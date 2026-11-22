# Copyright (c) ModelScope Contributors. All rights reserved.
from ms_agent.command.types import CommandContext
from ms_agent.command.usage import arg_error


def test_arg_error_is_one_syntax_line():
    result = arg_error(
        '/model catalog remove <provider> <model>',
        reason='Unknown catalog action \'foo\'',
        note='drop = remove',
        got='/model catalog foo bar',
    )
    text = result.content
    assert text.startswith("Unknown catalog action 'foo'.")
    assert 'Need: /model catalog remove <provider> <model>' in text
    assert 'Got:  /model catalog foo bar' in text
    assert 'drop = remove' in text
    assert 'provider add' not in text


def test_arg_error_fills_got_from_ctx():
    ctx = CommandContext(
        raw_input='/model provider key',
        command_name='model',
        args='provider key',
    )
    result = arg_error(
        '/model provider key <provider> <key>|clear', ctx=ctx)
    assert 'Need: /model provider key <provider> <key>|clear' in result.content
    assert 'Got:  /model provider key' in result.content
