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


def _load_deep_research_config() -> Dict[str, Any]:
    raw = os.environ.get('MS_AGENT_DEEP_RESEARCH_CONFIG')
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _normalize_agent_override(raw: Optional[Dict[str, Any]]) -> Dict[str, str]:
    raw = raw or {}
    return {
        'model': str(raw.get('model') or ''),
        'api_key': str(raw.get('api_key') or ''),
        'base_url': str(raw.get('base_url') or ''),
    }


def _resolve_agent_llm_config(role: str, llm_config: Dict[str, Any],
                              dr_config: Dict[str, Any]) -> Dict[str, str]:
    overrides = _normalize_agent_override((dr_config or {}).get(role))
    return {
        'model':
        overrides.get('model') or str(llm_config.get('model') or ''),
        'api_key':
        overrides.get('api_key') or str(llm_config.get('api_key') or ''),
        'base_url':
        overrides.get('base_url') or str(llm_config.get('base_url') or ''),
    }


def _normalize_search_override(
        raw: Optional[Dict[str, Any]]) -> Dict[str, str]:
    raw = raw or {}
    return {
        'summarizer_model': str(raw.get('summarizer_model') or ''),
        'summarizer_api_key': str(raw.get('summarizer_api_key') or ''),
        'summarizer_base_url': str(raw.get('summarizer_base_url') or ''),
    }


def _build_config_override(
        llm_config: Dict[str, Any], output_dir: str,
        dr_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    override: Dict[str, Any] = {}
    if output_dir:
        override['output_dir'] = output_dir

    llm_override: Dict[str, Any] = {}
    resolved = _resolve_agent_llm_config('researcher', llm_config, dr_config)
    model = resolved.get('model')
    api_key = resolved.get('api_key')
    base_url = resolved.get('base_url')
    temperature = llm_config.get('temperature')
    temperature_enabled = bool(llm_config.get('temperature_enabled', False))
    max_tokens = llm_config.get('max_tokens')

    if model:
        llm_override['model'] = model

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
    dr_config = _load_deep_research_config()
    config_override = _build_config_override(llm_config, args.output_dir,
                                             dr_config)
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

                    tool_name = str(spec.tool_name or '')
                    if 'searcher' in tool_name:
                        resolved = _resolve_agent_llm_config(
                            'searcher', llm_config, dr_config)
                        search_override = _normalize_search_override(
                            (dr_config or {}).get('search'))
                    elif 'reporter' in tool_name:
                        resolved = _resolve_agent_llm_config(
                            'reporter', llm_config, dr_config)
                        search_override = {}
                    else:
                        resolved = {}
                        search_override = {}

                    if resolved:
                        updated = dict(spec.inline_config or {})
                        llm_cfg = dict(updated.get('llm') or {})
                        if resolved.get('model'):
                            llm_cfg['model'] = resolved['model']
                        if resolved.get('api_key'):
                            llm_cfg['openai_api_key'] = resolved['api_key']
                        if resolved.get('base_url'):
                            llm_cfg['openai_base_url'] = resolved['base_url']
                        if llm_cfg:
                            updated['llm'] = llm_cfg
                        if search_override:
                            tools_cfg = dict(updated.get('tools') or {})
                            web_cfg = dict(tools_cfg.get('web_search') or {})
                            if search_override.get('summarizer_model'):
                                web_cfg['summarizer_model'] = search_override[
                                    'summarizer_model']
                            if search_override.get('summarizer_api_key'):
                                web_cfg[
                                    'summarizer_api_key'] = search_override[
                                        'summarizer_api_key']
                            if search_override.get('summarizer_base_url'):
                                web_cfg[
                                    'summarizer_base_url'] = search_override[
                                        'summarizer_base_url']
                            if web_cfg:
                                tools_cfg['web_search'] = web_cfg
                                updated['tools'] = tools_cfg
                        spec.inline_config = updated

                        env_cfg = dict(spec.env or {})
                        if resolved.get('api_key'):
                            env_cfg['OPENAI_API_KEY'] = resolved['api_key']
                        if resolved.get('base_url'):
                            env_cfg['OPENAI_BASE_URL'] = resolved['base_url']
                        spec.env = env_cfg

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
