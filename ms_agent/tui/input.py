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
import re
import sys
from typing import TYPE_CHECKING, Optional

from ms_agent.tui.state import TuiState
from ms_agent.tui.theme import DEFAULT_THEME, Theme

if TYPE_CHECKING:
    from ms_agent.command.router import CommandRouter

# Bracketed paste wraps the clipboard in these markers. If they leak into the
# line (the terminal was not in paste mode) they must not become part of the
# command. The caret form is how a cooked terminal echoes the same bytes.
_PASTE_MARKERS = (
    '\x1b[200~',
    '\x1b[201~',
    '^[[200~',
    '^[[201~',
)
# Cursor Position Report. A cooked terminal echoes it as text, so
# ``^[[8;8R/mcp list`` would otherwise be sent to the model.
_CPR_RE = re.compile(r'(?:\x1b\[\d+;\d+R|\^\[\[\d+;\d+R)')


def _strip_terminal_noise(line: str) -> str:
    for marker in _PASTE_MARKERS:
        line = line.replace(marker, '')
    return _CPR_RE.sub('', line)


def split_prompt_lines(text: str) -> list:
    """Split one paste into the lines the command loop should see.

    prompt_toolkit returns a multiline paste as a single string. Fed through
    whole, ``/model`` treats the next line as part of the model id. A trailing
    empty line (the paste ended on Enter) is not itself a command. A cursor
    position report (``^[[8;8R``) is terminal noise, not part of the command.
    """
    cleaned = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    if '\n' not in cleaned:
        return [_strip_terminal_noise(cleaned)]
    lines = cleaned.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    kept = []
    for line in lines:
        stripped = _strip_terminal_noise(line)
        # A line that was only a cursor report must not be sent.
        if stripped == '' and line != '':
            continue
        kept.append(stripped)
    return kept or ['']


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

    def __init__(self,
                 state: TuiState,
                 router: Optional['CommandRouter'] = None,
                 theme: Theme = DEFAULT_THEME,
                 console: object = None,
                 renderer: object = None) -> None:
        self._state = state
        self._router = router
        self._theme = theme
        self._console = console  # rich Console, for the pre-prompt divider
        # RichEventSink. Released before prompt_toolkit draws, so Live's
        # refresh thread is not still writing when raw mode starts.
        self._renderer = renderer
        # Lines left over from a multiline paste. Each becomes its own prompt.
        self._queued: list = []
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
                        yield Completion(
                            '/' + name,
                            start_position=-len(text),
                            display=f'/{name}',
                            display_meta=desc)

            from prompt_toolkit.formatted_text import HTML

            style = Style.from_dict({
                'completion-menu':
                'bg:#1c1c1c',
                'completion-menu.completion':
                'bg:#1c1c1c #d0d0d0',
                'completion-menu.completion.current':
                'bg:#00afd7 #000000 bold',
                'completion-menu.meta.completion':
                'bg:#1c1c1c #6c6c6c',
                'completion-menu.meta.completion.current':
                'bg:#0087af #e4e4e4',
                'scrollbar.background':
                'bg:#303030',
                'scrollbar.button':
                'bg:#00afd7',
                # a calm dim status line, not the default reversed bar
                'bottom-toolbar':
                'noreverse bg:default #808080',
                'bottom-toolbar.text':
                'noreverse bg:default #808080',
            })
            return PromptSession(
                history=InMemoryHistory(),
                completer=_SlashCompleter(),
                complete_while_typing=True,
                # Up and down walk this history.
                bottom_toolbar=self._toolbar,
                placeholder=HTML(
                    '<ansibrightblack>Type a message'
                    '  ·  / for commands  ·  ↑ history</ansibrightblack>'),
                style=style)
        except Exception:
            return None

    def note_model(self, model: str) -> None:
        """Refresh the status-bar model after a command mutates it."""
        if model:
            self._state.model = str(model)

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
        return HTML(
            f'<b><ansicyan>{self._theme.prompt_symbol}</ansicyan></b> ')

    def _release_terminal(self) -> None:
        renderer = self._renderer
        if renderer is None:
            return
        release = getattr(renderer, 'release_terminal', None)
        if release is not None:
            release()

    async def read_prompt(self, prompt: str = '❯ ') -> str:
        # The TUI owns its prompt presentation; the caller's ``prompt`` arg is
        # only a fallback hint for the non-interactive path.
        # Live must be fully stopped before prompt_toolkit enables raw mode
        # and bracketed paste. A queued paste line skips the divider, but
        # still waits out a region left up by the turn that just finished.
        self._release_terminal()
        if self._queued:
            return self._queued.pop(0)
        if self._session is not None and sys.stdin.isatty():
            # A subtle full-width divider separates the input from the
            # conversation above (Claude Code style).
            if self._console is not None:
                from rich.rule import Rule
                self._console.print(Rule(style='grey30'))
            # prompt_toolkit owns Ctrl-C while the line is being edited.
            # After it returns, the TUI handler covers the stream that follows.
            sigint = getattr(self, '_sigint', None)
            if sigint is not None:
                sigint._streaming = False
            try:
                text = await self._session.prompt_async(self._message())
            finally:
                if sigint is not None:
                    sigint._arm_turn_sigint()
                    sigint._streaming = True
            lines = split_prompt_lines(text)
            if len(lines) > 1:
                self._queued.extend(lines[1:])
            return lines[0] if lines else ''
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, input, prompt)
