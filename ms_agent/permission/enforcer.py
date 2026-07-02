"""PermissionEnforcer: outer-layer user-intent permission control.

Checks blacklist/whitelist, session/persistent memory, and falls back to
the PermissionHandler for interactive user confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .config import PermissionConfig
from .handler import (
    AutoPermissionHandler,
    PermissionAction,
    PermissionHandler,
    PermissionResponse,
)
from .matcher import PermissionMatcher
from .memory import PermissionMemory
from .suggestions import generate_suggestions


@dataclass(frozen=True)
class PermissionDecision:
    action: Literal['allow', 'deny', 'ask']
    reason: str
    updated_args: dict[str, Any] | None = None


class PermissionEnforcer:
    """Outer-layer permission enforcement based on user intent and configuration."""

    def __init__(
        self,
        config: PermissionConfig,
        handler: PermissionHandler | None = None,
        memory: PermissionMemory | None = None,
    ) -> None:
        self._config = config
        self._handler = handler or AutoPermissionHandler()
        self._memory = memory or PermissionMemory()
        self._matcher = PermissionMatcher()

    async def check(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        force_decision: PermissionDecision | None = None,
    ) -> PermissionDecision:
        # 1. Blacklist → deny (not overridable in any mode)
        for pattern in self._config.blacklist:
            if self._matcher.match_with_content(pattern, tool_name, tool_args):
                return PermissionDecision(
                    action='deny',
                    reason=f'Denied by blacklist rule: {pattern}',
                )

        if force_decision and force_decision.action == 'ask':
            suggestions = generate_suggestions(tool_name, tool_args)
            response = await self._handler.ask(
                tool_name=tool_name,
                tool_args=tool_args,
                context=force_decision.reason or '',
                suggestions=suggestions,
            )
            return self._process_response(response, tool_name, tool_args)

        # 2. Auto / strict mode → allow (safety handled by SafetyGuard + ask_resolver)
        if self._config.mode in ('auto', 'strict'):
            return PermissionDecision(action='allow', reason=f'{self._config.mode.capitalize()} mode')

        # 3. Whitelist → allow
        for pattern in self._config.whitelist:
            if self._matcher.match_with_content(pattern, tool_name, tool_args):
                return PermissionDecision(
                    action='allow',
                    reason=f'Allowed by whitelist rule: {pattern}',
                )

        # 4. Memory (session + persistent) → allow
        if self._memory.matches(tool_name, tool_args):
            return PermissionDecision(
                action='allow',
                reason='Allowed by remembered permission',
            )

        # 5. Ask user via handler
        suggestions = generate_suggestions(tool_name, tool_args)
        response = await self._handler.ask(
            tool_name=tool_name,
            tool_args=tool_args,
            context='',
            suggestions=suggestions,
        )

        return self._process_response(response, tool_name, tool_args)

    def _process_response(
        self,
        response: PermissionResponse,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> PermissionDecision:
        if response.action == PermissionAction.ALLOW_ONCE:
            return PermissionDecision(action='allow', reason='User allowed once')

        if response.action == PermissionAction.ALLOW_SESSION:
            pattern = response.pattern or tool_name
            self._memory.add_session(pattern)
            return PermissionDecision(
                action='allow',
                reason=f'User allowed for session (pattern: {pattern})',
            )

        if response.action == PermissionAction.ALLOW_ALWAYS:
            pattern = response.pattern or tool_name
            self._memory.add(pattern, scope='project', source='user')
            return PermissionDecision(
                action='allow',
                reason=f'User allowed always (pattern: {pattern})',
            )

        if response.action == PermissionAction.MODIFY:
            return PermissionDecision(
                action='allow',
                reason='User modified args',
                updated_args=response.updated_args,
            )

        if response.action == PermissionAction.DENY:
            return PermissionDecision(
                action='deny',
                reason=response.feedback or 'User denied',
            )

        return PermissionDecision(action='deny', reason='Unknown action')
