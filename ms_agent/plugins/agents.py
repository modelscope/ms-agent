"""Plugin agent registry and delegate for agents/*.md subagent templates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf

from ms_agent.plugins.types import AgentDef
from ms_agent.skill.schema import SkillSchemaParser

_FRONTMATTER_RE = re.compile(r'^---\s*\n.*?\n---\s*\n', re.DOTALL)

# Claude Code tool names -> ms-agent config.tools top-level keys to keep.
_CLAUDE_TOOL_TO_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    'Read': ('file_system',),
    'Write': ('file_system',),
    'Edit': ('file_system',),
    'MultiEdit': ('file_system',),
    'Bash': ('code_executor',),
    'Grep': ('file_system', 'localsearch', 'web_search'),
    'Glob': ('file_system',),
    'Skill': (),  # skills are injected separately
    'TodoWrite': ('todo_list',),
    'AskUserQuestion': (),  # no dedicated tool yet
    'Task': ('agent_tools',),
}

_FORBIDDEN_AGENT_FRONTMATTER_KEYS = frozenset({
    'hooks',
    'mcpServers',
    'permissionMode',
})

_CLAUDE_BUILTIN_SUBAGENT_TYPES = frozenset({
    'general-purpose',
    'explore',
    'shell',
    'browser',
    'planner',
    'architect',
})


@dataclass(frozen=True)
class RegisteredPluginAgent:
    defn: AgentDef
    namespaced_name: str


class PluginAgentRegistry:
    """In-memory registry of plugin-defined subagent templates."""

    def __init__(self) -> None:
        self._by_namespaced: dict[str, RegisteredPluginAgent] = {}
        self._by_short: dict[str, RegisteredPluginAgent] = {}

    def rebuild(self, agent_defs: list[AgentDef]) -> None:
        self._by_namespaced.clear()
        self._by_short.clear()
        short_claimed: set[str] = set()
        for defn in sorted(agent_defs, key=lambda item: (item.plugin_id, item.name)):
            namespaced = f'{defn.plugin_id}:{defn.name}'
            entry = RegisteredPluginAgent(defn=defn, namespaced_name=namespaced)
            self._by_namespaced[namespaced] = entry
            if defn.name not in short_claimed:
                self._by_short[defn.name] = entry
                short_claimed.add(defn.name)

    def remove_plugin(self, plugin_id: str) -> None:
        for key in [
            key for key, entry in self._by_namespaced.items()
            if entry.defn.plugin_id == plugin_id
        ]:
            entry = self._by_namespaced.pop(key)
            short = self._by_short.get(entry.defn.name)
            if short is not None and short.namespaced_name == entry.namespaced_name:
                self._by_short.pop(entry.defn.name, None)
        for name, entry in list(self._by_short.items()):
            if entry.defn.plugin_id == plugin_id:
                self._by_short.pop(name, None)

    def has_agents(self) -> bool:
        return bool(self._by_namespaced)

    def list_all(self) -> list[dict[str, Any]]:
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        for entry in self._by_namespaced.values():
            if entry.namespaced_name in seen:
                continue
            seen.add(entry.namespaced_name)
            defn = entry.defn
            items.append({
                'plugin_id': defn.plugin_id,
                'name': defn.name,
                'namespaced_name': entry.namespaced_name,
                'description': defn.description,
                'model': defn.model,
                'tools': list(defn.tools),
                'skills': list(defn.skills),
                'path': defn.path,
            })
        return sorted(items, key=lambda item: item['namespaced_name'])

    def resolve(self, name: str | None) -> RegisteredPluginAgent | None:
        if not name:
            return None
        if name in self._by_namespaced:
            return self._by_namespaced[name]
        if name in self._by_short:
            return self._by_short[name]
        if ':' in name:
            plugin_id, short = name.split(':', 1)
            namespaced = f'{plugin_id}:{short}'
            return self._by_namespaced.get(namespaced)
        return None


class AgentDelegate:
    """Build runnable sub-agent specs from plugin agent markdown templates."""

    @staticmethod
    def read_agent_markdown(path: str | Path) -> tuple[dict[str, Any], str]:
        content = Path(path).read_text(encoding='utf-8')
        frontmatter = SkillSchemaParser.parse_yaml_frontmatter(content) or {}
        body = _FRONTMATTER_RE.sub('', content, count=1).strip()
        return frontmatter, body

    @staticmethod
    def validate_frontmatter(frontmatter: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        for key in _FORBIDDEN_AGENT_FRONTMATTER_KEYS:
            if key in frontmatter:
                warnings.append(
                    f'Plugin agents must not declare {key!r} in frontmatter')
        return warnings

    @staticmethod
    def build_inline_config(
        defn: AgentDef,
        parent_config: Any,
    ) -> dict[str, Any]:
        frontmatter, body = AgentDelegate.read_agent_markdown(defn.path)
        warnings = AgentDelegate.validate_frontmatter(frontmatter)
        if warnings:
            raise ValueError(
                f'Invalid plugin agent {defn.plugin_id}:{defn.name}: '
                + '; '.join(warnings))

        inline: dict[str, Any] = {
            'prompt': {'system': body},
            'ms_agent_subagent': True,
            'plugin_agent': {
                'plugin_id': defn.plugin_id,
                'name': defn.name,
                'path': defn.path,
            },
        }
        if hasattr(parent_config, 'local_dir') and parent_config.local_dir:
            inline['local_dir'] = str(parent_config.local_dir)
        model = defn.model or frontmatter.get('model')
        if model and str(model).lower() != 'inherit':
            parent_llm = {}
            if hasattr(parent_config, 'llm') and parent_config.llm is not None:
                parent_llm = OmegaConf.to_container(parent_config.llm, resolve=True) or {}
            inline['llm'] = {**parent_llm, 'model': str(model)}
        if defn.skills:
            inline['skills'] = {
                'whitelist': list(defn.skills),
            }
        return inline

    @staticmethod
    def compute_disallowed_tools(
        defn: AgentDef,
        parent_config: Any,
    ) -> list[str] | None:
        if defn.disallowed_tools:
            return list(defn.disallowed_tools)
        if not defn.tools:
            return None
        if not hasattr(parent_config, 'tools') or parent_config.tools is None:
            return None
        tools_dict = OmegaConf.to_container(parent_config.tools, resolve=True) or {}
        if not isinstance(tools_dict, dict):
            return None

        keep: set[str] = set()
        for claude_name in defn.tools:
            keep.update(_CLAUDE_TOOL_TO_CONFIG_KEYS.get(claude_name, ()))

        plugin_only_keys = {'agent_tools', 'split_task', 'task_control'}
        disallowed = [
            key for key in tools_dict
            if key not in keep and key not in plugin_only_keys
        ]
        return disallowed or None

    @staticmethod
    def to_agent_tool_spec(
        entry: RegisteredPluginAgent,
        parent_config: Any,
        *,
        trust_remote_code: bool = True,
    ):
        from ms_agent.tools.agent_tool import _AgentToolSpec

        defn = entry.defn
        description = (
            defn.description
            or f'Plugin subagent {entry.namespaced_name} from {defn.plugin_id}'
        )
        inline_config = AgentDelegate.build_inline_config(defn, parent_config)
        disallowed_tools = AgentDelegate.compute_disallowed_tools(defn, parent_config)
        return _AgentToolSpec(
            tool_name=defn.name,
            description=description,
            parameters={
                'type': 'object',
                'properties': {
                    'prompt': {
                        'type': 'string',
                        'description': (
                            f'Task prompt for plugin subagent {entry.namespaced_name}.'
                        ),
                    },
                    'request': {
                        'type': 'string',
                        'description': 'Alias of prompt for AgentTool compatibility.',
                    },
                    'description': {
                        'type': 'string',
                        'description': 'Short summary of the delegated task.',
                    },
                },
                'required': [],
                'additionalProperties': True,
            },
            config_path=None,
            inline_config=inline_config,
            server_name=f'plugin:{defn.plugin_id}',
            tag_prefix=f'{defn.plugin_id}-{defn.name}-',
            input_mode='text',
            request_field='prompt',
            input_template=None,
            output_mode='final_message',
            max_output_chars=100000,
            trust_remote_code=trust_remote_code,
            env=None,
            run_in_thread=True,
            run_in_process=True,
            dynamic=False,
            disallowed_tools=disallowed_tools,
        )

    @staticmethod
    def build_task_tool_spec(
        registry: PluginAgentRegistry,
        *,
        trust_remote_code: bool = True,
    ):
        from ms_agent.tools.agent_tool import _AgentToolSpec

        available = [item['namespaced_name'] for item in registry.list_all()]
        return _AgentToolSpec(
            tool_name='Task',
            description=(
                'Launch a plugin-defined subagent. Provide `agent` (for example '
                f'{available[0] if available else "hookify:conversation-analyzer"}) '
                'and `prompt`.'
            ),
            parameters={
                'type': 'object',
                'properties': {
                    'agent': {
                        'type': 'string',
                        'description': (
                            'Plugin subagent name, e.g. conversation-analyzer or '
                            'hookify:conversation-analyzer.'
                        ),
                    },
                    'subagent_type': {
                        'type': 'string',
                        'description': 'Alias of agent when it matches a plugin subagent.',
                    },
                    'prompt': {
                        'type': 'string',
                        'description': 'Prompt for the delegated subagent.',
                    },
                    'description': {
                        'type': 'string',
                        'description': 'Short summary of the delegated task.',
                    },
                },
                'required': ['prompt'],
                'additionalProperties': True,
            },
            config_path=None,
            inline_config=None,
            server_name='plugin_agents',
            tag_prefix='plugin-task-',
            input_mode='text',
            request_field='prompt',
            input_template=None,
            output_mode='final_message',
            max_output_chars=100000,
            trust_remote_code=trust_remote_code,
            env=None,
            run_in_thread=True,
            run_in_process=True,
            dynamic=True,
            disallowed_tools=None,
        )

    @staticmethod
    def resolve_task_agent_name(tool_args: dict[str, Any]) -> str | None:
        for key in ('agent', 'subagent_type', 'subagent', 'name'):
            value = tool_args.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def resolve_task_entry(
        registry: PluginAgentRegistry,
        tool_args: dict[str, Any],
    ) -> RegisteredPluginAgent | None:
        """Resolve a plugin subagent from Task tool arguments."""
        agent_name = AgentDelegate.resolve_task_agent_name(tool_args)
        entry = registry.resolve(agent_name) if agent_name else None
        if entry is not None:
            return entry
        if agent_name:
            for item in registry.list_all():
                namespaced = item['namespaced_name']
                if agent_name in {namespaced, item['name'], namespaced.split(':', 1)[-1]}:
                    resolved = registry.resolve(namespaced)
                    if resolved is not None:
                        return resolved
        items = registry.list_all()
        if len(items) == 1:
            only = registry.resolve(items[0]['namespaced_name'])
            if only is not None:
                return only
        if (
            agent_name in _CLAUDE_BUILTIN_SUBAGENT_TYPES
            and len(items) == 1
        ):
            return registry.resolve(items[0]['namespaced_name'])
        return None
