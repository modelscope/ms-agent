"""PermissionEnforcer: outer-layer user-intent permission control.

Checks blacklist/whitelist, session/persistent memory, and falls back to
the PermissionHandler for interactive user confirmation.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Literal

from .config import PermissionConfig
from .handler import (AutoPermissionHandler, PermissionAction,
                      PermissionHandler, PermissionResponse)
from .matcher import CONTENT_SEP, PermissionMatcher
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
        # Parallel tool calls (asyncio.gather in ToolManager.parallel_call_tool)
        # reach the handler concurrently. Whether that is safe is the HANDLER's
        # property, not a blanket rule: a terminal-bound one (CLI prompt / TUI
        # menu) deadlocks with N prompts fighting over one stdin, while a
        # request_id-keyed UI wants them all at once. Handlers opt in with
        # ``supports_concurrent_asks``; everyone else is serialized with a lock
        # created lazily per running loop (the per-turn TUI uses a fresh loop
        # each turn, so a single init-time Lock would bind to the wrong one).
        self._ask_lock: asyncio.Lock | None = None
        self._ask_lock_loop = None

    def _ask_lock_for_loop(self) -> 'asyncio.Lock':
        loop = asyncio.get_running_loop()
        if self._ask_lock is None or self._ask_lock_loop is not loop:
            self._ask_lock = asyncio.Lock()
            self._ask_lock_loop = loop
        return self._ask_lock

    async def _ask_user(self,
                        *,
                        forced: bool = False,
                        **kwargs) -> PermissionResponse | None:
        """Put one ask in front of the user, serialized unless the handler
        declares it can service several at once.

        Returns ``None`` when a queued ask turned out to be unnecessary: while
        it waited for the lock, an earlier ask in the same round was answered
        with allow_session / allow_always covering this call too, so prompting
        again would ask the user something they just answered. ``forced`` asks
        (a SafetyGuard confirmation) skip that shortcut — memory must never
        bypass a safety ask.
        """
        # ``call_id`` is a newer, optional kwarg (see check()). A handler that
        # predates it — or a lightweight test double — need not accept it; drop
        # it for such handlers so their fixed signature keeps working.
        if 'call_id' in kwargs and not self._handler_accepts('call_id'):
            kwargs.pop('call_id')
        if getattr(self._handler, 'supports_concurrent_asks', False):
            return await self._handler.ask(**kwargs)
        async with self._ask_lock_for_loop():
            if not forced and self._memory.matches(kwargs['tool_name'],
                                                   kwargs['tool_args']):
                return None
            return await self._handler.ask(**kwargs)

    def _can_ask_human(self) -> bool:
        """Whether a real person can actually answer a prompt right now.

        ``AutoPermissionHandler`` is the stand-in used headlessly and it always
        answers "allow", so treating it as an asker would turn every ask rule
        into a no-op.
        """
        return not isinstance(self._handler, AutoPermissionHandler)

    def _handler_accepts(self, param: str) -> bool:
        try:
            sig = inspect.signature(self._handler.ask)
        except (TypeError, ValueError):
            return True  # can't introspect — assume it takes it, don't strip
        params = sig.parameters.values()
        return (any(p.name == param for p in params)
                or any(p.kind == inspect.Parameter.VAR_KEYWORD
                       for p in params))

    async def check(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        force_decision: PermissionDecision | None = None,
        call_id: str = '',
    ) -> PermissionDecision:
        # ``call_id`` (the tool_call this ask is gating) is threaded to the
        # handler so a UI can record/correlate the decision against the exact
        # call — important when a round fires several identical tool calls in
        # parallel. Empty when the LLM adapter didn't assign an id yet;
        # handlers must tolerate that.
        # 1. Blacklist → deny (not overridable in any mode)
        for pattern in self._config.blacklist:
            if self._matcher.match_with_content(pattern, tool_name, tool_args):
                return PermissionDecision(
                    action='deny',
                    reason=f'Denied by blacklist rule: {pattern}',
                )

        if force_decision and force_decision.action == 'ask':
            suggestions = generate_suggestions(tool_name, tool_args)
            response = await self._ask_user(
                forced=True,
                tool_name=tool_name,
                tool_args=tool_args,
                context=force_decision.reason or '',
                suggestions=suggestions,
                call_id=call_id,
            )
            return self._process_response(response, tool_name, tool_args)

        # 1b. Ask rules → confirm, in EVERY mode. Until now this config existed
        # but only the hook path consulted it, so an ask rule was silently
        # inert on the ordinary route. It outranks the mode and the whitelist —
        # that is the whole point of "ask even under full access" — but not the
        # user's own remembered answer below, so consenting once still sticks.
        ask_rule = next(
            (p for p in self._config.ask_rules
             if self._matcher.match_with_content(p, tool_name, tool_args)),
            None,
        )
        if ask_rule and not self._can_ask_human():
            # Headless (AutoPermissionHandler allows everything): there is
            # nobody to confirm, and silently running the thing an ask rule was
            # written to gate would be worse than refusing.
            return PermissionDecision(
                action='deny',
                reason=(f'Ask rule matched: {ask_rule}; no interactive '
                        'handler is attached to confirm it'),
            )

        # 2. Auto / strict mode → allow (safety handled by SafetyGuard + ask_resolver)
        if self._config.mode in ('auto', 'strict') and not ask_rule:
            return PermissionDecision(
                action='allow',
                reason=f'{self._config.mode.capitalize()} mode')

        # 3. Whitelist → allow
        if not ask_rule:
            for pattern in self._config.whitelist:
                if self._matcher.match_with_content(pattern, tool_name,
                                                    tool_args):
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

        # 5. Ask user via handler (serialized unless it opts into concurrency)
        suggestions = generate_suggestions(tool_name, tool_args)
        response = await self._ask_user(
            tool_name=tool_name,
            tool_args=tool_args,
            context='',
            suggestions=suggestions,
            call_id=call_id,
        )

        return self._process_response(response, tool_name, tool_args)

    def _remember_pattern(self, response: PermissionResponse, tool_name: str,
                          tool_args: dict[str, Any]) -> str:
        """What to remember when the caller named no pattern of its own.

        The bare tool name means "allow this TOOL" — for the shell that is
        every future command, so approving ``ls -la`` once silently handed over
        unrestricted shell access. Prefer instead the most specific generated
        suggestion that is no broader than the tool itself (``<tool>:ls *``);
        a suggestion that WIDENS the scope (``<server>---*``) is not a fallback
        anyone asked for.
        """
        if response.pattern:
            return response.pattern
        for s in generate_suggestions(tool_name, tool_args):
            if s == tool_name or s.startswith(f'{tool_name}{CONTENT_SEP}'):
                return s
        return tool_name

    def _process_response(
        self,
        response: PermissionResponse | None,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> PermissionDecision:
        if response is None:
            # The ask was skipped: memory started covering this call while it
            # was queued behind another one (see _ask_user).
            return PermissionDecision(
                action='allow',
                reason='Allowed by remembered permission',
            )

        if response.action == PermissionAction.ALLOW_ONCE:
            return PermissionDecision(
                action='allow', reason='User allowed once')

        if response.action == PermissionAction.ALLOW_SESSION:
            pattern = self._remember_pattern(response, tool_name, tool_args)
            self._memory.add_session(pattern)
            return PermissionDecision(
                action='allow',
                reason=f'User allowed for session (pattern: {pattern})',
            )

        if response.action == PermissionAction.ALLOW_ALWAYS:
            pattern = self._remember_pattern(response, tool_name, tool_args)
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
