"""Map ms-agent tool names to external ecosystem aliases."""

from __future__ import annotations

# ms-agent suffix -> external names
_TOOL_SUFFIX_MAP: dict[str, dict[str, str]] = {
    'shell_executor': {
        'claude': 'Bash',
        'cursor': 'Shell',
        'hermes': 'terminal',
    },
    'read_file': {
        'claude': 'Read',
        'cursor': 'Read',
        'hermes': 'read_file',
    },
    'write_file': {
        'claude': 'Write',
        'cursor': 'Write',
        'hermes': 'write_file',
    },
    'edit_file': {
        'claude': 'Edit',
        'cursor': 'Write',
        'hermes': 'patch',
    },
}


class ToolNameMapper:
    """Bidirectional tool name mapping for hook payloads and matchers."""

    TOOL_SPLITER = '---'

    def __init__(self, enabled_sources: frozenset[str] = frozenset({'native'})):
        self._enabled_sources = enabled_sources

    def to_external(self, tool_name: str, platform: str) -> str | None:
        if self.TOOL_SPLITER not in tool_name:
            return None
        suffix = tool_name.split(self.TOOL_SPLITER, 1)[1]
        mapping = _TOOL_SUFFIX_MAP.get(suffix, {})
        return mapping.get(platform)

    def enrich_payload(
        self,
        payload: dict,
        tool_name: str | None = None,
    ) -> dict:
        """Add external tool name aliases to stdin payload."""
        tn = tool_name or payload.get('tool_name', '')
        if not tn:
            return payload
        enriched = dict(payload)
        if 'claude' in self._enabled_sources or 'native' in self._enabled_sources:
            ext = self.to_external(tn, 'claude')
            if ext:
                enriched['tool_name_claude'] = ext
        if 'cursor' in self._enabled_sources:
            ext = self.to_external(tn, 'cursor')
            if ext:
                enriched['tool_name_cursor'] = ext
        if 'hermes' in self._enabled_sources:
            ext = self.to_external(tn, 'hermes')
            if ext:
                enriched['tool_name_hermes'] = ext
        args = enriched.get('tool_args')
        if args is not None:
            enriched.setdefault('tool_input', args)
        enriched.setdefault('hook_event_name', enriched.get('event', ''))
        return enriched

    def external_matcher_to_native(self, matcher: str, platform: str) -> str:
        """Convert external tool matcher to ms-agent format where possible."""
        if self.TOOL_SPLITER in matcher:
            return matcher
        reverse: dict[str, str] = {}
        for suffix, platforms in _TOOL_SUFFIX_MAP.items():
            name = platforms.get(platform)
            if name:
                reverse[name] = f'*{self.TOOL_SPLITER}{suffix}'
        for ext_name, native_pattern in reverse.items():
            if matcher == ext_name:
                return native_pattern
        # Shell/Bash/terminal wildcard
        if matcher in ('Bash', 'Shell', 'terminal'):
            return f'*{self.TOOL_SPLITER}shell_executor'
        return matcher
