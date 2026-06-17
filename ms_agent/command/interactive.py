# Copyright (c) ModelScope Contributors. All rights reserved.
"""Surface-agnostic interactive command session.

A single :class:`InteractiveSession` owns the ``>>>`` read loop, slash-command
dispatch through one :class:`CommandRouter`, and the interpretation of a
:class:`CommandResult` into a turn outcome. Both the initial-prompt path
(``LLMAgent.run_loop``) and the mid-conversation re-prompt path
(``InputCallback.after_tool_call``) drive the same session, so the router
instance, the ``extra`` contract, and the command-loop semantics are shared
rather than duplicated per call site.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from ms_agent.command.router import CommandRouter
from ms_agent.command.types import CommandContext, CommandResultType


@dataclass
class InteractiveTurn:
    """Outcome of one interactive turn.

    ``action == 'submit'``: ``text`` is the user input to run / continue with.
    ``action == 'quit'``:   the user asked to leave (``/quit`` or EOF).
    """

    action: str
    text: Optional[str] = None


class InteractiveSession:
    """Drives a single ``>>>`` prompt turn, handling slash commands in a loop."""

    def __init__(self, router: CommandRouter, source: str = 'cli') -> None:
        self._router = router
        self._source = source

    async def run_turn(
        self,
        messages: Optional[List[Any]] = None,
        runtime: Any = None,
    ) -> InteractiveTurn:
        """Read input at ``>>>`` until a real prompt or a quit signal.

        Informational commands (``MESSAGE`` / ``MUTATE_STATE``) print their
        output and re-prompt. ``/quit`` and EOF return a quit turn. A plain
        prompt, a ``SUBMIT_PROMPT`` command, or an unrecognized command return
        a submit turn carrying the text to run.

        ``messages`` is the live conversation when one exists (mid-turn), or
        ``None`` at the initial prompt; it is exposed to commands via
        ``extra['messages']`` as a list (``[]`` when there is no conversation
        yet) so command handlers never have to special-case ``None``.
        """
        while True:
            try:
                query = input('>>> ').strip()
            except (EOFError, KeyboardInterrupt):
                return InteractiveTurn(action='quit')
            if not query:
                continue
            if not self._router.is_command(query):
                return InteractiveTurn(action='submit', text=query)

            cmd_name, args = self._router.parse_input(query)
            ctx = CommandContext(
                raw_input=query,
                command_name=cmd_name,
                args=args,
                source=self._source,
                runtime=runtime,
                extra={
                    'router': self._router,
                    'messages': messages if messages is not None else [],
                },
            )
            result = await self._router.dispatch(ctx)
            if result is None:
                # Unrecognized command — treat it as a normal prompt.
                return InteractiveTurn(action='submit', text=query)
            if result.type == CommandResultType.QUIT:
                if result.content:
                    print(result.content)
                return InteractiveTurn(action='quit')
            if result.type == CommandResultType.SUBMIT_PROMPT:
                return InteractiveTurn(action='submit', text=result.content)
            # MESSAGE / MUTATE_STATE: show output and prompt again.
            if result.content:
                print(result.content)
