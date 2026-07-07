# Copyright (c) ModelScope Contributors. All rights reserved.
"""Console I/O sink for the TUI.

``RichConsoleIO`` implements the small contract the agent's console-io seam
expects (``write`` / ``end_stream`` / ``print`` / ``read_prompt``). Streaming
assistant tokens are written live to stdout; the prompt uses ``prompt_toolkit``
(slash-command completion + history) and falls back to ``input()`` when a TTY /
prompt_toolkit is unavailable (pipes, CI), so the TUI stays scriptable.
"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING, List, Optional

from rich.console import Console

if TYPE_CHECKING:
    from ms_agent.command.router import CommandRouter


class RichConsoleIO:
    """Rich-backed console I/O used by the TUI and injected into LLMAgent."""

    def __init__(
        self,
        console: Optional[Console] = None,
        router: Optional['CommandRouter'] = None,
    ) -> None:
        self.console = console or Console()
        self._router = router
        self._streaming = False
        # Shown as the prompt_toolkit bottom toolbar (model · perm · work-dir).
        self.status = ''
        self._pt_session = self._build_prompt_session()

    # -- prompt_toolkit session (best-effort) --

    def _build_prompt_session(self):
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.completion import WordCompleter
            from prompt_toolkit.history import InMemoryHistory

            words: List[str] = []
            if self._router is not None:
                for cmds in self._router.list_commands('tui').values():
                    for c in cmds:
                        words.append(f'/{c.name}')
                        words.extend(f'/{a}' for a in c.aliases)
            completer = WordCompleter(
                sorted(set(words)), sentence=True, ignore_case=True)
            return PromptSession(
                history=InMemoryHistory(), completer=completer)
        except Exception:
            return None

    # -- streaming output (called by LLMAgent step) --

    def write(self, text: str) -> None:
        """Write a streaming assistant content delta (no newline)."""
        if not self._streaming:
            self.console.print('[bold green]assistant[/] ', end='')
            self._streaming = True
        sys.stdout.write(text)
        sys.stdout.flush()

    def end_stream(self) -> None:
        """End the current streaming assistant message."""
        if self._streaming:
            sys.stdout.write('\n')
            sys.stdout.flush()
            self._streaming = False

    # -- structured output --

    def print(self, text: str = '') -> None:
        self._flush_stream()
        self.console.print(text)

    def rule(self, title: str = '') -> None:
        self._flush_stream()
        self.console.rule(title)

    def _flush_stream(self) -> None:
        if self._streaming:
            sys.stdout.write('\n')
            sys.stdout.flush()
            self._streaming = False

    # -- input --

    def read_prompt(self, prompt: str = '❯ ') -> str:
        """Read a line of input. prompt_toolkit if possible, else input()."""
        self._flush_stream()
        if self._pt_session is not None and sys.stdin.isatty():
            try:
                # No bottom_toolbar: it caused a persistent flicker in some
                # terminals. Status (model/perm/work-dir) lives in the banner.
                return self._pt_session.prompt(prompt)
            except (EOFError, KeyboardInterrupt):
                raise
            except Exception:
                pass
        return input(prompt)
