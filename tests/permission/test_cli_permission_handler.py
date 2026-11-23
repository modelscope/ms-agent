# Copyright (c) ModelScope Contributors. All rights reserved.
"""The CLI confirmation menu must never approve on a stray keystroke.

The menu advertises explicit keys (y/s/a/e/n). An empty Enter, a typo, or a
closed stdin is none of those, so the handler re-prompts a bounded number of
times and otherwise denies by default.
"""
import builtins

import pytest

from ms_agent.permission.handler import CLIPermissionHandler, PermissionAction


class _EOF:
    """Sentinel: simulate a closed stdin instead of a typed answer."""


def _set_input(monkeypatch, answer):
    if answer is _EOF:

        def fake_input(*args, **kwargs):
            raise EOFError()

    else:

        def fake_input(*args, **kwargs):
            return answer

    monkeypatch.setattr(builtins, 'input', fake_input)


@pytest.mark.asyncio
@pytest.mark.parametrize('answer', ['', 'yse', 'q', ' ', _EOF])
async def test_unclear_answer_never_allows(answer, monkeypatch, capsys):
    _set_input(monkeypatch, answer)
    response = await CLIPermissionHandler().ask('shell', {}, '')
    assert response.action is not PermissionAction.ALLOW_ONCE
    assert response.action is PermissionAction.DENY


@pytest.mark.asyncio
async def test_keyboard_interrupt_denies(monkeypatch, capsys):
    def fake_input(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(builtins, 'input', fake_input)
    response = await CLIPermissionHandler().ask('shell', {}, '')
    assert response.action is PermissionAction.DENY


@pytest.mark.asyncio
@pytest.mark.parametrize('answer,expected', [
    ('y', PermissionAction.ALLOW_ONCE),
    ('n', PermissionAction.DENY),
])
async def test_explicit_answer(answer, expected, monkeypatch, capsys):
    _set_input(monkeypatch, answer)
    response = await CLIPermissionHandler().ask('shell', {}, '')
    assert response.action is expected
