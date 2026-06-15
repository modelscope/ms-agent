"""Shared wildcard matching for permission rules.

Rule format: ``server---tool`` or ``server---tool:content_pattern``
Supports ``*`` / ``?`` wildcards via fnmatch, ``|`` to separate alternatives.
"""

from __future__ import annotations

from typing import Any

from ms_agent.utils.pattern_matcher import match_pattern


TOOL_SPLITER = '---'
CONTENT_SEP = ':'


def _extract_content(tool_name: str, tool_args: dict[str, Any]) -> str | None:
    """Extract the primary content string from tool args for content-pattern matching."""
    if tool_name.endswith(f'{TOOL_SPLITER}shell_executor'):
        return tool_args.get('command')
    if tool_name.endswith(f'{TOOL_SPLITER}write_file'):
        return tool_args.get('path')
    if tool_name.endswith(f'{TOOL_SPLITER}read_file'):
        return tool_args.get('path')
    if tool_name.endswith(f'{TOOL_SPLITER}edit_file'):
        return tool_args.get('path')
    if tool_name.endswith(f'{TOOL_SPLITER}grep'):
        return tool_args.get('pattern')
    if tool_name.endswith(f'{TOOL_SPLITER}glob'):
        return tool_args.get('pattern')
    for key in ('path', 'command', 'query', 'url', 'pattern'):
        if key in tool_args:
            return tool_args[key]
    return None


class PermissionMatcher:
    """Wildcard matcher for permission rules, shared by both SafetyGuard and PermissionEnforcer."""

    def match(self, pattern: str, tool_call: str) -> bool:
        """Match a tool call string against a pattern using fnmatch.

        Supports ``|`` separated alternatives: ``read_file|write_file``.
        """
        return match_pattern(pattern, tool_call)

    def match_with_content(
        self,
        pattern: str,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> bool:
        """Match with optional content pattern after ``:``.

        Examples::

            "file_system---read_file"               → matches tool name only
            "code_executor---shell_executor:pip *"   → matches tool name + command content
            "file_system---*"                        → wildcard on tool name
        """
        if CONTENT_SEP in pattern:
            tool_pattern, content_pattern = pattern.split(CONTENT_SEP, 1)
        else:
            tool_pattern = pattern
            content_pattern = None

        if not self.match(tool_pattern, tool_name):
            return False

        if content_pattern is None:
            return True

        content = _extract_content(tool_name, tool_args)
        if content is None:
            return False

        return self.match(content_pattern, content)
