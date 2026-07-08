# Copyright (c) ModelScope Contributors. All rights reserved.
"""Inline selection menu key handling (driven via a prompt_toolkit pipe).

Validates the arrow-key / number-key / enter / cancel logic without a real
terminal, so the permission menu's behavior is regression-guarded.
"""
import asyncio

from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from ms_agent.tui.select import _menu_async

OPTS = ['Allow once', 'Allow for this session', 'Always allow', 'Deny']


def _run(keys: str, default: int = 0):
    async def go():
        with create_pipe_input() as inp:
            with create_app_session(input=inp, output=DummyOutput()):
                inp.send_text(keys)
                return await _menu_async(OPTS, default)

    return asyncio.run(go())


def test_enter_picks_default():
    assert _run('\r') == 0


def test_enter_picks_given_default():
    assert _run('\r', default=2) == 2


def test_down_then_enter():
    assert _run('\x1b[B\r') == 1  # ↓, Enter


def test_down_wraps_from_last_to_first():
    # 4 options: ↓×4 wraps back to index 0
    assert _run('\x1b[B\x1b[B\x1b[B\x1b[B\r') == 0


def test_up_then_enter_wraps():
    assert _run('\x1b[A\r') == len(OPTS) - 1  # ↑ from 0 wraps to last


def test_tab_moves_down():
    assert _run('\t\r') == 1


def test_number_key_jumps_and_selects():
    assert _run('3') == 2


def test_ctrl_c_cancels_to_none():
    assert _run('\x03') is None


def _run_with_header(keys: str, header: str):
    async def go():
        with create_pipe_input() as inp:
            with create_app_session(input=inp, output=DummyOutput()):
                inp.send_text(keys)
                return await _menu_async(OPTS, 0, header)

    return asyncio.run(go())


def test_header_does_not_break_selection():
    # A multi-line header (tool + args) renders above options; keys still work.
    assert _run_with_header('\x1b[B\r', 'tool_x\n{"a": 1}') == 1
