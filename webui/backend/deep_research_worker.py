import argparse
import asyncio
import os
import signal
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

import json
from deep_research_eventizer import HistoryEventizer  # noqa: E402
from ms_agent.agent.loader import AgentLoader
from ms_agent.tools.agent_tool import AgentTool
from omegaconf import OmegaConf

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

STOP_REQUESTED = False


class NullWriter:

    def write(self, _: str) -> int:
        return 0

    def flush(self) -> None:
        return None


class NDJSONEmitter:

    def __init__(self, stream) -> None:
        self._stream = stream

    def emit(self, event: Dict[str, Any]) -> None:
        try:
            self._stream.write(json.dumps(event, ensure_ascii=False) + '\n')
            self._stream.flush()
        except Exception:
            pass


def _load_llm_config() -> Dict[str, Any]:
    raw = os.environ.get('MS_AGENT_LLM_CONFIG')
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _build_config_override(llm_config: Dict[str, Any],
                           output_dir: str) -> Optional[Dict[str, Any]]:
    override: Dict[str, Any] = {}
    if output_dir:
        override['output_dir'] = output_dir

    llm_override: Dict[str, Any] = {}
    provider = (llm_config.get('provider') or '').strip()
    model = llm_config.get('model')
    api_key = llm_config.get('api_key')
    base_url = llm_config.get('base_url')
    temperature = llm_config.get('temperature')
    temperature_enabled = bool(llm_config.get('temperature_enabled', False))
    max_tokens = llm_config.get('max_tokens')

    if provider in {'modelscope', 'openai', 'anthropic', 'dashscope'}:
        llm_override['service'] = provider
    else:
        llm_override['service'] = 'openai'

    if model:
        llm_override['model'] = model

    if llm_override['service'] == 'modelscope':
        if api_key:
            llm_override['modelscope_api_key'] = api_key
        if base_url:
            llm_override['modelscope_base_url'] = base_url
    elif llm_override['service'] == 'anthropic':
        if api_key:
            llm_override['anthropic_api_key'] = api_key
        if base_url:
            llm_override['anthropic_base_url'] = base_url
    else:
        if api_key:
            llm_override['openai_api_key'] = api_key
        if base_url:
            llm_override['openai_base_url'] = base_url

    if llm_override:
        override['llm'] = llm_override

    gen_override: Dict[str, Any] = {}
    if temperature_enabled and temperature is not None:
        gen_override['temperature'] = temperature
    if max_tokens:
        gen_override['max_tokens'] = max_tokens
    if gen_override:
        override['generation_config'] = gen_override

    return override or None


async def _watch_artifacts(output_dir: str, emitter: NDJSONEmitter,
                           session_id: str) -> None:
    last_snapshot: Dict[str, tuple[int, float]] = {}
    output_path = Path(output_dir)
    ignore_dirs = {'.locks', '__pycache__'}

    while True:
        snapshot: Dict[str, tuple[int, float]] = {}
        files = []
        if output_path.exists():
            for path in output_path.rglob('*'):
                if path.is_dir():
                    if path.name in ignore_dirs:
                        continue
                    continue
                rel_path = path.relative_to(output_path).as_posix()
                if rel_path.startswith('.locks/'):
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                snapshot[rel_path] = (stat.st_size, stat.st_mtime)
                files.append({
                    'path': rel_path,
                    'relative_path': rel_path,
                    'size': stat.st_size,
                    'modified': stat.st_mtime,
                })

        if snapshot != last_snapshot:
            emitter.emit({
                'type': 'dr.artifact.updated',
                'payload': {
                    'files':
                    sorted(
                        files,
                        key=lambda x: x.get('modified', 0),
                        reverse=True)
                },
                'session_id': session_id,
            })
            last_snapshot = snapshot

        await asyncio.sleep(1.0)


async def run_worker(args: argparse.Namespace) -> None:
    emitter = NDJSONEmitter(sys.__stdout__)
    main_eventizer = HistoryEventizer(
        emitter.emit, channel='main', session_id=args.session_id)
    subagent_eventizers: Dict[str, HistoryEventizer] = {}

    loop = asyncio.get_running_loop()
    subagent_queue: asyncio.Queue = asyncio.Queue()

    def chunk_callback(*, event_type: str, data: Dict[str, Any]) -> None:
        loop.call_soon_threadsafe(subagent_queue.put_nowait,
                                  (event_type, data))

    async def consume_subagent_events():
        while True:
            event_type, data = await subagent_queue.get()
            if event_type is None:
                break
            call_id = data.get('call_id')
            if not call_id:
                continue
            eventizer = subagent_eventizers.get(call_id)
            if not eventizer:
                eventizer = HistoryEventizer(
                    emitter.emit,
                    channel='subagent',
                    session_id=args.session_id,
                    card_id=call_id,
                )
                subagent_eventizers[call_id] = eventizer
            history = data.get('history')
            if isinstance(history, list):
                eventizer.process(history)

    llm_config = _load_llm_config()
    config_override = _build_config_override(llm_config, args.output_dir)
    config_override = OmegaConf.create(
        config_override) if config_override else None

    agent = AgentLoader.build(
        config_dir_or_id=args.config,
        config=config_override,
        env=os.environ.copy(),
        trust_remote_code=True,
        load_cache=True,
    )

    original_prepare_tools = agent.prepare_tools

    async def prepare_tools_with_callback():
        await original_prepare_tools()
        if getattr(agent, 'tool_manager', None) is None:
            return
        for tool in agent.tool_manager.extra_tools:
            if isinstance(tool, AgentTool):
                tool.set_chunk_callback(chunk_callback)
                for spec in getattr(tool, '_specs', {}).values():
                    inline_cfg = spec.inline_config or {}
                    if inline_cfg.get('output_dir') != args.output_dir:
                        updated = dict(inline_cfg)
                        updated['output_dir'] = args.output_dir
                        spec.inline_config = updated

    agent.prepare_tools = prepare_tools_with_callback

    artifact_task = asyncio.create_task(
        _watch_artifacts(args.output_dir, emitter, args.session_id))
    subagent_task = asyncio.create_task(consume_subagent_events())

    had_error = False
    try:
        result = await agent.run(messages=args.query, stream=True)
        if hasattr(result, '__aiter__'):
            async for history in result:
                if isinstance(history, list):
                    main_eventizer.process(history)
        elif isinstance(result, list):
            main_eventizer.process(result)
    except Exception as exc:
        had_error = True
        emitter.emit({
            'type': 'dr.worker.error',
            'payload': {
                'error': str(exc),
                'traceback': traceback.format_exc(),
            },
            'session_id': args.session_id,
        })
        emitter.emit({
            'type': 'error',
            'message': str(exc),
        })
        raise
    finally:
        main_eventizer.finalize()
        emitter.emit({
            'type': 'dr.worker.exited',
            'payload': {
                'status': 'completed'
            },
            'session_id': args.session_id,
        })
        if STOP_REQUESTED:
            emitter.emit({
                'type': 'status',
                'status': 'stopped',
            })
        elif not had_error:
            emitter.emit({
                'type': 'complete',
                'result': {
                    'status': 'success',
                },
            })
        subagent_queue.put_nowait((None, None))
        artifact_task.cancel()
        subagent_task.cancel()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, help='Path to agent yaml')
    parser.add_argument('--query', required=True, help='User query')
    parser.add_argument('--session_id', required=True)
    parser.add_argument('--output_dir', required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sys.argv = [sys.argv[0]]
    sys.stdout = NullWriter()

    def _handle_stop(_sig, _frame):
        global STOP_REQUESTED
        STOP_REQUESTED = True

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    asyncio.run(run_worker(args))


if __name__ == '__main__':
    main()
