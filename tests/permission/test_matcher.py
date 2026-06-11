"""Tests for PermissionMatcher."""

import pytest

from ms_agent.permission.matcher import PermissionMatcher


@pytest.fixture
def matcher():
    return PermissionMatcher()


class TestMatch:
    def test_exact_match(self, matcher):
        assert matcher.match('file_system---read_file', 'file_system---read_file')

    def test_wildcard_star(self, matcher):
        assert matcher.match('file_system---*', 'file_system---read_file')
        assert matcher.match('*---read_file', 'file_system---read_file')
        assert matcher.match('*', 'anything')

    def test_wildcard_question(self, matcher):
        assert matcher.match('file_system---read_fil?', 'file_system---read_file')
        assert not matcher.match('file_system---read_fil?', 'file_system---read_files')

    def test_no_match(self, matcher):
        assert not matcher.match('file_system---write_file', 'file_system---read_file')

    def test_pipe_alternatives(self, matcher):
        assert matcher.match('read_file|write_file', 'read_file')
        assert matcher.match('read_file|write_file', 'write_file')
        assert not matcher.match('read_file|write_file', 'edit_file')

    def test_pipe_with_wildcards(self, matcher):
        assert matcher.match('file_system---*|web_search---*', 'web_search---fetch_page')

    def test_empty_pattern(self, matcher):
        assert not matcher.match('', 'file_system---read_file')


class TestMatchWithContent:
    def test_tool_name_only(self, matcher):
        assert matcher.match_with_content(
            'file_system---read_file',
            'file_system---read_file',
            {'path': '/tmp/test'},
        )

    def test_content_pattern(self, matcher):
        assert matcher.match_with_content(
            'code_executor---shell_executor:pip *',
            'code_executor---shell_executor',
            {'command': 'pip install requests'},
        )

    def test_content_no_match(self, matcher):
        assert not matcher.match_with_content(
            'code_executor---shell_executor:npm *',
            'code_executor---shell_executor',
            {'command': 'pip install requests'},
        )

    def test_content_pattern_with_wildcard_tool(self, matcher):
        assert matcher.match_with_content(
            '*---shell_executor:ls *',
            'code_executor---shell_executor',
            {'command': 'ls -la'},
        )

    def test_no_content_available(self, matcher):
        assert not matcher.match_with_content(
            'unknown---tool:pattern',
            'unknown---tool',
            {'some_arg': 'value'},
        )
