"""Tests for path validation core."""

import os
import tempfile

import pytest

from ms_agent.permission.path_validator import (
    get_glob_base_directory,
    is_dangerous_removal_path,
    validate_path,
)


class TestValidatePath:
    def test_relative_path_within_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            r = validate_path('test.txt', td, [td], 'read')
            assert r.allowed
            assert r.action == 'allow'

    def test_absolute_path_within_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            r = validate_path(os.path.join(td, 'test.txt'), td, [td], 'write')
            assert r.allowed

    def test_path_outside_allowed_write(self):
        r = validate_path('/etc/passwd', '/tmp', ['/tmp'], 'write')
        assert not r.allowed
        assert r.action == 'deny'

    def test_path_outside_allowed_read(self):
        r = validate_path('/etc/passwd', '/tmp', ['/tmp'], 'read')
        assert not r.allowed
        assert r.action == 'ask'  # read outside → ask, not deny

    def test_tilde_expansion(self):
        home = os.path.expanduser('~')
        r = validate_path('~/test.txt', '/tmp', [home], 'read')
        assert r.allowed

    def test_tilde_user_rejected(self):
        r = validate_path('~otheruser/file', '/tmp', ['/tmp'], 'read')
        assert not r.allowed
        assert 'Unsupported tilde expansion' in r.reason

    def test_tilde_plus_rejected(self):
        r = validate_path('~+/file', '/tmp', ['/tmp'], 'read')
        assert not r.allowed

    def test_shell_variable_rejected(self):
        r = validate_path('$HOME/file', '/tmp', ['/tmp'], 'write')
        assert not r.allowed
        assert 'variable expansion' in r.reason

    def test_windows_variable_rejected(self):
        r = validate_path('%TEMP%/file', '/tmp', ['/tmp'], 'write')
        assert not r.allowed

    def test_zsh_equals_rejected(self):
        r = validate_path('=ls', '/tmp', ['/tmp'], 'read')
        assert not r.allowed

    def test_glob_in_write_rejected(self):
        r = validate_path('*.txt', '/tmp', ['/tmp'], 'write')
        assert not r.allowed
        assert r.action == 'deny'

    def test_glob_in_read_uses_base_dir(self):
        with tempfile.TemporaryDirectory() as td:
            r = validate_path(os.path.join(td, '*.txt'), td, [td], 'read')
            assert r.allowed

    def test_quoted_path(self):
        with tempfile.TemporaryDirectory() as td:
            r = validate_path(f'"{td}/test.txt"', td, [td], 'write')
            assert r.allowed

    def test_multiple_allowed_dirs(self):
        with tempfile.TemporaryDirectory() as td1:
            with tempfile.TemporaryDirectory() as td2:
                r = validate_path(os.path.join(td2, 'f'), td1, [td1, td2], 'write')
                assert r.allowed


class TestReadOnlyDirectories:
    def test_read_allowed_via_read_only_dir(self):
        with tempfile.TemporaryDirectory() as write_dir:
            with tempfile.TemporaryDirectory() as ro_dir:
                r = validate_path(
                    os.path.join(ro_dir, 'data.csv'), write_dir,
                    [write_dir], 'read', read_only_dirs=[ro_dir],
                )
                assert r.allowed
                assert r.action == 'allow'

    def test_write_denied_in_read_only_dir(self):
        with tempfile.TemporaryDirectory() as write_dir:
            with tempfile.TemporaryDirectory() as ro_dir:
                r = validate_path(
                    os.path.join(ro_dir, 'data.csv'), write_dir,
                    [write_dir], 'write', read_only_dirs=[ro_dir],
                )
                assert not r.allowed
                assert r.action == 'deny'

    def test_create_denied_in_read_only_dir(self):
        with tempfile.TemporaryDirectory() as write_dir:
            with tempfile.TemporaryDirectory() as ro_dir:
                r = validate_path(
                    os.path.join(ro_dir, 'new.txt'), write_dir,
                    [write_dir], 'create', read_only_dirs=[ro_dir],
                )
                assert not r.allowed
                assert r.action == 'deny'

    def test_read_outside_both_dirs_returns_ask(self):
        with tempfile.TemporaryDirectory() as write_dir:
            with tempfile.TemporaryDirectory() as ro_dir:
                r = validate_path(
                    '/etc/passwd', write_dir,
                    [write_dir], 'read', read_only_dirs=[ro_dir],
                )
                assert not r.allowed
                assert r.action == 'ask'
                assert r.category == 'read_outside_dirs'

    def test_allowed_dir_takes_precedence_over_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            r = validate_path(
                os.path.join(td, 'file.txt'), td,
                [td], 'read', read_only_dirs=[td],
            )
            assert r.allowed

    def test_write_in_allowed_dir_still_works(self):
        with tempfile.TemporaryDirectory() as td:
            with tempfile.TemporaryDirectory() as ro_dir:
                r = validate_path(
                    os.path.join(td, 'file.txt'), td,
                    [td], 'write', read_only_dirs=[ro_dir],
                )
                assert r.allowed


class TestIsDangerousRemovalPath:
    @pytest.mark.parametrize('path', [
        '/',
        '*',
        '/tmp/*',
        '/usr',
        os.path.expanduser('~'),
    ])
    def test_dangerous_paths(self, path):
        assert is_dangerous_removal_path(path)

    @pytest.mark.parametrize('path', [
        '/tmp/mydir',
        '/usr/local/bin',
        'relative/path',
        './test.txt',
    ])
    def test_safe_paths(self, path):
        assert not is_dangerous_removal_path(path)

    def test_windows_drive_root(self):
        assert is_dangerous_removal_path('C:/')
        assert is_dangerous_removal_path('D:\\')

    def test_windows_drive_child(self):
        assert is_dangerous_removal_path('C:/Windows')

    def test_normalized_slashes(self):
        assert is_dangerous_removal_path('///')


class TestGetGlobBaseDirectory:
    def test_no_glob(self):
        assert get_glob_base_directory('/tmp/test.txt') == '/tmp'

    def test_glob_at_end(self):
        assert get_glob_base_directory('/tmp/*.txt') == '/tmp'

    def test_glob_in_middle(self):
        assert get_glob_base_directory('/tmp/*/test.txt') == '/tmp'

    def test_relative_glob(self):
        assert get_glob_base_directory('*.py') == '.'

    def test_root_glob(self):
        assert get_glob_base_directory('/*') == '/'
