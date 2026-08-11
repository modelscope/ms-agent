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

    def __init__(self,
                 router: CommandRouter,
                 source: str = 'cli',
                 input_source: Any = None,
                 event_sink: Any = None) -> None:
        self._router = router
        self._source = source
        # Async InputSource (ms_agent.ui). Its awaitable read_prompt lets the
        # native loop drive a TUI / WebUI without blocking the event loop. When
        # None, bare input() is used so CLI behavior is unchanged.
        self._input_source = input_source
        # AgentEventSink for command output (MESSAGE results): routed as a
        # Notice so a TUI renders it on the same channel as everything else.
        # When None, plain print() is used (CLI).
        self._event_sink = event_sink

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
                if self._input_source is not None:
                    query = (await
                             self._input_source.read_prompt('>>> ')).strip()
                else:
                    query = input('>>> ').strip()
            except (EOFError, KeyboardInterrupt):
                return InteractiveTurn(action='quit')
            if not query:
                continue
            if not self._router.is_command(query):
                # Echo the user turn on the event channel (fills the ACP
                # user_message_chunk gap). A TUI ignores it — the terminal
                # already shows the typed line — but a WebUI renders it.
                if self._event_sink is not None:
                    from ms_agent.ui.events import UserMessage
                    self._event_sink.emit(UserMessage(text=query))
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
                    self._emit(result.content)
                return InteractiveTurn(action='quit')
            if result.type == CommandResultType.SUBMIT_PROMPT:
                return InteractiveTurn(action='submit', text=result.content)
            # MESSAGE / MUTATE_STATE: show output and prompt again.
            if result.content:
                self._emit(result.content)

    def _emit(self, text: str) -> None:
        if self._event_sink is not None:
            from ms_agent.ui.events import Notice
            self._event_sink.emit(Notice(level='info', text=text))
        else:
            print(text)
