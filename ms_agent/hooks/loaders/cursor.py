"""Cursor hooks.json loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ms_agent.hooks.registry import HookRegistry, _parse_hook_handler, MatcherGroup
from ms_agent.hooks.tool_name_mapper import ToolNameMapper
from ms_agent.utils import get_logger

logger = get_logger()

_CURSOR_EVENT_MAP = {
    'sessionStart': 'SessionStart',
    'beforeSubmitPrompt': 'UserPromptSubmit',
    'preToolUse': 'PreToolUse',
    'postToolUse': 'PostToolUse',
    'stop': 'Stop',
    'subagentStop': 'SubagentStop',
    'beforeShellExecution': 'PreToolUse',
    'afterFileEdit': 'PostToolUse',
}


class CursorHooksLoader:
    @staticmethod
    def load_file(
        path: Path | str,
        project_path: str,
        *,
        enabled_executors: frozenset[str] = frozenset({'command'}),
    ) -> HookRegistry:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        hooks = data.get('hooks', data)
        return CursorHooksLoader.parse_hooks(
            hooks, project_path, enabled_executors=enabled_executors)

    @staticmethod
    def parse_hooks(
        hooks: dict[str, Any],
        project_path: str,
        *,
        enabled_executors: frozenset[str] = frozenset({'command'}),
    ) -> HookRegistry:
        if not hooks:
            return HookRegistry(_index={})

        mapper = ToolNameMapper(enabled_sources=frozenset({'cursor'}))
        index: dict[str, tuple[MatcherGroup, ...]] = {}

        for event_name, entries in hooks.items():
            canonical = _CURSOR_EVENT_MAP.get(event_name)
            if not canonical or canonical not in HookRegistry.VALID_EVENTS:
                logger.warning('Skipping unknown Cursor hook event: %s', event_name)
                continue

            groups = []
            for entry in (entries or []):
                matcher = entry.get('matcher')
                if event_name == 'beforeShellExecution':
                    matcher = matcher or f'*{ToolNameMapper.TOOL_SPLITER}shell_executor'
                elif event_name == 'afterFileEdit':
                    matcher = matcher or f'*{ToolNameMapper.TOOL_SPLITER}write_file'
                elif matcher and canonical in HookRegistry.TOOL_EVENTS:
                    matcher = mapper.external_matcher_to_native(matcher, 'cursor')

                t = entry.get('type', 'command') or 'command'
                if t not in enabled_executors:
                    logger.warning(
                        'Cursor hook type %s not in enabled_executors %s, skipping',
                        t,
                        sorted(enabled_executors),
                    )
                    continue

                h = {
                    'type': t,
                    'command': entry.get('command'),
                    'timeout': entry.get('timeout', 30),
                    'failClosed': entry.get('failClosed', False),
                }
                parsed = _parse_hook_handler(h)
                if parsed:
                    groups.append(MatcherGroup(
                        matcher=matcher if canonical in HookRegistry.TOOL_EVENTS else None,
                        hooks=(parsed,),
                    ))
            if groups:
                existing = index.get(canonical, ())
                index[canonical] = existing + tuple(groups)

        return HookRegistry(_index=index)
