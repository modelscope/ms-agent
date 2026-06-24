"""Hermes shell hook loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ms_agent.hooks.registry import HookRegistry, _parse_hook_handler, MatcherGroup
from ms_agent.hooks.tool_name_mapper import ToolNameMapper
from ms_agent.utils import get_logger

logger = get_logger()

_HERMES_EVENT_MAP = {
    'on_session_start': 'SessionStart',
    'pre_llm_call': 'UserPromptSubmit',
    'pre_tool_call': 'PreToolUse',
    'post_tool_call': 'PostToolUse',
    'on_session_end': 'Stop',
    'subagent_stop': 'SubagentStop',
    'pre_approval_request': 'PermissionRequest',
}


class HermesShellLoader:
    @staticmethod
    def load_file(
        path: Path | str,
        project_path: str,
        *,
        plugin_root: str | None = None,
        plugin_data_dir: str | None = None,
        user_config: dict[str, Any] | None = None,
        enabled_executors: frozenset[str] = frozenset({'command'}),
    ) -> HookRegistry:
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        hooks = data.get('hooks', {})
        return HermesShellLoader.parse_hooks(
            hooks,
            project_path,
            plugin_root=plugin_root,
            plugin_data_dir=plugin_data_dir,
            user_config=user_config,
            enabled_executors=enabled_executors,
        )

    @staticmethod
    def parse_hooks(
        hooks: dict[str, Any],
        project_path: str,
        *,
        plugin_root: str | None = None,
        plugin_data_dir: str | None = None,
        user_config: dict[str, Any] | None = None,
        enabled_executors: frozenset[str] = frozenset({'command'}),
    ) -> HookRegistry:
        if not hooks:
            return HookRegistry(_index={})

        mapper = ToolNameMapper(enabled_sources=frozenset({'hermes'}))
        index: dict[str, tuple[MatcherGroup, ...]] = {}

        for event_name, entries in hooks.items():
            canonical = _HERMES_EVENT_MAP.get(event_name)
            if not canonical or canonical not in HookRegistry.VALID_EVENTS:
                logger.warning('Skipping unknown Hermes hook event: %s', event_name)
                continue

            groups = []
            for entry in (entries or []):
                if isinstance(entry, str):
                    entry = {'command': entry}
                if not isinstance(entry, dict):
                    continue

                matcher = entry.get('matcher') or entry.get('tool')
                if matcher and canonical in HookRegistry.TOOL_EVENTS:
                    matcher = mapper.external_matcher_to_native(matcher, 'hermes')
                    matcher = _expand_vars(
                        matcher, project_path, plugin_root, plugin_data_dir,
                        user_config)

                cmd = entry.get('command') or entry.get('script')
                h = {
                    'type': 'command',
                    'command': _expand_vars(
                        str(cmd), project_path, plugin_root, plugin_data_dir,
                        user_config) if cmd else cmd,
                    'timeout': entry.get('timeout', 30),
                    'fail_closed': entry.get('fail_closed', False),
                }
                if h['type'] not in enabled_executors:
                    logger.warning(
                        'Hermes hook type %s not in enabled_executors %s, skipping',
                        h['type'],
                        sorted(enabled_executors),
                    )
                    continue
                parsed = _parse_hook_handler(h)
                if parsed:
                    groups.append(MatcherGroup(
                        matcher=matcher if canonical in HookRegistry.TOOL_EVENTS else None,
                        hooks=(parsed,),
                    ))
            if groups:
                index[canonical] = tuple(groups)

        return HookRegistry(_index=index)


def _expand_vars(
    value: str,
    project_path: str,
    plugin_root: str | None,
    plugin_data_dir: str | None,
    user_config: dict[str, Any] | None,
) -> str:
    value = value.replace('${MS_AGENT_PROJECT_DIR}', project_path)
    value = value.replace('${CLAUDE_PROJECT_DIR}', project_path)
    if plugin_root:
        value = value.replace('${MS_AGENT_PLUGIN_ROOT}', plugin_root)
        value = value.replace('${CLAUDE_PLUGIN_ROOT}', plugin_root)
    if plugin_data_dir:
        value = value.replace('${MS_AGENT_PLUGIN_DATA}', plugin_data_dir)
        value = value.replace('${CLAUDE_PLUGIN_DATA}', plugin_data_dir)
    for key, item in (user_config or {}).items():
        value = value.replace(f'${{user_config.{key}}}', str(item))
        value = value.replace(f'${{CLAUDE_PLUGIN_OPTION_{key.upper()}}}', str(item))
    return value
