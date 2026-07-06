"""Auto-generate permission pattern suggestions for allow_always actions."""

from __future__ import annotations

import shlex
from typing import Any

from .matcher import CONTENT_SEP, TOOL_SPLITER
from .wrapper_strip import strip_safe_wrappers


def generate_suggestions(tool_name: str, tool_args: dict[str, Any]) -> list[str]:
    """Generate suggested wildcard patterns based on tool name and arguments.

    Returns a list of patterns from most specific to most general.
    """
    suggestions: list[str] = []

    # Extract server name (everything before first TOOL_SPLITER)
    parts = tool_name.split(TOOL_SPLITER, 1)
    server = parts[0] if len(parts) > 1 else ''

    if tool_name.endswith(f'{TOOL_SPLITER}shell_executor'):
        command = tool_args.get('command', '')
        if command:
            first_cmd = _extract_first_command(command)
            if first_cmd:
                suggestions.append(f'{tool_name}{CONTENT_SEP}{first_cmd} *')
        suggestions.append(tool_name)
    elif server == 'file_system':
        suggestions.append(tool_name)
    elif server == 'web_search':
        suggestions.append(f'{server}{TOOL_SPLITER}*')
    else:
        suggestions.append(tool_name)
        if server:
            suggestions.append(f'{server}{TOOL_SPLITER}*')

    return suggestions


def _extract_first_command(command: str) -> str:
    """Extract the base command name, stripping safe wrappers (timeout, nice, …)."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    stripped = strip_safe_wrappers(tokens)
    return stripped[0] if stripped else ''
