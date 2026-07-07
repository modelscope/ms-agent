# Copyright (c) ModelScope Contributors. All rights reserved.
"""Rich-styled permission handler for the TUI.

Same 5-choice contract as ``CLIPermissionHandler`` ([y]/[s]/[a]/[e]/[n]) but
rendered through the shared ``rich`` console so the confirmation matches the
rest of the TUI instead of a raw stderr box.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel


class TUIPermissionHandler:
    def __init__(self, console: Optional[Console] = None, io: Any = None) -> None:
        self._console = console or Console()
        self._io = io

    async def ask(self, tool_name, tool_args, context, suggestions=None):
        from ms_agent.permission.handler import (PermissionAction,
                                                 PermissionResponse)
        args_str = json.dumps(tool_args, ensure_ascii=False, indent=2)
        if len(args_str) > 600:
            args_str = args_str[:600] + '\n…'
        suggestion = suggestions[0] if suggestions else tool_name
        body = (
            f'[bold]tool[/]  {tool_name}\n'
            f'[bold]args[/]  {args_str}\n'
            + (f'[dim]{context}[/]\n' if context else '')
            + '\n[green]y[/] allow once   [green]s[/] allow session   '
            + '[green]a[/] always   [yellow]e[/] edit args   [red]n[/] deny')
        self._console.print(
            Panel(body, title='🔒 Permission required',
                  border_style='magenta', expand=False))

        # Read via plain input() in the executor. The permission ask runs from
        # a worker thread (run_in_executor) while the main loop awaits; using
        # prompt_toolkit here would wrestle the main thread for the terminal.
        # Enforcer serializes asks, so a simple blocking read is safe.
        def _read(prompt):
            return input(prompt)

        loop = asyncio.get_running_loop()
        choice = (await loop.run_in_executor(
            None, lambda: _read('choice [y/s/a/e/n]: '))).strip().lower()

        if choice == 's':
            return PermissionResponse(action=PermissionAction.ALLOW_SESSION,
                                      pattern=suggestion)
        if choice == 'a':
            edited = (await loop.run_in_executor(
                None, lambda: _read(f'pattern [{suggestion}]: '))).strip()
            return PermissionResponse(action=PermissionAction.ALLOW_ALWAYS,
                                      pattern=edited or suggestion)
        if choice == 'e':
            raw = (await loop.run_in_executor(
                None, lambda: _read('new args (JSON): '))).strip()
            try:
                new_args = json.loads(raw)
            except json.JSONDecodeError:
                self._console.print('[red]invalid JSON — denying[/]')
                return PermissionResponse(action=PermissionAction.DENY)
            return PermissionResponse(action=PermissionAction.MODIFY,
                                      updated_args=new_args)
        if choice == 'n':
            return PermissionResponse(action=PermissionAction.DENY)
        return PermissionResponse(action=PermissionAction.ALLOW_ONCE)
