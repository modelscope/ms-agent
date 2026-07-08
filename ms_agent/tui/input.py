# Copyright (c) ModelScope Contributors. All rights reserved.
"""prompt_toolkit-backed async input for the TUI.

Implements the ``ms_agent.ui.InputSource`` contract: an awaitable
``read_prompt`` that reads a line via ``PromptSession.prompt_async`` so the
native agent loop can await input without blocking the event loop. Adds a
persistent bottom status bar (model · tokens · perm · session) and slash-command
completion sourced from the agent's ``CommandRouter`` (scoped to ``tui``).

Degrades gracefully: when prompt_toolkit or a TTY is unavailable (pipes, CI),
falls back to blocking ``input()`` in an executor, so the TUI stays scriptable.
"""
from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, Optional

from ms_agent.tui.state import TuiState
from ms_agent.tui.theme import DEFAULT_THEME, Theme

if TYPE_CHECKING:
    from ms_agent.command.router import CommandRouter


def slash_matches(router, text: str):
    """Yield ``(name, description)`` for /command completions of ``text``.

    Only fires when the line starts with ``/`` (so file paths and normal text
    don't trigger a menu). Scoped to the ``tui`` command source; de-dupes names
    and aliases. Kept dependency-free so it's unit-testable without a terminal.
    """
    if router is None or not text.startswith('/'):
        return
    word = text[1:].lower()
    seen = set()
    for cmds in router.list_commands('tui').values():
        for c in cmds:
            for nm in (c.name, *getattr(c, 'aliases', ())):
                if nm.lower().startswith(word) and nm not in seen:
                    seen.add(nm)
                    yield nm, c.description


class PromptToolkitInput:
    """Async input source with a status bar and slash completion."""

    def __init__(self, state: TuiState,
                 router: Optional['CommandRouter'] = None,
                 theme: Theme = DEFAULT_THEME,
                 console: object = None) -> None:
        self._state = state
        self._router = router
        self._theme = theme
        self._console = console  # rich Console, for the pre-prompt divider
        self._session = self._build_session()

    def _build_session(self):
        # Only build a prompt_toolkit session for a real terminal. Constructing
        # one under a pipe/CI emits a "not a terminal" warning; the executor
        # input() fallback in read_prompt handles those cases cleanly.
        if not sys.stdin.isatty():
            return None
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.completion import Completer, Completion
            from prompt_toolkit.history import InMemoryHistory
            from prompt_toolkit.styles import Style

            router = self._router

            class _SlashCompleter(Completer):
                def get_completions(self, document, complete_event):
                    text = document.text_before_cursor
                    for name, desc in slash_matches(router, text):
                        yield Completion('/' + name, start_position=-len(text),
                                         display=f'/{name}', display_meta=desc)

            from prompt_toolkit.formatted_text import HTML

            style = Style.from_dict({
                'completion-menu': 'bg:#1c1c1c',
                'completion-menu.completion': 'bg:#1c1c1c #d0d0d0',
                'completion-menu.completion.current': 'bg:#00afd7 #000000 bold',
                'completion-menu.meta.completion': 'bg:#1c1c1c #6c6c6c',
                'completion-menu.meta.completion.current': 'bg:#0087af #e4e4e4',
                'scrollbar.background': 'bg:#303030',
                'scrollbar.button': 'bg:#00afd7',
                # a calm dim status line, not the default reversed bar
                'bottom-toolbar': 'noreverse bg:default #808080',
                'bottom-toolbar.text': 'noreverse bg:default #808080',
            })
            return PromptSession(
                history=InMemoryHistory(),
                completer=_SlashCompleter(),
                complete_while_typing=True,
                bottom_toolbar=self._toolbar,
                placeholder=HTML(
                    '<ansibrightblack>Type a message'
                    '  ·  / for commands  ·  ↑ history</ansibrightblack>'),
                style=style)
        except Exception:
            return None

    def _toolbar(self):
        s = self._state
        parts = []
        if s.model:
            parts.append(s.model)
        parts.append(f'{s.total_tokens} tok')
        if s.perm:
            parts.append(s.perm)
        if s.session_name:
            parts.append(s.session_name)
        return '  ' + ' · '.join(parts)

    def _message(self):
        from prompt_toolkit.formatted_text import HTML
        return HTML(f'<b><ansicyan>{self._theme.prompt_symbol}</ansicyan></b> ')

    async def read_prompt(self, prompt: str = '❯ ') -> str:
        # The TUI owns its prompt presentation; the caller's ``prompt`` arg is
        # only a fallback hint for the non-interactive path.
        if self._session is not None and sys.stdin.isatty():
            # A subtle full-width divider separates the input from the
            # conversation above (Claude Code style).
            if self._console is not None:
                from rich.rule import Rule
                self._console.print(Rule(style='grey30'))
            return await self._session.prompt_async(self._message())
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, input, prompt)
