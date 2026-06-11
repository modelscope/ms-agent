"""Tests for generate_suggestions."""

from ms_agent.permission.suggestions import generate_suggestions


class TestShellSuggestions:
    def test_plain_command(self):
        suggestions = generate_suggestions(
            'code_executor---shell_executor',
            {'command': 'ls -la'},
        )
        assert suggestions[0] == 'code_executor---shell_executor:ls *'
        assert 'code_executor---shell_executor' in suggestions

    def test_strips_timeout_wrapper(self):
        suggestions = generate_suggestions(
            'code_executor---shell_executor',
            {'command': 'timeout 10 ls -la'},
        )
        assert suggestions[0] == 'code_executor---shell_executor:ls *'

    def test_strips_nice_wrapper(self):
        suggestions = generate_suggestions(
            'code_executor---shell_executor',
            {'command': 'nice -n 10 pip install requests'},
        )
        assert suggestions[0] == 'code_executor---shell_executor:pip *'

    def test_empty_command(self):
        suggestions = generate_suggestions(
            'code_executor---shell_executor',
            {'command': ''},
        )
        assert suggestions == ['code_executor---shell_executor']


class TestOtherTools:
    def test_file_system(self):
        suggestions = generate_suggestions(
            'file_system---read_file',
            {'path': '/src/main.py'},
        )
        assert suggestions == ['file_system---read_file']

    def test_web_search(self):
        suggestions = generate_suggestions(
            'web_search---search',
            {'query': 'test'},
        )
        assert suggestions[0] == 'web_search---*'
