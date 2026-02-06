import asyncio
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

import json


class DeepResearchWorkerManager:

    def __init__(self, send_event: Callable[[str, Dict[str, Any]],
                                            Awaitable[None]]):
        self._send_event = send_event
        self._processes: Dict[str, asyncio.subprocess.Process] = {}
        self._stdout_tasks: Dict[str, asyncio.Task] = {}
        self._stderr_tasks: Dict[str, asyncio.Task] = {}
        self._stopping: set[str] = set()

    def _get_repo_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _get_worker_path(self) -> Path:
        return Path(__file__).resolve().parent / 'deep_research_worker.py'

    def _build_env(self, env_vars: Optional[Dict[str, str]],
                   llm_config: Optional[Dict[str, Any]],
                   deep_research_config: Optional[Dict[str, Any]]) -> Dict[str, str]:
        env = os.environ.copy()
        if env_vars:
            env.update({k: v for k, v in env_vars.items() if v})
        if llm_config:
            env['MS_AGENT_LLM_CONFIG'] = json.dumps(
                llm_config, ensure_ascii=False)
        if deep_research_config:
            env['MS_AGENT_DEEP_RESEARCH_CONFIG'] = json.dumps(
                deep_research_config, ensure_ascii=False)

        api_key = (llm_config or {}).get('api_key')
        base_url = (llm_config or {}).get('base_url')
        if api_key and not env.get('OPENAI_API_KEY'):
            env['OPENAI_API_KEY'] = api_key
        if base_url and not env.get('OPENAI_BASE_URL'):
            env['OPENAI_BASE_URL'] = base_url
        env['PYTHONUNBUFFERED'] = '1'
        repo_root = str(self._get_repo_root())
        existing_path = env.get('PYTHONPATH', '')
        if repo_root not in existing_path.split(os.pathsep):
            env['PYTHONPATH'] = repo_root + (
                os.pathsep + existing_path if existing_path else '')
        return env

    async def start(self,
                    session_id: str,
                    *,
                    query: str,
                    config_path: str,
                    output_dir: str,
                    env_vars: Optional[Dict[str, str]] = None,
                    llm_config: Optional[Dict[str, Any]] = None,
                    deep_research_config: Optional[Dict[str, Any]] = None) -> None:
        if session_id in self._processes:
            await self.stop(session_id)

        worker_path = self._get_worker_path()
        output_dir_path = Path(output_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            str(worker_path),
            '--config',
            config_path,
            '--query',
            query,
            '--session_id',
            session_id,
            '--output_dir',
            str(output_dir_path),
        ]

        env = self._build_env(env_vars, llm_config, deep_research_config)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(self._get_repo_root()),
            start_new_session=True,
        )

        self._processes[session_id] = process
        self._stdout_tasks[session_id] = asyncio.create_task(
            self._read_stdout(session_id, process))
        self._stderr_tasks[session_id] = asyncio.create_task(
            self._read_stderr(session_id, process))
        await self._send_event(
            session_id, {
                'type': 'log',
                'level': 'info',
                'message': f'Deep research worker started (pid={process.pid})',
                'timestamp': datetime.now().isoformat(),
            })

    async def stop(self, session_id: str) -> None:
        process = self._processes.get(session_id)
        if not process:
            return

        try:
            self._stopping.add(session_id)
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except Exception:
                    try:
                        process.terminate()
                    except Exception:
                        pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except Exception:
                        try:
                            process.kill()
                        except Exception:
                            pass
        finally:
            self._cleanup(session_id)

    async def _read_stdout(self, session_id: str,
                           process: asyncio.subprocess.Process) -> None:
        if not process.stdout:
            return
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            text = line.decode('utf-8', errors='replace').strip()
            if not text:
                continue
            try:
                event = json.loads(text)
            except Exception:
                continue
            try:
                await self._send_event(session_id, event)
            except Exception:
                pass
        return_code = process.returncode
        if return_code is None:
            try:
                return_code = await process.wait()
            except Exception:
                return_code = None
        if return_code not in (None, 0) and session_id not in self._stopping:
            await self._send_event(
                session_id, {
                    'type':
                    'error',
                    'message':
                    f'Deep research worker exited with code {return_code}',
                })
            await self._send_event(session_id, {
                'type': 'status',
                'status': 'error'
            })
        self._cleanup(session_id)

    async def _read_stderr(self, session_id: str,
                           process: asyncio.subprocess.Process) -> None:
        if not process.stderr:
            return
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            # Keep stderr for server logs; avoid polluting stdout stream.
            try:
                text = line.decode('utf-8', errors='replace')
                sys.stderr.write(text)
                sys.stderr.flush()
                await self._send_event(
                    session_id, {
                        'type': 'log',
                        'level': 'error',
                        'message': f'[deep_research_worker] {text.strip()}',
                        'timestamp': datetime.now().isoformat(),
                    })
            except Exception:
                pass

    def _cleanup(self, session_id: str) -> None:
        task = self._stdout_tasks.pop(session_id, None)
        if task:
            task.cancel()
        task = self._stderr_tasks.pop(session_id, None)
        if task:
            task.cancel()
        self._processes.pop(session_id, None)
        self._stopping.discard(session_id)
