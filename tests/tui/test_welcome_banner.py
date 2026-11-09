"""Welcome-page path text stays identifiable when it wraps."""
from ms_agent.tui.app import format_welcome_directory, welcome_value_width


def test_short_path_uses_home_tilde():
    text = format_welcome_directory(
        '/Users/luyan/workspace/app', 80, '/Users/luyan')
    assert text == '~/workspace/app'
    assert '…' not in text


def test_long_path_wraps_on_separators_and_keeps_the_prefix():
    path = '/Users/luyan/workspace/modelscope-agent-feat-tui-align'
    text = format_welcome_directory(path, 24, '/Users/luyan')
    assert text.splitlines()[0] == '~/workspace/'
    assert ''.join(text.splitlines()) == '~/workspace/modelscope-agent-feat-tui-align'
    assert '…' not in text
    assert not text.startswith('space/')


def test_narrow_terminal_stacks_the_info_panel():
    value_w, stack = welcome_value_width(100, 69, len('directory'))
    assert stack is True
    assert value_w >= 24


def test_wide_terminal_keeps_the_panel_beside_the_wordmark():
    value_w, stack = welcome_value_width(160, 69, len('directory'))
    assert stack is False
    assert value_w >= 36
