# Copyright (c) ModelScope Contributors. All rights reserved.
"""Permission handler for the TUI — an inline arrow-key confirmation menu.

Matches the pattern used by Claude Code / Qoder / hermes: a compact header for
the tool call, then a selectable menu (``❯`` cursor, ↑/↓ + number keys, Enter)
instead of a "type a letter" prompt. A non-TTY fallback keeps it scriptable.

This handler does NOT declare ``supports_concurrent_asks``, so the enforcer
serializes its asks — one terminal, one menu at a time. That alone is no longer
enough for a quiet screen: the menu runs on the same event loop the renderer
draws from, and a sibling tool call approved a moment earlier can finish while
this menu is up. So ``ask()`` also holds the renderer's output for its duration
(``RichEventSink.hold_output``).
"""
from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from rich.console import Console
from typing import Any, Optional

from ms_agent.tui.select import select_async
from ms_agent.tui.theme import DEFAULT_THEME, Theme

# Menu rows → PermissionAction. Order is the on-screen order.
_ALLOW_ONCE, _ALLOW_SESSION, _ALLOW_ALWAYS, _EDIT, _DENY = range(5)


class TUIPermissionHandler:

    def __init__(self,
                 console: Optional[Console] = None,
                 io: Any = None,
                 theme: Theme = DEFAULT_THEME,
                 renderer: Any = None) -> None:
        self._console = console or Console()
        self._theme = theme
        # The event renderer, so its draws can be held while this menu owns the
        # terminal. A sibling tool call finishing mid-menu would otherwise print
        # its result line straight through the prompt_toolkit app the user is
        # reading (tool completions arrive per call now, so that overlap is
        # reachable whenever one call is approved while another is still asked).
        self._renderer = renderer

    @contextmanager
    def _own_screen(self):
        hold = getattr(self._renderer, 'hold_output', None)
        if hold is None:
            yield  # no renderer wired (tests, embedders) — nothing to hold
            return
        with hold():
            yield

    async def ask(self, tool_name, tool_args, context, suggestions=None):
        with self._own_screen():
            return await self._ask(tool_name, tool_args, context, suggestions)

    async def _ask(self, tool_name, tool_args, context, suggestions=None):
        from ms_agent.permission.handler import (PermissionAction,
                                                 PermissionResponse)
        suggestion = suggestions[0] if suggestions else tool_name

        # No persistent box: the tool line ("• Write path") already printed by
        # the renderer is the context. The header below renders *inside* the
        # transient menu and is erased with it, so once decided only the tool
        # line + its result remain (Claude Code / Qoder style).
        header = f'⚠ allow this tool call?  {tool_name}'
        args_preview = self._format_args(tool_args)
        if args_preview:
            header += '\n' + args_preview
        if context:
            header += '\n' + str(context)

        options = [
            'Allow once',
            'Allow for this session',
            f'Always allow  [{suggestion}]',
            'Edit arguments',
            'Deny',
        ]
        idx = await select_async(options, default=_ALLOW_ONCE, header=header)

        # ── map selection → response (no persistent echo; the tool result line
        # that follows is the trace — a denial shows "└ Tool call denied …") ──
        if idx is None or idx == _DENY:
            return PermissionResponse(action=PermissionAction.DENY)

        if idx == _ALLOW_SESSION:
            return PermissionResponse(
                action=PermissionAction.ALLOW_SESSION, pattern=suggestion)
        if idx == _ALLOW_ALWAYS:
            return PermissionResponse(
                action=PermissionAction.ALLOW_ALWAYS, pattern=suggestion)
        if idx == _EDIT:
            raw = (await self._read_line('new args (JSON): ')).strip()
            try:
                new_args = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                self._console.print('[red]invalid JSON — denying[/]')
                return PermissionResponse(action=PermissionAction.DENY)
            return PermissionResponse(
                action=PermissionAction.MODIFY, updated_args=new_args)
        return PermissionResponse(action=PermissionAction.ALLOW_ONCE)

    def _format_args(self, tool_args) -> str:
        try:
            s = json.dumps(tool_args, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            s = str(tool_args)
        lines = s.splitlines()
        if len(lines) > 8:
            s = '\n'.join(lines[:8]) + '\n  …'
        elif len(s) > 400:
            s = s[:400] + '…'
        return s

    async def _read_line(self, prompt: str) -> str:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, input, prompt)
        except (EOFError, KeyboardInterrupt):
            return ''
