# Copyright (c) ModelScope Contributors. All rights reserved.
"""Compact tool presentation: action headers + result summaries."""
from ms_agent.tui.tool_view import tool_header, tool_summary


def test_write_file_header():
    assert tool_header('file_system---write_file',
                       {'path': '/a/b.md', 'content': 'x'}) == 'Write /a/b.md'


def test_shell_header():
    assert tool_header('code_executor---shell_executor',
                       {'command': 'git push'}) == 'Run git push'


def test_search_header():
    assert tool_header('web_search---exa_search',
                       {'query': 'modelscope'}) == 'Search modelscope'


def test_read_header_from_json_string_args():
    assert tool_header('file_system---read_file',
                       '{"path": "x.py"}') == 'Read x.py'


def test_generic_header_falls_back_to_action_and_arg():
    h = tool_header('custom---do_thing', {'foo': 'bar'})
    assert h == 'do thing bar'


def test_header_without_splitter():
    assert tool_header('web_search', {'query': 'q'}) == 'Search q'


def test_summary_empty_is_no_output():
    assert tool_summary('') == '(no output)'


def test_summary_single_line():
    assert tool_summary('wrote file') == 'wrote file'


def test_summary_multiline_counts_extra():
    s = tool_summary('line1\nline2\nline3')
    assert 'line1' in s and '+2 lines' in s


def test_summary_trivial_first_line_leads_with_count():
    # JSON blob whose first line is just "{" → "58 lines", not "{  (+57 lines)".
    blob = '{\n' + '\n'.join(f'  "k{i}": {i}' for i in range(56)) + '\n}'
    assert tool_summary(blob) == f'{blob.count(chr(10)) + 1} lines'


def test_summary_error():
    assert tool_summary('', 'boom') == 'error: boom'


def test_summary_truncates_long():
    assert tool_summary('x' * 200).endswith('…')
