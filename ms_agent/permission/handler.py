"""PermissionHandler protocol and implementations.

Three implementations:
  - AutoPermissionHandler: always allow (fallback).
  - CLIPermissionHandler: interactive terminal menu.
  - WebPermissionHandler: Future-based async with event emitter.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Protocol
from uuid import uuid4


class PermissionAction(str, Enum):
    ALLOW_ONCE = 'allow_once'
    ALLOW_SESSION = 'allow_session'
    ALLOW_ALWAYS = 'allow_always'
    DENY = 'deny'
    MODIFY = 'modify'


@dataclass(frozen=True)
class PermissionResponse:
    action: PermissionAction
    updated_args: dict[str, Any] | None = None
    pattern: str | None = None
    feedback: str | None = None


class PermissionHandler(Protocol):
    """Confirmation UI for a tool call the policy can't decide on its own.

    Optional duck-typed attribute ``supports_concurrent_asks`` (default
    ``False`` when absent) declares whether several asks may be in flight at
    once. It is False for anything bound to the one terminal — N prompts
    fighting over a single stdin/menu deadlock — so ``PermissionEnforcer``
    serializes those. A handler that keys pending asks by id and renders them
    independently (``WebPermissionHandler``) sets it True, so a round's
    parallel tool calls all surface for decision at the same time instead of
    one-at-a-time behind whoever the user answers first.
    """

    async def ask(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        context: str,
        suggestions: list[str] | None = None,
        call_id: str = '',
    ) -> PermissionResponse:
        ...


class AutoPermissionHandler:
    """Always allows — used as fallback or in auto mode."""

    # Never blocks on anything, so it has no reason to be serialized.
    supports_concurrent_asks = True

    async def ask(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        context: str,
        suggestions: list[str] | None = None,
        call_id: str = '',
    ) -> PermissionResponse:
        return PermissionResponse(action=PermissionAction.ALLOW_ONCE)


class CLIPermissionHandler:
    """Interactive CLI permission prompt."""

    async def ask(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        context: str,
        suggestions: list[str] | None = None,
        call_id: str = '',
    ) -> PermissionResponse:
        args_display = json.dumps(tool_args, ensure_ascii=False, indent=2)
        if len(args_display) > 500:
            args_display = args_display[:500] + '...'

        suggestion = suggestions[0] if suggestions else tool_name

        print(f'\n{"="*60}', file=sys.stderr)
        print(f' Permission Required', file=sys.stderr)
        print(f'{"="*60}', file=sys.stderr)
        print(f' Tool: {tool_name}', file=sys.stderr)
        print(f' Args: {args_display}', file=sys.stderr)
        if context:
            print(f' Context: {context}', file=sys.stderr)
        print(f'{"─"*60}', file=sys.stderr)
        print(f' [y] Allow this once', file=sys.stderr)
        print(f' [s] Allow for this session', file=sys.stderr)
        print(f' [a] Always allow (pattern: {suggestion})', file=sys.stderr)
        print(f' [e] Edit args then execute', file=sys.stderr)
        print(f' [n] Deny', file=sys.stderr)
        print(f'{"="*60}', file=sys.stderr)

        loop = asyncio.get_running_loop()
        choice = await loop.run_in_executor(
            None, lambda: input('Choice [y/s/a/e/n]: ').strip().lower())

        if choice == 's':
            return PermissionResponse(
                action=PermissionAction.ALLOW_SESSION,
                pattern=suggestion,
            )
        elif choice == 'a':
            edited = await loop.run_in_executor(
                None,
                lambda: input(f'Pattern [{suggestion}]: ').strip(),
            )
            final_pattern = edited if edited else suggestion
            return PermissionResponse(
                action=PermissionAction.ALLOW_ALWAYS,
                pattern=final_pattern,
            )
        elif choice == 'e':
            edited_raw = await loop.run_in_executor(
                None,
                lambda: input('New args (JSON): ').strip(),
            )
            try:
                new_args = json.loads(edited_raw)
            except json.JSONDecodeError:
                print('Invalid JSON, denying.', file=sys.stderr)
                return PermissionResponse(action=PermissionAction.DENY)
            return PermissionResponse(
                action=PermissionAction.MODIFY,
                updated_args=new_args,
            )
        elif choice == 'n':
            return PermissionResponse(action=PermissionAction.DENY)
        else:
            return PermissionResponse(action=PermissionAction.ALLOW_ONCE)


class EventEmitter(Protocol):
    """Protocol for pushing events to the frontend."""

    def emit(self, event: dict[str, Any]) -> None:
        ...


@dataclass
class _PendingAsk:
    """One card the user has not answered yet, and what it was about."""
    future: 'asyncio.Future[PermissionResponse]'
    tool_name: str
    tool_args: dict
    forced: bool = False


class WebPermissionHandler:
    """Async handler that suspends on a Future until the frontend responds."""

    # Pending asks are keyed by request_id and each renders as its own card, so
    # a round's parallel tool calls can all wait for a decision simultaneously.
    # Serializing them instead would show one card at a time while the untouched
    # siblings sat there looking like they were already running.
    supports_concurrent_asks = True

    def __init__(
        self,
        event_emitter: EventEmitter,
        timeout: float | None = None,
    ) -> None:
        """``timeout=None`` waits indefinitely for an answer.

        That is the right default for a handler whose whole purpose is to ask
        a person something: expiring the question answers it on their behalf,
        with the one answer they cannot undo. The host sets a bound where one
        makes sense — a full-access session, where the human may not be at the
        keyboard at all.
        """
        self._pending: dict[str, _PendingAsk] = {}
        self._event_emitter = event_emitter
        self._timeout = timeout

    async def ask(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        context: str,
        suggestions: list[str] | None = None,
        call_id: str = '',
        forced: bool = False,
    ) -> PermissionResponse:
        request_id = uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[PermissionResponse] = loop.create_future()
        # What was asked is kept beside the future so an answer to ONE card can
        # be applied to the others it covers (see resolve_matching).
        self._pending[request_id] = _PendingAsk(
            future=future,
            tool_name=tool_name,
            tool_args=dict(tool_args or {}),
            forced=forced,
        )

        self._event_emitter.emit({
            'type':
            'permission_request',
            'request_id':
            request_id,
            'call_id':
            call_id,
            'tool_name':
            tool_name,
            'tool_args':
            tool_args,
            'context':
            context,
            'suggestions':
            suggestions or [],
            'options': [a.value for a in PermissionAction],
        })

        try:
            if self._timeout is None:
                return await future
            return await asyncio.wait_for(future, timeout=self._timeout)
        except asyncio.TimeoutError:
            # Said plainly, and said to the MODEL: a timeout is not a person
            # declining. Without the distinction the agent reads an ordinary
            # refusal, tries a variation, and waits out the whole timeout
            # again — one unattended prompt costing several times what the
            # limit says it should.
            return PermissionResponse(
                action=PermissionAction.DENY,
                feedback=(
                    f'No response within {self._timeout:.0f}s, so this call '
                    'was not run. This is a TIMEOUT, not a refusal by the '
                    'user — nobody saw the request. Do not re-request the '
                    'same approval; finish what you can without it and say '
                    'plainly what is left waiting on approval.'),
            )
        finally:
            self._pending.pop(request_id, None)

    def awaiting_request_ids(self) -> set:
        """Every request still open for an answer.

        A host replaying a reconnected turn needs this to tell a card that is
        still live from one that was already decided.
        """
        return {
            request_id
            for request_id, pending in self._pending.items()
            if not pending.future.done()
        }

    def is_awaiting(self, request_id: str) -> bool:
        """Whether this request is still open for an answer.

        Public because a host has to ask before routing a click, and reaching
        into ``_pending`` to ask makes the host's code depend on how pending
        asks happen to be stored — which is how adding a field to that record
        turned every approval click into a 500.
        """
        pending = self._pending.get(request_id)
        return pending is not None and not pending.future.done()

    def resolve(self, request_id: str, response: PermissionResponse) -> None:
        pending = self._pending.get(request_id)
        if pending and not pending.future.done():
            pending.future.set_result(response)

    def resolve_matching(
        self,
        covers: Callable[[str, dict[str, Any]], bool],
        response: PermissionResponse,
    ) -> int:
        """Answer the still-open asks that a decision just made unnecessary.

        A round can put several cards up at once, and answering one of them
        with "always allow" is a statement about a PATTERN, not about that one
        call. Leaving its siblings up asks the user the question they just
        answered — and since a wait has no deadline, an unanswered sibling
        holds the turn open indefinitely rather than being quietly denied.

        Safety confirmations are skipped: those exist precisely so a remembered
        answer cannot stand in for looking at this one.
        """
        resolved = 0
        for request_id, pending in list(self._pending.items()):
            if pending.forced or pending.future.done():
                continue
            if not covers(pending.tool_name, pending.tool_args):
                continue
            pending.future.set_result(response)
            self._pending.pop(request_id, None)
            resolved += 1
        return resolved

    def cancel_pending(self, feedback: str = 'Session closed') -> int:
        """Answer every outstanding ask so nothing is left waiting on a person
        who has gone. Returns how many were resolved.

        Needed once waits can be unbounded: a suspended ask holds its turn, and
        a held turn is exempt from idle reclamation, so an abandoned prompt
        would otherwise pin its session for the life of the process.
        """
        resolved = 0
        for request_id, pending in list(self._pending.items()):
            if pending.future.done():
                continue
            pending.future.set_result(
                PermissionResponse(
                    action=PermissionAction.DENY, feedback=feedback))
            resolved += 1
            self._pending.pop(request_id, None)
        return resolved
