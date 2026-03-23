# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import multiprocessing as mp
import os
import threading
import traceback
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from queue import Empty as QueueEmpty
from queue import Full as QueueFull
from typing import Any, Callable, Dict, List, Optional, Union

import json
from ms_agent.agent.loader import AgentLoader
from ms_agent.llm.utils import Message, Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger
from ms_agent.utils.stats import (append_stats, build_timing_record,
                                  get_stats_path, monotonic, now_iso,
                                  summarize_usage)
from ms_agent.utils.thread_util import DaemonThreadPoolExecutor
from omegaconf import DictConfig, ListConfig, OmegaConf

logger = get_logger()


def _to_container(value: Any) -> Any:
    if isinstance(value, DictConfig):
        return OmegaConf.to_container(value, resolve=True)
    if isinstance(value, ListConfig):
        return OmegaConf.to_container(value, resolve=True)
    return value


@dataclass
class _AgentToolSpec:
    tool_name: str
    description: str
    parameters: Dict[str, Any]
    config_path: Optional[str]
    inline_config: Optional[Dict[str, Any]]
    server_name: str
    tag_prefix: str
    input_mode: str
    request_field: Optional[str]
    input_template: Optional[str]
    output_mode: str
    max_output_chars: int
    trust_remote_code: Optional[bool]
    env: Optional[Dict[str, str]]
    run_in_thread: bool
    run_in_process: bool


_MESSAGE_FIELDS = set(Message.__dataclass_fields__.keys())


def _message_from_data(data: Any) -> Message:
    if isinstance(data, Message):
        return data
    if isinstance(data, dict):
        msg_kwargs = {k: data[k] for k in _MESSAGE_FIELDS if k in data}
        if 'role' not in msg_kwargs:
            msg_kwargs['role'] = 'assistant'
        msg_kwargs.setdefault('content', '')
        return Message(**msg_kwargs)
    return Message(role='assistant', content=str(data))


def _build_sub_agent(spec: _AgentToolSpec, default_trust_remote_code: bool):
    if spec.inline_config is not None:
        config_override = OmegaConf.create(spec.inline_config)
    else:
        config_override = None

    trust_remote_code = spec.trust_remote_code
    if trust_remote_code is None:
        trust_remote_code = default_trust_remote_code

    tag = f'{spec.tag_prefix}{uuid.uuid4().hex[:8]}'
    agent = AgentLoader.build(
        config_dir_or_id=spec.config_path,
        config=config_override,
        env=spec.env,
        tag=tag,
        trust_remote_code=trust_remote_code,
    )

    generation_cfg = getattr(agent.config, 'generation_config', DictConfig({}))
    agent.config.generation_config = generation_cfg
    return agent


def _run_agent_in_subprocess(
    spec: _AgentToolSpec,
    default_trust_remote_code: bool,
    payload: Any,
    stream_events: bool,
    event_queue: Any,
    result_queue: Any,
) -> None:
    sub_agent = None
    try:
        sub_agent = _build_sub_agent(spec, default_trust_remote_code)
        run_payload = payload
        if isinstance(run_payload, list):
            run_payload = [_message_from_data(msg) for msg in run_payload]

        async def _runner():
            chunk_count = 0
            if stream_events:
                result = await sub_agent.run(run_payload, stream=True)
            else:
                result = await sub_agent.run(run_payload)
            if hasattr(result, '__aiter__'):
                history = None
                async for chunk in result:
                    history = chunk
                    if stream_events and event_queue is not None:
                        serialized_chunk = {
                            'kind':
                            'messages',
                            'messages': [
                                _message_from_data(msg).to_dict()
                                for msg in (history or [])
                            ],
                        }
                        try:
                            event_queue.put_nowait({
                                'type': 'chunk',
                                'history': serialized_chunk
                            })
                        except QueueFull:
                            # Avoid blocking sub-agent progress if UI/event consumer
                            # is temporarily slower than chunk production.
                            pass
                    chunk_count += 1
                result = history
            if isinstance(result, list):
                return {
                    'kind':
                    'messages',
                    'messages':
                    [_message_from_data(msg).to_dict() for msg in result],
                    'streamed_chunks':
                    chunk_count,
                    'agent_tag':
                    getattr(sub_agent, 'tag', None),
                    'agent_type':
                    getattr(sub_agent, 'AGENT_NAME', None),
                }
            return {
                'kind': 'raw',
                'raw': str(result),
                'streamed_chunks': chunk_count,
                'agent_tag': getattr(sub_agent, 'tag', None),
                'agent_type': getattr(sub_agent, 'AGENT_NAME', None),
            }

        result_queue.put({'ok': True, 'result': asyncio.run(_runner())})
    except BaseException as exc:  # pragma: no cover
        result_queue.put({
            'ok': False,
            'error': str(exc),
            'traceback': traceback.format_exc(),
            'agent_tag': getattr(sub_agent, 'tag', None),
            'agent_type': getattr(sub_agent, 'AGENT_NAME', None),
        })


class AgentTool(ToolBase):
    """Expose existing ms-agent agents as callable tools."""

    DEFAULT_SERVER = 'agent_tools'
    _PROCESS_POLL_INTERVAL_S = 0.05
    _PROCESS_EXIT_RESULT_GRACE_S = 1.0
    _PROCESS_FINAL_JOIN_TIMEOUT_S = 1.0

    def __init__(self, config: DictConfig, **kwargs):
        super().__init__(config)
        self._trust_remote_code = kwargs.get('trust_remote_code', True)
        self._enable_stats = False
        self._specs: Dict[str, _AgentToolSpec] = {}
        self._server_tools: Dict[str, List[Tool]] = {}
        self._thread_executor: Optional[ThreadPoolExecutor] = None
        self._thread_max_workers: int = 0
        self._chunk_cb: Optional[Callable[..., Any]] = None
        self._active_processes: Dict[str, mp.Process] = {}
        self._active_processes_lock = threading.Lock()
        self._load_specs()
        self._init_thread_pool_config()

    def _init_thread_pool_config(self):
        tools_cfg = getattr(self.config, 'tools', DictConfig({}))
        agent_tools_cfg = getattr(tools_cfg, 'agent_tools', DictConfig({}))
        max_workers = getattr(agent_tools_cfg, 'max_workers', None)
        if max_workers is None:
            max_workers = os.getenv('AGENT_TOOL_MAX_WORKERS', None)
        try:
            self._thread_max_workers = int(max_workers) if max_workers else 3
        except Exception:
            self._thread_max_workers = 3

    @property
    def enabled(self) -> bool:
        return bool(self._specs)

    def _load_specs(self):
        tools_cfg = getattr(self.config, 'tools', DictConfig({}))
        agent_tools_cfg = getattr(tools_cfg, 'agent_tools', None)
        if agent_tools_cfg is None:
            return

        if isinstance(agent_tools_cfg, DictConfig) and hasattr(
                agent_tools_cfg, 'definitions'):
            definitions = agent_tools_cfg.definitions
            server_name = getattr(agent_tools_cfg, 'server_name',
                                  self.DEFAULT_SERVER)
            self._enable_stats = bool(
                getattr(agent_tools_cfg, 'enable_stats', False))
        else:
            definitions = agent_tools_cfg
            server_name = self.DEFAULT_SERVER

        definitions_list: List[Any]
        if isinstance(definitions, DictConfig):
            definitions_list = [definitions]
        elif isinstance(definitions, ListConfig):
            definitions_list = list(definitions)
        elif isinstance(definitions, list):
            definitions_list = definitions
        else:
            logger.warning('agent_tools configuration is not iterable; skip.')
            return

        for idx, spec_cfg in enumerate(definitions_list):
            spec = self._build_spec(spec_cfg, server_name, idx)
            if spec is None:
                continue
            if spec.tool_name in self._specs:
                logger.warning(
                    'Duplicate agent tool name detected: %s, overriding previous definition.',
                    spec.tool_name)
            self._specs[spec.tool_name] = spec

        self._build_server_index()

    def _build_spec(self, cfg: Union[DictConfig, Dict[str, Any]],
                    default_server, idx: int) -> Optional[_AgentToolSpec]:
        cfg = cfg or {}
        cfg = cfg if isinstance(cfg, DictConfig) else DictConfig(cfg)
        tool_name = getattr(cfg, 'tool_name', None) or getattr(
            cfg, 'name', None)
        if not tool_name:
            logger.warning(
                'agent_tools[%s] missing tool_name/name field, skip.', idx)
            return None

        agent_cfg = getattr(cfg, 'agent', None)
        config_path = getattr(cfg, 'config_path', None)
        inline_cfg = getattr(cfg, 'config', None)
        if agent_cfg is not None:
            config_path = getattr(agent_cfg, 'config_path', config_path)
            inline_cfg = getattr(agent_cfg, 'config', inline_cfg)
        inline_cfg = _to_container(
            inline_cfg) if inline_cfg is not None else None

        if not config_path and inline_cfg is None:
            logger.warning(
                'agent_tools[%s] (%s) missing config_path/config definition.',
                idx, tool_name)
            return None

        description = getattr(cfg, 'description',
                              f'Invoke agent "{tool_name}" as a tool.')
        parameters = getattr(cfg, 'parameters', None)
        if parameters is None:
            parameters = {
                'type': 'object',
                'properties': {
                    'request': {
                        'type':
                        'string',
                        'description':
                        f'Task description forwarded to the sub-agent {tool_name}.'
                    },
                },
                'required': ['request'],
                'additionalProperties': True,
            }
        else:
            parameters = _to_container(parameters)

        tag_prefix = getattr(
            cfg, 'tag_prefix',
            f'{getattr(self.config, "tag", "agent")}-{tool_name}-')

        request_field = getattr(cfg, 'request_field', 'request')
        input_template = getattr(cfg, 'input_template', None)
        input_mode = getattr(cfg, 'input_mode', 'text')
        output_mode = getattr(cfg, 'output_mode', 'final_message')
        max_chars = int(getattr(cfg, 'max_output_chars', 100000))
        server_name = getattr(cfg, 'server_name', default_server)
        trust_remote_code = getattr(cfg, 'trust_remote_code', None)
        # Run sub-agent in a background thread to avoid blocking the main event loop
        # when underlying LLM SDKs are synchronous.
        run_in_thread = bool(getattr(cfg, 'run_in_thread', True))
        # Run sub-agent in an isolated process so timed-out calls can be killed.
        run_in_process = bool(getattr(cfg, 'run_in_process', run_in_thread))

        env_cfg = getattr(cfg, 'env', None)
        env_cfg = _to_container(env_cfg) if env_cfg is not None else None

        if config_path and not os.path.isabs(config_path):
            base_dir = getattr(self.config, 'local_dir', None)
            if base_dir:
                config_path = os.path.normpath(
                    os.path.join(base_dir, config_path))

        return _AgentToolSpec(
            tool_name=tool_name,
            description=description,
            parameters=parameters,
            config_path=config_path,
            inline_config=inline_cfg,
            server_name=server_name,
            tag_prefix=tag_prefix,
            input_mode=input_mode,
            request_field=request_field,
            input_template=input_template,
            output_mode=output_mode,
            max_output_chars=max_chars,
            trust_remote_code=trust_remote_code,
            env=env_cfg,
            run_in_thread=run_in_thread,
            run_in_process=run_in_process,
        )

    def _build_server_index(self):
        server_map: Dict[str, List[Tool]] = {}
        for spec in self._specs.values():
            server_map.setdefault(spec.server_name, []).append(
                Tool(
                    tool_name=spec.tool_name,
                    server_name=spec.server_name,
                    description=spec.description,
                    parameters=spec.parameters,
                ))
        self._server_tools = server_map

    async def connect(self):
        # Lazily initialize a dedicated pool for agent tools that opt into
        # `run_in_thread`, so we don't consume threads when the tool is unused.
        if self._thread_executor is None:
            # Use daemon threads to avoid blocking process exit when sub-agent
            # calls are cancelled by tool-call timeouts.
            self._thread_executor = DaemonThreadPoolExecutor(
                max_workers=self._thread_max_workers,
                thread_name_prefix='agent_tool_',
            )
        return None

    async def cleanup(self):
        self._terminate_all_active_processes(reason='during AgentTool cleanup')
        if self._thread_executor is not None:
            try:
                try:
                    self._thread_executor.shutdown(
                        wait=False, cancel_futures=True)
                except TypeError:
                    self._thread_executor.shutdown(wait=False)
            except Exception:
                pass
            self._thread_executor = None
        return None

    async def get_tools(self) -> Dict[str, Any]:
        return self._server_tools

    def set_chunk_callback(self, cb: Optional[Callable[..., Any]]) -> None:
        self._chunk_cb = cb

    def _emit_chunk_event(self, event_type: str, data: Dict[str, Any]) -> None:
        if not self._chunk_cb:
            return
        try:
            self._chunk_cb(event_type=event_type, data=data)
        except TypeError:
            try:
                self._chunk_cb(event_type, data)
            except Exception as exc:  # noqa
                logger.warning(f'AgentTool chunk callback failed: {exc}')
        except Exception as exc:  # noqa
            logger.warning(f'AgentTool chunk callback failed: {exc}')

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        if tool_name not in self._specs:
            raise ValueError(f'Agent tool "{tool_name}" not registered.')
        spec = self._specs[tool_name]
        if spec.server_name != server_name:
            raise ValueError(
                f'Agent tool "{tool_name}" is not part of server "{server_name}".'
            )

        call_id = None
        if isinstance(tool_args, dict) and '__call_id' in tool_args:
            call_id = tool_args.pop('__call_id', None)
        payload = self._build_payload(tool_args, spec)
        use_subprocess = spec.run_in_thread and spec.run_in_process
        agent = None if use_subprocess else self._build_agent(spec)
        messages = await self._run_agent(agent, payload, spec, call_id=call_id)
        return self._format_output(messages, spec)

    def _build_agent(self, spec: _AgentToolSpec):
        return _build_sub_agent(spec, self._trust_remote_code)

    @staticmethod
    def _terminate_process(proc: Optional[mp.Process], *, reason: str) -> None:
        if proc is None:
            return
        if not proc.is_alive():
            try:
                proc.join(timeout=0.05)
            except Exception:
                pass
            return

        logger.warning(
            'AgentTool subprocess pid=%s %s, terminating.',
            getattr(proc, 'pid', None),
            reason,
        )
        try:
            proc.terminate()
            proc.join(timeout=1.0)
        except Exception:
            pass
        if proc.is_alive():
            logger.warning(
                'AgentTool subprocess pid=%s did not terminate gracefully, killing.',
                getattr(proc, 'pid', None),
            )
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.join(timeout=1.0)
            except Exception:
                pass

    def _register_process(self, run_id: str, proc: mp.Process) -> None:
        with self._active_processes_lock:
            self._active_processes[run_id] = proc

    def _unregister_process(self, run_id: str) -> None:
        with self._active_processes_lock:
            self._active_processes.pop(run_id, None)

    def _terminate_all_active_processes(self, *, reason: str) -> None:
        with self._active_processes_lock:
            active = list(self._active_processes.items())
            self._active_processes.clear()
        for _, proc in active:
            self._terminate_process(proc, reason=reason)

    async def _wait_process_result(self,
                                   proc: mp.Process,
                                   result_queue: Any,
                                   on_poll: Optional[Callable[[],
                                                              None]] = None):
        exited_at = None
        while True:
            if on_poll is not None:
                on_poll()
            try:
                return result_queue.get_nowait()
            except QueueEmpty:
                pass

            # Process can exit slightly before queue payload becomes visible.
            # Keep polling for a short grace window to avoid false "no result".
            if not proc.is_alive():
                if exited_at is None:
                    exited_at = monotonic()
                elif (monotonic()
                      - exited_at) >= self._PROCESS_EXIT_RESULT_GRACE_S:
                    return None

            await asyncio.sleep(self._PROCESS_POLL_INTERVAL_S)

    @staticmethod
    def _drain_process_event_queue(
            event_queue: Any, on_event: Callable[[Dict[str, Any]],
                                                 None]) -> None:
        if event_queue is None:
            return
        while True:
            try:
                event = event_queue.get_nowait()
            except QueueEmpty:
                return
            if isinstance(event, dict):
                on_event(event)

    def _serialize_payload_for_process(self, payload: Any) -> Any:
        if not isinstance(payload, list):
            return payload
        return [_message_from_data(msg).to_dict() for msg in payload]

    @staticmethod
    def _restore_process_result(result_payload: Dict[str, Any]) -> Any:
        kind = result_payload.get('kind')
        if kind == 'messages':
            messages = result_payload.get('messages') or []
            return [_message_from_data(msg) for msg in messages]
        return result_payload.get('raw', '')

    async def _run_agent(self,
                         agent,
                         payload,
                         spec: _AgentToolSpec,
                         call_id: Optional[str] = None):
        runtime_agent = agent
        runtime_agent_tag = getattr(runtime_agent, 'tag', None)
        runtime_agent_type = getattr(runtime_agent, 'AGENT_NAME', None)

        async def _run_and_collect():
            nonlocal runtime_agent, runtime_agent_tag, runtime_agent_type
            if runtime_agent is None:
                runtime_agent = self._build_agent(spec)
                runtime_agent_tag = getattr(runtime_agent, 'tag', None)
                runtime_agent_type = getattr(runtime_agent, 'AGENT_NAME', None)
            if self._chunk_cb:
                result = await runtime_agent.run(payload, stream=True)
            else:
                result = await runtime_agent.run(payload)
            if hasattr(result, '__aiter__'):
                history = None
                self._emit_chunk_event('start', {
                    'call_id': call_id,
                    'tool_name': spec.tool_name,
                })
                async for chunk in result:
                    history = chunk
                    self._emit_chunk_event(
                        'chunk', {
                            'call_id': call_id,
                            'tool_name': spec.tool_name,
                            'history': chunk,
                        })
                if history is not None:
                    self._emit_chunk_event(
                        'end', {
                            'call_id': call_id,
                            'tool_name': spec.tool_name,
                            'history': history,
                        })
                result = history
            else:
                self._emit_chunk_event('start', {
                    'call_id': call_id,
                    'tool_name': spec.tool_name,
                })
                self._emit_chunk_event(
                    'chunk', {
                        'call_id': call_id,
                        'tool_name': spec.tool_name,
                        'history': result,
                    })
                self._emit_chunk_event(
                    'end', {
                        'call_id': call_id,
                        'tool_name': spec.tool_name,
                        'history': result,
                    })
            return result

        async def _run_in_background():
            # Run sub-agent in a dedicated event loop in a background thread.
            def _sync_runner():
                return asyncio.run(_run_and_collect())

            loop = asyncio.get_running_loop()
            if self._thread_executor is not None:
                return await loop.run_in_executor(self._thread_executor,
                                                  _sync_runner)
            return await asyncio.to_thread(_sync_runner)

        async def _run_in_subprocess():
            nonlocal runtime_agent_tag, runtime_agent_type
            ctx = mp.get_context('spawn')
            result_queue = ctx.Queue(maxsize=1)
            event_queue = ctx.Queue(
                maxsize=128) if self._chunk_cb is not None else None
            proc: Optional[mp.Process] = None
            run_id = f'{call_id or "agent_tool"}-{uuid.uuid4().hex[:8]}'

            def _emit_stream_event(event: Dict[str, Any]) -> None:
                if not self._chunk_cb:
                    return
                history_payload = event.get('history')
                if not isinstance(history_payload, dict):
                    return
                history = self._restore_process_result(history_payload)
                self._emit_chunk_event(
                    'chunk', {
                        'call_id': call_id,
                        'tool_name': spec.tool_name,
                        'history': history,
                    })

            try:
                if self._chunk_cb:
                    self._emit_chunk_event('start', {
                        'call_id': call_id,
                        'tool_name': spec.tool_name,
                    })
                process_payload = self._serialize_payload_for_process(payload)
                proc = ctx.Process(
                    target=_run_agent_in_subprocess,
                    args=(spec, self._trust_remote_code, process_payload,
                          self._chunk_cb
                          is not None, event_queue, result_queue),
                    name=f'agent_tool_{spec.tool_name}',
                )
                proc.start()
                self._register_process(run_id, proc)
                result = await self._wait_process_result(
                    proc,
                    result_queue,
                    on_poll=lambda: self._drain_process_event_queue(
                        event_queue, _emit_stream_event))
                if result is None:
                    raise RuntimeError(
                        f'AgentTool subprocess exited without result: {spec.tool_name}'
                    )
                self._drain_process_event_queue(event_queue,
                                                _emit_stream_event)
                if not result.get('ok'):
                    runtime_agent_tag = result.get(
                        'agent_tag') or runtime_agent_tag
                    runtime_agent_type = result.get(
                        'agent_type') or runtime_agent_type
                    tb = result.get('traceback', '')
                    if tb:
                        logger.warning(tb)
                    raise RuntimeError(
                        f'Sub-agent {spec.tool_name} failed: {result.get("error", "unknown error")}'
                    )
                result_payload = result.get('result', {}) or {}
                runtime_agent_tag = result_payload.get(
                    'agent_tag') or runtime_agent_tag
                runtime_agent_type = result_payload.get(
                    'agent_type') or runtime_agent_type
                restored = self._restore_process_result(result_payload)
                streamed_chunks = int(
                    result_payload.get('streamed_chunks', 0) or 0)
                if self._chunk_cb:
                    if streamed_chunks <= 0:
                        self._emit_chunk_event(
                            'chunk', {
                                'call_id': call_id,
                                'tool_name': spec.tool_name,
                                'history': restored,
                            })
                    self._emit_chunk_event(
                        'end', {
                            'call_id': call_id,
                            'tool_name': spec.tool_name,
                            'history': restored,
                        })
                return restored
            except asyncio.CancelledError:
                self._terminate_process(proc, reason='was cancelled')
                raise
            except Exception:
                self._terminate_process(proc, reason='encountered error')
                raise
            finally:
                self._unregister_process(run_id)
                if proc is not None:
                    try:
                        proc.join(timeout=self._PROCESS_FINAL_JOIN_TIMEOUT_S)
                    except Exception:
                        pass
                    if proc.is_alive():
                        self._terminate_process(
                            proc, reason='did not exit after result handling')
                try:
                    result_queue.close()
                    result_queue.join_thread()
                except Exception:
                    pass
                if event_queue is not None:
                    try:
                        event_queue.close()
                        event_queue.join_thread()
                    except Exception:
                        pass

        if spec.run_in_thread and spec.run_in_process:
            runner = _run_in_subprocess
        elif spec.run_in_thread:
            runner = _run_in_background
        else:
            runner = _run_and_collect

        if not self._enable_stats:
            return await runner()

        start_ts = now_iso()
        start_time = monotonic()
        status = 'completed'
        result = None
        try:
            result = await runner()
            return result
        except BaseException as exc:
            status = 'cancelled' if isinstance(
                exc, asyncio.CancelledError) else 'error'
            raise
        finally:
            end_ts = now_iso()
            duration_s = monotonic() - start_time
            usage = summarize_usage(result if isinstance(result, list) else [])
            record = build_timing_record(
                event='agent_tool',
                agent_tag=runtime_agent_tag,
                agent_type=runtime_agent_type,
                started_at=start_ts,
                ended_at=end_ts,
                duration_s=duration_s,
                status=status,
                usage=usage,
                extra={
                    'tool_name': spec.tool_name,
                    'server_name': spec.server_name,
                    'caller_tag': getattr(self.config, 'tag', None),
                },
            )
            try:
                await append_stats(get_stats_path(self.config), record)
            except Exception as exc:
                logger.warning(
                    f'Failed to write agent tool stats for {spec.tool_name}: {exc}'
                )

    def _build_payload(self, tool_args: dict, spec: _AgentToolSpec):
        if spec.input_mode == 'messages':
            field = spec.request_field or 'messages'
            raw_messages = tool_args.get(field)
            if not isinstance(raw_messages, list):
                raise ValueError(
                    f'Agent tool "{spec.tool_name}" expects "{field}" to be a list of messages.'
                )
            return [
                Message(
                    role=msg.get('role', 'user'),
                    content=msg.get('content', ''),
                    tool_calls=msg.get('tool_calls', []),
                    tool_call_id=msg.get('tool_call_id'),
                    name=msg.get('name'),
                    reasoning_content=msg.get('reasoning_content', ''),
                ) for msg in raw_messages  # TODO: Change role to user or not
            ]

        if spec.input_template:
            template_args = defaultdict(lambda: '', tool_args)
            try:
                return spec.input_template.format_map(template_args)
            except Exception as exc:
                logger.warning(
                    'Failed to render input template for tool %s: %s. Falling back to JSON payload.',
                    spec.tool_name, exc)

        field = spec.request_field or 'request'
        if field in tool_args and isinstance(tool_args[field], str):
            return tool_args[field]

        return json.dumps(tool_args, ensure_ascii=False, indent=2)

    def _format_output(self, messages: Any, spec: _AgentToolSpec) -> str:
        if not isinstance(messages, list):
            return self._truncate(str(messages), spec.max_output_chars)

        if spec.output_mode == 'history':
            serialized = [self._serialize_message(msg) for msg in messages]
            return self._truncate(
                json.dumps(serialized, ensure_ascii=False, indent=2),
                spec.max_output_chars)

        if spec.output_mode == 'raw_json':
            serialized = [msg.to_dict() for msg in messages]  # type: ignore
            return self._truncate(
                json.dumps(serialized, ensure_ascii=False),
                spec.max_output_chars)

        # Default: return final assistant message text
        for msg in reversed(messages):
            if getattr(msg, 'role', '') == 'assistant':
                return self._truncate(msg.content or '', spec.max_output_chars)

        return self._truncate(messages[-1].content or '',
                              spec.max_output_chars)

    def _serialize_message(self, message: Message) -> Dict[str, Any]:
        data = message.to_dict()
        if data.get('tool_calls'):
            for call in data['tool_calls']:
                if isinstance(call.get('arguments'), dict):
                    call['arguments'] = json.dumps(
                        call['arguments'], ensure_ascii=False)
        return data

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        if limit <= 0:
            return text
        if len(text) <= limit:
            return text
        return text[:limit] + '\n\n[AgentTool truncated output]'
