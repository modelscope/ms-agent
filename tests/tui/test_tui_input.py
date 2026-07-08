# Copyright (c) ModelScope Contributors. All rights reserved.
"""PromptToolkitInput: status bar formatting + non-tty fallback."""
import asyncio
from unittest.mock import patch

from ms_agent.command import CommandRouter, register_builtin_commands
from ms_agent.tui.input import PromptToolkitInput, slash_matches
from ms_agent.tui.state import TuiState
from ms_agent.ui.input import InputSource


def _router():
    r = CommandRouter()
    register_builtin_commands(r)
    return r


def test_slash_matches_prefix():
    names = [n for n, _ in slash_matches(_router(), '/mod')]
    assert 'model' in names


def test_slash_matches_bare_slash_lists_all():
    names = [n for n, _ in slash_matches(_router(), '/')]
    assert 'help' in names and 'model' in names


def test_slash_no_match_for_plain_text():
    assert list(slash_matches(_router(), 'hello world')) == []


def test_slash_completion_carries_description():
    desc = dict(slash_matches(_router(), '/model')).get('model')
    assert desc  # non-empty description shown as menu meta


def test_satisfies_input_source_protocol():
    assert isinstance(PromptToolkitInput(TuiState()), InputSource)


def test_toolbar_shows_state():
    state = TuiState(model='qwen3.7-plus', perm='restricted',
                     session_name='my-session')
    state.total_prompt_tokens = 100
    state.total_completion_tokens = 20
    tb = PromptToolkitInput(state)._toolbar()
    assert 'qwen3.7-plus' in tb
    assert '120 tok' in tb
    assert 'restricted' in tb
    assert 'my-session' in tb


def test_read_prompt_falls_back_when_not_tty():
    inp = PromptToolkitInput(TuiState())
    with patch('ms_agent.tui.input.sys.stdin') as stdin, \
            patch('builtins.input', return_value='hello'):
        stdin.isatty.return_value = False
        result = asyncio.run(inp.read_prompt('> '))
    assert result == 'hello'
