# Copyright (c) ModelScope Contributors. All rights reserved.
"""Async input contract: StdinInputSource reads a line off the event loop."""
import asyncio
from unittest.mock import patch

from ms_agent.ui.input import InputSource, StdinInputSource


def test_stdin_input_source_satisfies_protocol():
    assert isinstance(StdinInputSource(), InputSource)


def test_stdin_input_source_reads_line():
    src = StdinInputSource()
    with patch('builtins.input', return_value='hello world'):
        result = asyncio.run(src.read_prompt('>>> '))
    assert result == 'hello world'


def test_stdin_input_source_passes_prompt():
    src = StdinInputSource()
    seen = {}

    def _fake_input(prompt):
        seen['prompt'] = prompt
        return 'x'

    with patch('builtins.input', _fake_input):
        asyncio.run(src.read_prompt('agent> '))
    assert seen['prompt'] == 'agent> '


def test_stdin_input_source_propagates_eof():
    src = StdinInputSource()
    with patch('builtins.input', side_effect=EOFError):
        try:
            asyncio.run(src.read_prompt())
        except EOFError:
            pass
        else:
            raise AssertionError('EOFError should propagate for quit handling')
