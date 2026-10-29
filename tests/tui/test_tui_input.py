# Copyright (c) ModelScope Contributors. All rights reserved.
"""PromptToolkitInput: status bar formatting + non-tty fallback."""
import asyncio
from unittest.mock import patch

from ms_agent.command import CommandRouter, register_builtin_commands
from ms_agent.tui.input import (PromptToolkitInput, slash_matches,
                                 split_prompt_lines)
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


def test_split_prompt_lines_keeps_each_pasted_line():
    assert split_prompt_lines('/model qwen\nhello') == ['/model qwen', 'hello']
    # A trailing Enter is not an extra blank command.
    assert split_prompt_lines('/model qwen\nhello\n') == ['/model qwen', 'hello']
    assert split_prompt_lines('/model a\r\nsecond\r\n') == ['/model a', 'second']
    assert split_prompt_lines('just one') == ['just one']
    assert split_prompt_lines('\x1b[200~/model qwen\nhello\x1b[201~') == [
        '/model qwen', 'hello'
    ]
    assert split_prompt_lines('^[[200~hello^[[201~') == ['hello']


def test_cursor_report_does_not_become_the_command():
    # Cooked echo and the raw CSI both have to come off the command.
    assert split_prompt_lines('^[[8;8R/mcp list') == ['/mcp list']
    assert split_prompt_lines('\x1b[8;8R/mcp list') == ['/mcp list']
    assert split_prompt_lines('^[[8;8R\n/mcp list') == ['/mcp list']
    assert split_prompt_lines('\x1b[200~^[[8;8R/mcp list\x1b[201~') == [
        '/mcp list'
    ]
    # A report by itself is not a message. A real blank line in a paste stays.
    assert split_prompt_lines('^[[8;8R') == ['']
    assert split_prompt_lines('keep\n\nstill') == ['keep', '', 'still']


def test_multiline_paste_is_one_prompt_then_queued_lines():
    """The second line of a paste must come back as its own read, so /model
    cannot swallow it into the model id. Live is released before the prompt
    draws, and a queued line does not draw another divider."""
    from io import StringIO

    from rich.console import Console

    order = []

    class _Renderer:
        def release_terminal(self):
            order.append('release')

    class _Session:
        calls = 0

        async def prompt_async(self, *args, **kwargs):
            order.append('prompt')
            _Session.calls += 1
            return '/model qwen\nhello\n'

    with patch('ms_agent.tui.input.sys.stdin') as stdin:
        stdin.isatty.return_value = False
        console = Console(file=StringIO(), force_terminal=False, width=40)
        prints = []
        original = console.print

        def _spy(*args, **kwargs):
            prints.append(args)
            return original(*args, **kwargs)

        console.print = _spy
        inp = PromptToolkitInput(TuiState(), console=console, renderer=_Renderer())
    inp._session = _Session()

    with patch('ms_agent.tui.input.sys.stdin') as stdin:
        stdin.isatty.return_value = True
        first = asyncio.run(inp.read_prompt())
        second = asyncio.run(inp.read_prompt())

    assert first == '/model qwen'
    assert second == 'hello'
    assert _Session.calls == 1
    assert order == ['release', 'prompt', 'release']
    assert len(prints) == 1  # divider only for the real prompt
