# Copyright (c) ModelScope Contributors. All rights reserved.
"""TUIPermissionHandler owns the terminal while its menu is up.

The menu is a prompt_toolkit Application rendered inline on the SAME event loop
the renderer draws from, and tool completions now arrive as each call finishes
(LLMAgent.parallel_tool_call) rather than after the whole round — so approving
one call can open the next call's menu while the first is still executing, and
its result would land inside the menu the user is reading.
"""
from io import StringIO

import pytest
from rich.console import Console

from ms_agent.permission.handler import PermissionAction
from ms_agent.tui import permission as permission_mod
from ms_agent.tui.permission import TUIPermissionHandler
from ms_agent.tui.renderer import RichEventSink
from ms_agent.tui.state import TuiState
from ms_agent.ui.events import ToolCallCompleted, ToolCallStarted


def _renderer():
    console = Console(file=StringIO(), force_terminal=False, width=80)
    return RichEventSink(console, TuiState()), console


@pytest.mark.asyncio
async def test_sibling_completion_does_not_print_into_the_menu(monkeypatch):
    renderer, console = _renderer()
    handler = TUIPermissionHandler(console=console, renderer=renderer)
    renderer.emit(
        ToolCallStarted(
            call_id='c1', name='file_system---read_file',
            arguments={'path': 'a.txt'}))
    seen_during_menu = {}

    async def fake_menu(options, *, default=0, header=None):
        # A sibling call finishes while the user is deciding.
        renderer.emit(
            ToolCallCompleted(
                call_id='c1', name='file_system---read_file', result='aaa'))
        seen_during_menu['out'] = console.file.getvalue()
        return 0  # "Allow once"

    monkeypatch.setattr(permission_mod, 'select_async', fake_menu)
    resp = await handler.ask('file_system---write_file', {'path': 'b.txt'}, '')

    assert resp.action == PermissionAction.ALLOW_ONCE
    assert 'aaa' not in seen_during_menu['out']  # held while the menu was up
    assert 'aaa' in console.file.getvalue()  # drawn once the menu closed


@pytest.mark.asyncio
async def test_handler_without_a_renderer_still_works(monkeypatch):
    """Embedders/tests may construct the handler bare — no renderer to hold."""
    console = Console(file=StringIO(), force_terminal=False, width=80)
    handler = TUIPermissionHandler(console=console)

    async def fake_menu(options, *, default=0, header=None):
        return 4  # "Deny"

    monkeypatch.setattr(permission_mod, 'select_async', fake_menu)
    resp = await handler.ask('code_executor---shell', {'command': 'rm -rf /'},
                             '')
    assert resp.action == PermissionAction.DENY
