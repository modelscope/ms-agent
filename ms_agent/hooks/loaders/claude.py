"""Claude Code settings.json hook loader."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ms_agent.hooks.registry import HookRegistry, _parse_hook_handler, MatcherGroup
from ms_agent.hooks.tool_name_mapper import ToolNameMapper
from ms_agent.utils import get_logger

logger = get_logger()

_CLAUDE_EVENT_MAP = {
    'SessionStart': 'SessionStart',
    'UserPromptSubmit': 'UserPromptSubmit',
    'PreToolUse': 'PreToolUse',
    'PostToolUse': 'PostToolUse',
    'Stop': 'Stop',
    'SubagentStop': 'SubagentStop',
    'PermissionRequest': 'PermissionRequest',
}


class ClaudeSettingsLoader:
    @staticmethod
    def load_file(
        path: Path | str,
        project_path: str,
        *,
        plugin_root: str | None = None,
        enabled_executors: frozenset[str] = frozenset({'command'}),
    ) -> HookRegistry:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        hooks = data.get('hooks', {})
        return ClaudeSettingsLoader.parse_hooks(
            hooks,
            project_path,
            plugin_root=plugin_root,
            enabled_executors=enabled_executors,
        )

    @staticmethod
    def parse_hooks_file(
        path: Path | str,
        *,
        plugin_root: str | None = None,
        project_path: str = '',
        enabled_executors: frozenset[str] = frozenset({'command'}),
    ) -> HookRegistry:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        hooks = data.get('hooks', data)
        return ClaudeSettingsLoader.parse_hooks(
            hooks,
            project_path,
            plugin_root=plugin_root,
            enabled_executors=enabled_executors,
        )

    @staticmethod
    def parse_hooks(
        hooks: dict[str, Any],
        project_path: str,
        *,
        plugin_root: str | None = None,
        enabled_executors: frozenset[str] = frozenset({'command'}),
    ) -> HookRegistry:
        if not hooks:
            return HookRegistry(_index={})

        mapper = ToolNameMapper(enabled_sources=frozenset({'claude'}))
        index: dict[str, tuple[MatcherGroup, ...]] = {}

        for event_name, groups_raw in hooks.items():
            canonical = _CLAUDE_EVENT_MAP.get(event_name)
            if not canonical or canonical not in HookRegistry.VALID_EVENTS:
                logger.warning('Skipping unknown Claude hook event: %s', event_name)
                continue

            groups = []
            for g in (groups_raw or []):
                matcher = g.get('matcher')
                if matcher and canonical in HookRegistry.TOOL_EVENTS:
                    matcher = mapper.external_matcher_to_native(matcher, 'claude')
                    matcher = _expand_path_vars(matcher, project_path, plugin_root)

                hooks_raw = g.get('hooks', [])
                handlers = []
                for h in hooks_raw:
                    h = _expand_command_vars(h, project_path, plugin_root)
                    t = h.get('type', 'command') or 'command'
                    if t not in enabled_executors:
                        logger.warning(
                            'Claude hook type %s not in enabled_executors %s, skipping',
                            t,
                            sorted(enabled_executors),
                        )
                        continue
                    parsed = _parse_hook_handler(h)
                    if parsed:
                        handlers.append(parsed)
                if handlers:
                    groups.append(MatcherGroup(
                        matcher=matcher if canonical in HookRegistry.TOOL_EVENTS else None,
                        hooks=tuple(handlers),
                    ))
            if groups:
                index[canonical] = tuple(groups)

        return HookRegistry(_index=index)


def _expand_path_vars(
    value: str,
    project_path: str,
    plugin_root: str | None,
) -> str:
    value = value.replace('${CLAUDE_PROJECT_DIR}', project_path)
    value = value.replace('${MS_AGENT_PROJECT_DIR}', project_path)
    if plugin_root:
        value = value.replace('${CLAUDE_PLUGIN_ROOT}', plugin_root)
        value = value.replace('${MS_AGENT_PLUGIN_ROOT}', plugin_root)
    return value


def _expand_command_vars(
    h: dict[str, Any],
    project_path: str,
    plugin_root: str | None,
) -> dict[str, Any]:
    out = dict(h)
    cmd = out.get('command')
    if isinstance(cmd, str):
        out['command'] = _expand_path_vars(cmd, project_path, plugin_root)
    return out
