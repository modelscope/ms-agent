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
    def load_file(path: Path | str, project_path: str) -> HookRegistry:
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        hooks = data.get('hooks', {})
        return HermesShellLoader.parse_hooks(hooks, project_path)

    @staticmethod
    def parse_hooks(hooks: dict[str, Any], project_path: str) -> HookRegistry:
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

                cmd = entry.get('command') or entry.get('script')
                h = {
                    'type': 'command',
                    'command': cmd,
                    'timeout': entry.get('timeout', 30),
                    'fail_closed': entry.get('fail_closed', False),
                }
                parsed = _parse_hook_handler(h)
                if parsed:
                    groups.append(MatcherGroup(
                        matcher=matcher if canonical in HookRegistry.TOOL_EVENTS else None,
                        hooks=(parsed,),
                    ))
            if groups:
                index[canonical] = tuple(groups)

        return HookRegistry(_index=index)
