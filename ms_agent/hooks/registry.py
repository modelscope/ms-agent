"""HookRegistry — canonical event index and config parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from ms_agent.utils import get_logger
from ms_agent.utils.pattern_matcher import match_pattern

logger = get_logger()


@dataclass(frozen=True)
class HookHandlerConfig:
    type: str = 'command'
    timeout: float = 30.0
    fail_closed: bool = False
    command: str | None = None
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    allowed_env_vars: tuple[str, ...] = ()
    prompt: str | None = None
    model: str | None = None
    max_turns: int = 20


@dataclass(frozen=True)
class MatcherGroup:
    matcher: str | None
    hooks: tuple[HookHandlerConfig, ...]


def _filter_handlers_by_executor(
    hooks_raw: list[dict[str, Any]],
    enabled_executors: frozenset[str],
    *,
    source: str = 'config',
) -> tuple[HookHandlerConfig, ...]:
    handlers: list[HookHandlerConfig] = []
    for h in hooks_raw:
        t = h.get('type', 'command') or 'command'
        if t not in enabled_executors:
            logger.warning(
                'Hook type %s not in enabled_executors %s, skipping (%s)',
                t,
                sorted(enabled_executors),
                source,
            )
            continue
        parsed = _parse_hook_handler(h)
        if parsed is not None:
            handlers.append(parsed)
    return tuple(handlers)


def _parse_hook_handler(h: dict[str, Any]) -> HookHandlerConfig | None:
    t = h.get('type', 'command')
    timeout = float(h.get('timeout', 30.0))
    fail_closed = bool(h.get('failClosed', h.get('fail_closed', False)))
    if t == 'command':
        if not h.get('command'):
            return None
        return HookHandlerConfig(
            type='command',
            command=h['command'],
            timeout=timeout,
            fail_closed=fail_closed,
        )
    if t == 'http':
        if not h.get('url'):
            return None
        return HookHandlerConfig(
            type='http',
            url=h['url'],
            headers=dict(h.get('headers') or {}),
            allowed_env_vars=tuple(
                h.get('allowedEnvVars', h.get('allowed_env_vars', []))),
            timeout=timeout,
            fail_closed=fail_closed,
        )
    if t in ('prompt', 'agent'):
        if not h.get('prompt'):
            return None
        return HookHandlerConfig(
            type=t,
            prompt=h['prompt'],
            model=h.get('model'),
            max_turns=int(h.get('maxTurns', h.get('max_turns', 20))),
            timeout=timeout,
            fail_closed=fail_closed,
        )
    logger.warning('Unknown hook handler type: %s', t)
    return None


@dataclass(frozen=True)
class HookRegistry:
    _index: dict[str, tuple[MatcherGroup, ...]]

    VALID_EVENTS: ClassVar[frozenset[str]] = frozenset({
        'SessionStart', 'PreToolUse', 'PostToolUse',
        'UserPromptSubmit', 'Stop', 'PermissionRequest',
        'SubagentStop',
    })

    TOOL_EVENTS: ClassVar[frozenset[str]] = frozenset({
        'PreToolUse', 'PostToolUse', 'PermissionRequest',
    })

    @classmethod
    def from_dict(
        cls,
        d: dict[str, Any],
        *,
        enabled_executors: frozenset[str] = frozenset({'command'}),
        source: str = 'config',
    ) -> HookRegistry:
        if not d:
            return cls(_index={})

        index: dict[str, tuple[MatcherGroup, ...]] = {}
        for event_type, groups_raw in d.items():
            if event_type in (
                    'enabled_sources', 'enabled_executors', 'default_model',
                    'fail_closed', 'allowed_http_hook_urls',
                    'http_hook_allowed_env_vars'):
                continue
            if event_type not in cls.VALID_EVENTS:
                logger.warning('Unknown hook event type: %s', event_type)
                continue
            groups = []
            for g in (groups_raw or []):
                matcher = g.get('matcher') if event_type in cls.TOOL_EVENTS else None
                hooks_raw = g.get('hooks', [])
                handlers = _filter_handlers_by_executor(
                    hooks_raw,
                    enabled_executors,
                    source=source,
                )
                if handlers:
                    groups.append(MatcherGroup(matcher=matcher, hooks=handlers))
            if groups:
                index[event_type] = tuple(groups)
        return cls(_index=index)

    def merge(self, other: HookRegistry) -> HookRegistry:
        merged: dict[str, tuple[MatcherGroup, ...]] = {}
        all_events = set(self._index) | set(other._index)
        for event in all_events:
            self_groups = self._index.get(event, ())
            other_groups = other._index.get(event, ())
            merged[event] = self_groups + other_groups
        return HookRegistry(_index=merged)

    def get_handlers(
        self,
        event_type: str,
        tool_name: str | None = None,
    ) -> list[HookHandlerConfig]:
        groups = self._index.get(event_type, [])
        result: list[HookHandlerConfig] = []
        for group in groups:
            if event_type not in self.TOOL_EVENTS:
                result.extend(group.hooks)
            elif group.matcher is None:
                result.extend(group.hooks)
            elif tool_name is not None and match_pattern(group.matcher, tool_name):
                result.extend(group.hooks)
        return result

    @property
    def is_empty(self) -> bool:
        return not self._index
