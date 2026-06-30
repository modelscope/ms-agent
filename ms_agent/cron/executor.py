"""Job executor: bridges cron jobs to AgentLoader/WorkflowLoader."""
from __future__ import annotations

import asyncio
import contextvars
import os
import time
from pathlib import Path
from typing import Any, Optional

from ms_agent.cron.types import CronJobSpec, ExecutionResult

_CRON_CONTEXT: contextvars.ContextVar[bool] = contextvars.ContextVar(
    '_CRON_CONTEXT', default=False
)


def is_in_cron_context() -> bool:
    return _CRON_CONTEXT.get(False)


def _now_ms() -> int:
    return int(time.time() * 1000)


def resolve_project_path(raw: str) -> str:
    """Resolve a project reference to an absolute filesystem path.

    Handles: pip install (wheel), pip install -e . (editable), and
    arbitrary CWD (cron daemon, webui, agent tool).

    Resolution order:
      1. Absolute path that exists → return as-is
      2. Relative path that exists from CWD → resolve to absolute
      3. Bundled package project under ms_agent/projects/
         (works for wheel installs where build_py copies projects/)
      4. Source repo projects/ next to the ms_agent package
         (works for editable installs where ms_agent/projects/ doesn't exist)
      5. Fall through → return original string
         (Config.from_task will try ModelScope Hub download)

    Steps 3-4 also handle a leading "projects/" prefix so both
    "deep_research/v2" and "projects/deep_research/v2" resolve correctly.
    """
    if os.path.isabs(raw) and os.path.exists(raw):
        return raw
    if os.path.exists(raw):
        return os.path.abspath(raw)

    stripped = raw[len('projects/'):] if raw.startswith('projects/') else None
    candidates = [raw] if stripped is None else [raw, stripped]

    try:
        from importlib import resources
        pkg_dir = Path(str(resources.files('ms_agent')))

        # Step 3: wheel install — ms_agent/projects/<candidate>
        for name in candidates:
            p = pkg_dir / 'projects' / name
            if p.exists():
                return str(p.resolve())

        # Step 4: editable install — <repo_root>/projects/<candidate>
        repo_root = pkg_dir.parent
        for name in candidates:
            p = repo_root / 'projects' / name
            if p.exists():
                return str(p.resolve())
    except Exception:
        pass

    return raw


class JobExecutor:
    """Execute cron jobs via AgentLoader / WorkflowLoader.

    Features:
      - ContextVar guard to prevent recursive cron-in-cron calls.
      - Per-job asyncio.Lock for concurrency control.
      - Timeout enforcement with agent cleanup.
      - Output file writing.
    """

    def __init__(
        self,
        default_timeout: int = 600,
        semaphore: Optional[asyncio.Semaphore] = None,
        output_dir: Optional[Path] = None,
        session_dir: Optional[Path] = None,
    ):
        self._default_timeout = default_timeout
        self._semaphore = semaphore or asyncio.Semaphore(5)
        self._per_job_semas: dict[str, asyncio.Semaphore] = {}
        self._active_agents: dict[str, Any] = {}
        self._output_dir = output_dir
        self._session_dir = session_dir

    async def execute(self, job: CronJobSpec, config: Any) -> ExecutionResult:
        async with self._semaphore:
            job_sema = self._per_job_semas.get(job.id)
            if job_sema is None:
                job_sema = asyncio.Semaphore(max(1, job.concurrency))
                self._per_job_semas[job.id] = job_sema
            async with job_sema:
                return await self._do_execute(job, config)

    async def _do_execute(self, job: CronJobSpec, config: Any) -> ExecutionResult:
        if _CRON_CONTEXT.get(False):
            return ExecutionResult(
                success=False,
                error='Recursive cron execution detected — aborting.',
                duration_ms=0,
            )

        token = _CRON_CONTEXT.set(True)
        engine = None
        start_ms = _now_ms()
        try:
            engine = self._build_engine(job, config)
            self._active_agents[job.id] = engine
            timeout = job.timeout or self._default_timeout

            result_messages = await asyncio.wait_for(
                engine.run(job.prompt or ''),
                timeout=timeout,
            )

            output_text = self._extract_output(result_messages)
            duration = _now_ms() - start_ms

            if self._output_dir:
                self._write_output(job.id, output_text)

            return ExecutionResult(
                success=True,
                output=output_text,
                duration_ms=duration,
            )

        except asyncio.TimeoutError:
            return ExecutionResult(
                success=False,
                error=f'Execution timed out ({job.timeout or self._default_timeout}s)',
                duration_ms=_now_ms() - start_ms,
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                error=str(e),
                duration_ms=_now_ms() - start_ms,
            )
        finally:
            _CRON_CONTEXT.reset(token)
            if engine is not None and hasattr(engine, 'cleanup_tools'):
                try:
                    await engine.cleanup_tools()
                except Exception:
                    pass
            self._active_agents.pop(job.id, None)

    def _build_engine(self, job: CronJobSpec, config: Any) -> Any:
        """Build an agent or workflow engine based on job spec."""
        load_cache = getattr(config, 'load_cache', False)

        if job.workflow:
            from ms_agent.workflow.loader import WorkflowLoader
            return WorkflowLoader.build(
                config_dir_or_id=resolve_project_path(job.workflow),
                config=config,
                trust_remote_code=job.trust_remote_code,
            )
        elif job.project:
            from ms_agent.agent.loader import AgentLoader
            return AgentLoader.build(
                config_dir_or_id=resolve_project_path(job.project),
                config=config,
                trust_remote_code=job.trust_remote_code,
                load_cache=load_cache,
            )
        else:
            from ms_agent.agent.loader import AgentLoader
            return AgentLoader.build(
                config=config,
                trust_remote_code=job.trust_remote_code,
                load_cache=load_cache,
            )

    def _extract_output(self, messages: Any) -> str:
        """Extract the final assistant text from engine.run() result."""
        if isinstance(messages, list):
            for msg in reversed(messages):
                if isinstance(msg, dict):
                    if msg.get('role') == 'assistant':
                        return msg.get('content', '')
                elif hasattr(msg, 'role') and msg.role == 'assistant':
                    content = getattr(msg, 'content', '')
                    if isinstance(content, str):
                        return content
        elif isinstance(messages, str):
            return messages
        return ''

    def _write_output(self, job_id: str, output: str) -> None:
        """Write execution output to a timestamped markdown file."""
        if not self._output_dir:
            return
        job_dir = self._output_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime('%Y-%m-%d_%H-%M-%S')
        out_file = job_dir / f'{ts}.md'
        out_file.write_text(output, encoding='utf-8')
