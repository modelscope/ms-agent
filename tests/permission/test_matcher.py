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

    def test_non_string_content_is_coerced(self, matcher):
        # Non-string args must not crash fnmatch (TypeError).
        result = matcher.match_with_content(
            'file_system---read_file:/tmp/*',
            'file_system---read_file',
            {'path': ['/tmp/a', '/tmp/b']},
        )
        assert isinstance(result, bool)


class TestBareCommandVariant:
    """``<cmd> *`` means "that command with any arguments" — and with NONE is a
    case of that. fnmatch wants the space plus a character, so bare ``curl``
    slipped past the very ask rule written to gate it, and a remembered
    ``whoami *`` failed to match the ``whoami`` it was generated from."""

    TOOL = 'code_executor---shell_executor'

    def _m(self, pattern: str, command: str) -> bool:
        return PermissionMatcher().match_with_content(
            f'{self.TOOL}:{pattern}', self.TOOL, {'command': command})

    def test_argument_less_command_matches(self):
        assert self._m('whoami *', 'whoami')
        assert self._m('curl *', 'curl')

    def test_command_with_arguments_still_matches(self):
        assert self._m('whoami *', 'whoami --version')
        assert self._m('curl *', 'curl https://example.com')

    def test_does_not_match_a_longer_command_name(self):
        assert not self._m('ls *', 'lsof')

    def test_applies_per_alternative(self):
        assert self._m('ls *|cat *', 'cat')
        assert not self._m('ls *|cat *', 'rm')

    def test_leaves_non_space_star_patterns_alone(self):
        # `dd if=*` / `rm -rf /*`: the trailing component is meaningful, not an
        # optional argument list, so the bare command must NOT match.
        assert self._m('dd if=*', 'dd if=/dev/zero')
        assert not self._m('dd if=*', 'dd')
        assert not self._m('rm -rf /*', 'rm')

    def test_path_patterns_unaffected(self):
        assert not PermissionMatcher().match_with_content(
            'file_system---read_file:~/.ssh/*', 'file_system---read_file',
            {'path': '~/.ssh'})
