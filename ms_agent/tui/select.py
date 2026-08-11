# Copyright (c) ModelScope Contributors. All rights reserved.
"""Inline arrow-key selection menu (prompt_toolkit).

A small, reusable single-choice picker rendered *in the scroll flow* (not a
full-screen dialog) — the pattern Claude Code / Qoder / hermes use for
permission prompts and model pickers: a ``❯`` cursor on the highlighted row,
↑/↓ (or Ctrl-P/N) to move, number keys to jump, Enter to confirm, Esc/Ctrl-C
to cancel. The menu erases itself on exit so only the outcome remains.

Runs on the current event loop via ``run_async`` (the agent's permission ask
executes in the main loop, so this composes cleanly). Callers must guard for a
TTY; there is a plain fallback for pipes/CI.
"""
from __future__ import annotations

import sys
from typing import List, Optional, Sequence


async def select_async(options: Sequence[str],
                       *,
                       default: int = 0,
                       header: Optional[str] = None) -> Optional[int]:
    """Show an inline menu; return the chosen index, or None if cancelled.

    ``header`` (optional, may be multi-line) renders above the options *inside*
    the transient menu — its first line bold, the rest dim — so context (e.g. a
    tool name + args) shows during the decision and is erased with the menu,
    leaving nothing behind.

    Falls back to a single blocking line read when stdin is not a TTY (accepts
    a 1-based number).
    """
    if not options:
        return None
    if not sys.stdin.isatty():
        return await _fallback_numeric(len(options))
    return await _menu_async(options, default, header)


async def _menu_async(options: Sequence[str],
                      default: int,
                      header: Optional[str] = None) -> Optional[int]:
    """The prompt_toolkit menu itself (no TTY guard, so tests can drive it via
    a pipe input + AppSession)."""
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    sel = [max(0, min(default, len(options) - 1))]
    kb = KeyBindings()

    @kb.add('up')
    @kb.add('c-p')
    def _up(event) -> None:
        sel[0] = (sel[0] - 1) % len(options)

    @kb.add('down')
    @kb.add('c-n')
    @kb.add('tab')
    def _down(event) -> None:
        sel[0] = (sel[0] + 1) % len(options)

    @kb.add('enter')
    def _accept(event) -> None:
        event.app.exit(result=sel[0])

    @kb.add('escape')
    @kb.add('c-c')
    def _cancel(event) -> None:
        event.app.exit(result=None)

    for _i in range(min(len(options), 9)):

        @kb.add(str(_i + 1))
        def _pick(event, i=_i) -> None:
            event.app.exit(result=i)

    header_lines = header.splitlines() if header else []

    def _render():
        frags = []
        for j, hl in enumerate(header_lines):
            frags.append(
                ('class:head' if j == 0 else 'class:headdim', hl + '\n'))
        for i, label in enumerate(options):
            if i == sel[0]:
                frags.append(('class:sel', f'❯ {i + 1}. {label}\n'))
            else:
                frags.append(('class:opt', f'  {i + 1}. {label}\n'))
        frags.append(('class:hint', '↑/↓ move · enter select · esc cancel'))
        return frags

    control = FormattedTextControl(_render, focusable=True, show_cursor=False)
    style = Style.from_dict({
        'sel': 'bold ansicyan',
        'opt': '',
        'head': 'bold ansiyellow',
        'headdim': 'ansibrightblack',
        'hint': 'italic ansibrightblack',
    })
    app = Application(
        layout=Layout(
            HSplit(
                [Window(control,
                        height=len(options) + 1 + len(header_lines))])),
        key_bindings=kb,
        style=style,
        full_screen=False,
        erase_when_done=True,
        mouse_support=False,
    )
    return await app.run_async()


async def _fallback_numeric(n: int) -> Optional[int]:
    """Non-TTY fallback: read a 1-based number (or legacy letter) from stdin."""
    import asyncio
    loop = asyncio.get_running_loop()
    try:
        raw = (await loop.run_in_executor(None, input, 'choice: ')).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if raw.isdigit() and 1 <= int(raw) <= n:
        return int(raw) - 1
    return _LEGACY_LETTERS.get(raw.lower())


# Back-compat for scripted input that still sends y/s/a/e/n.
_LEGACY_LETTERS = {'y': 0, 's': 1, 'a': 2, 'e': 3, 'n': 4}
