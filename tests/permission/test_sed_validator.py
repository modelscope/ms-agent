"""Tests for sed expression safety validator."""

import pytest

from ms_agent.permission.sed_validator import (
    check_sed_expression_safety,
    is_sed_read_only,
)


class TestIsSedReadOnly:
    def test_print_only(self):
        assert is_sed_read_only(['-n', 'p'])

    def test_address_print(self):
        assert is_sed_read_only(['-n', '1,5p'])

    def test_no_n_flag(self):
        assert not is_sed_read_only(['p'])

    def test_with_in_place(self):
        assert not is_sed_read_only(['-n', '-i', 'p'])

    def test_substitution(self):
        assert not is_sed_read_only(['-n', 's/a/b/'])

    def test_e_flag_print(self):
        assert is_sed_read_only(['-n', '-e', 'p'])


class TestCheckSedExpressionSafety:
    def test_safe_expression(self):
        r = check_sed_expression_safety('s/foo/bar/')
        assert r.safe

    def test_write_command(self):
        r = check_sed_expression_safety('s/foo/bar/w /tmp/out')
        assert not r.safe
        assert 'w' in r.reason.lower() or 'Write' in r.reason

    def test_execute_command(self):
        r = check_sed_expression_safety('s/foo/bar/e')
        assert not r.safe

    def test_non_ascii(self):
        r = check_sed_expression_safety('s/foö/bar/')
        assert not r.safe
        assert 'Non-ASCII' in r.reason

    def test_newline(self):
        r = check_sed_expression_safety('s/foo/bar/\n')
        assert not r.safe

    def test_curly_braces(self):
        r = check_sed_expression_safety('{s/foo/bar/}')
        assert not r.safe

    def test_negation(self):
        r = check_sed_expression_safety('!d')
        assert not r.safe

    def test_empty(self):
        r = check_sed_expression_safety('')
        assert r.safe


class TestArbitraryDelimiter:
    """Substitution flag detection must work with any delimiter, not just '/'."""

    def test_pipe_delimiter_write(self):
        r = check_sed_expression_safety('s|foo|bar|w /tmp/out')
        assert not r.safe

    def test_hash_delimiter_exec(self):
        r = check_sed_expression_safety('s#foo#bar#e')
        assert not r.safe

    def test_at_delimiter_gw(self):
        r = check_sed_expression_safety('s@pat@rep@gw file')
        assert not r.safe

    def test_pipe_delimiter_safe(self):
        r = check_sed_expression_safety('s|foo|bar|g')
        assert r.safe

    def test_escaped_delimiter_in_pattern(self):
        r = check_sed_expression_safety('s/foo\\/bar/baz/w file')
        assert not r.safe

    def test_escaped_delimiter_safe(self):
        r = check_sed_expression_safety('s/foo\\/bar/baz/g')
        assert r.safe

    def test_semicolon_chained(self):
        r = check_sed_expression_safety('s|a|b|g;s|c|d|e')
        assert not r.safe

    def test_semicolon_chained_safe(self):
        r = check_sed_expression_safety('s|a|b|g;s|c|d|g')
        assert r.safe
