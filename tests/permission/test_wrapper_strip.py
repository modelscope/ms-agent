"""Tests for safe wrapper stripping."""

import pytest

from ms_agent.permission.wrapper_strip import strip_safe_wrappers


class TestStripSafeWrappers:
    def test_timeout(self):
        assert strip_safe_wrappers(['timeout', '10', 'ls', '-la']) == ['ls', '-la']

    def test_timeout_with_flags(self):
        assert strip_safe_wrappers(['timeout', '--foreground', '10', 'ls']) == ['ls']

    def test_timeout_kill_after(self):
        assert strip_safe_wrappers(['timeout', '-k', '5', '10', 'ls']) == ['ls']

    def test_time(self):
        assert strip_safe_wrappers(['time', 'ls', '-la']) == ['ls', '-la']

    def test_nice_bare(self):
        assert strip_safe_wrappers(['nice', 'ls']) == ['ls']

    def test_nice_traditional(self):
        assert strip_safe_wrappers(['nice', '-10', 'ls']) == ['ls']

    def test_nice_posix(self):
        assert strip_safe_wrappers(['nice', '-n', '10', 'ls']) == ['ls']

    def test_nohup(self):
        assert strip_safe_wrappers(['nohup', 'cat', 'file']) == ['cat', 'file']

    def test_stdbuf(self):
        assert strip_safe_wrappers(['stdbuf', '-o0', 'cat', 'file']) == ['cat', 'file']

    def test_env_simple(self):
        assert strip_safe_wrappers(['env', 'ls']) == ['ls']

    def test_env_with_assignment(self):
        assert strip_safe_wrappers(['env', 'FOO=bar', 'ls']) == ['ls']

    def test_env_unsafe_flag_S(self):
        result = strip_safe_wrappers(['env', '-S', 'something', 'ls'])
        assert result == ['env', '-S', 'something', 'ls']

    def test_env_unsafe_flag_C(self):
        result = strip_safe_wrappers(['env', '-C', '/tmp', 'ls'])
        assert result == ['env', '-C', '/tmp', 'ls']

    def test_safe_env_var(self):
        assert strip_safe_wrappers(['NODE_ENV=production', 'ls']) == ['ls']

    def test_unsafe_env_var(self):
        result = strip_safe_wrappers(['HOME=/tmp', 'rm', 'file'])
        assert result == ['HOME=/tmp', 'rm', 'file']

    def test_chained_wrappers(self):
        result = strip_safe_wrappers(['timeout', '10', 'nice', '-5', 'ls'])
        assert result == ['ls']

    def test_env_var_then_wrapper(self):
        result = strip_safe_wrappers(['NODE_ENV=test', 'timeout', '10', 'ls'])
        assert result == ['ls']

    def test_empty(self):
        assert strip_safe_wrappers([]) == []

    def test_no_wrapper(self):
        assert strip_safe_wrappers(['ls', '-la']) == ['ls', '-la']
