# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import json
from ms_agent.agent.loader import AgentLoader
from ms_agent.llm.utils import Message, Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger
from ms_agent.utils.stats import (append_stats, build_timing_record,
                                  get_stats_path, monotonic, now_iso,
                                  summarize_usage)
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


class AgentTool(ToolBase):
    """Expose existing ms-agent agents as callable tools."""

    DEFAULT_SERVER = 'agent_tools'

    def __init__(self, config: DictConfig, **kwargs):
        super().__init__(config)
        self._trust_remote_code = kwargs.get('trust_remote_code', True)
        self._enable_stats = False
        self._specs: Dict[str, _AgentToolSpec] = {}
        self._server_tools: Dict[str, List[Tool]] = {}
        self._load_specs()

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
        return None

    async def cleanup(self):
        return None

    async def get_tools(self) -> Dict[str, Any]:
        return self._server_tools

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        if tool_name not in self._specs:
            raise ValueError(f'Agent tool "{tool_name}" not registered.')
        spec = self._specs[tool_name]
        if spec.server_name != server_name:
            raise ValueError(
                f'Agent tool "{tool_name}" is not part of server "{server_name}".'
            )

        payload = self._build_payload(tool_args, spec)
        agent = self._build_agent(spec)
        messages = await self._run_agent(agent, payload, spec)
        return self._format_output(messages, spec)

    def _build_agent(self, spec: _AgentToolSpec):
        if spec.inline_config is not None:
            config_override = OmegaConf.create(spec.inline_config)
        else:
            config_override = None

        trust_remote_code = spec.trust_remote_code
        if trust_remote_code is None:
            trust_remote_code = self._trust_remote_code

        tag = f'{spec.tag_prefix}{uuid.uuid4().hex[:8]}'
        agent = AgentLoader.build(
            config_dir_or_id=spec.config_path,
            config=config_override,
            env=spec.env,
            tag=tag,
            trust_remote_code=trust_remote_code,
        )

        generation_cfg = getattr(agent.config, 'generation_config',
                                 DictConfig({}))
        # OmegaConf.update(
        #     generation_cfg,
        #     'stream',
        #     False,
        #     merge=True,
        # )
        agent.config.generation_config = generation_cfg
        return agent

    async def _run_agent(self, agent, payload, spec: _AgentToolSpec):
        if not self._enable_stats:
            result = await agent.run(payload)
            if hasattr(result, '__aiter__'):
                history = None
                async for chunk in result:
                    history = chunk
                result = history
            return result

        start_ts = now_iso()
        start_time = monotonic()
        status = 'completed'
        result = None
        try:
            result = await agent.run(payload)
            if hasattr(result, '__aiter__'):
                history = None
                async for chunk in result:
                    history = chunk
                result = history
            return result
        except Exception:
            status = 'error'
            raise
        finally:
            end_ts = now_iso()
            duration_s = monotonic() - start_time
            usage = summarize_usage(result if isinstance(result, list) else [])
            record = build_timing_record(
                event='agent_tool',
                agent_tag=getattr(agent, 'tag', None),
                agent_type=getattr(agent, 'AGENT_NAME', None),
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
