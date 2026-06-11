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
from typing import Any, Protocol
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
    async def ask(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        context: str,
        suggestions: list[str] | None = None,
    ) -> PermissionResponse: ...


class AutoPermissionHandler:
    """Always allows — used as fallback or in auto mode."""

    async def ask(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        context: str,
        suggestions: list[str] | None = None,
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
        choice = await loop.run_in_executor(None, lambda: input('Choice [y/s/a/e/n]: ').strip().lower())

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
    def emit(self, event: dict[str, Any]) -> None: ...


class WebPermissionHandler:
    """Async handler that suspends on a Future until the frontend responds."""

    def __init__(
        self,
        event_emitter: EventEmitter,
        timeout: float = 120.0,
    ) -> None:
        self._pending: dict[str, asyncio.Future[PermissionResponse]] = {}
        self._event_emitter = event_emitter
        self._timeout = timeout

    async def ask(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        context: str,
        suggestions: list[str] | None = None,
    ) -> PermissionResponse:
        request_id = uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[PermissionResponse] = loop.create_future()
        self._pending[request_id] = future

        self._event_emitter.emit({
            'type': 'permission_request',
            'request_id': request_id,
            'tool_name': tool_name,
            'tool_args': tool_args,
            'context': context,
            'suggestions': suggestions or [],
            'options': [a.value for a in PermissionAction],
        })

        try:
            return await asyncio.wait_for(future, timeout=self._timeout)
        except asyncio.TimeoutError:
            return PermissionResponse(
                action=PermissionAction.DENY,
                feedback='Permission request timed out',
            )
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, request_id: str, response: PermissionResponse) -> None:
        future = self._pending.get(request_id)
        if future and not future.done():
            future.set_result(response)
