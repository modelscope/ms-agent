"""Tests for ShellPathValidator pipeline."""

import os
import tempfile

import pytest

from ms_agent.permission.shell_validator import ShellPathValidator


@pytest.fixture
def validator(tmp_path):
    return ShellPathValidator(allowed_dirs=[str(tmp_path)])


class TestBasicCommands:
    def test_ls_allowed(self, validator, tmp_path):
        r = validator.check(f'ls {tmp_path}')
        assert r.action == 'allow'

    def test_cat_allowed(self, validator, tmp_path):
        r = validator.check(f'cat {tmp_path}/test.txt')
        assert r.action == 'allow'

    def test_empty_command(self, validator):
        r = validator.check('')
        assert r.action == 'deny'

    def test_long_command(self, validator):
        r = validator.check('a' * 9000)
        assert r.action == 'deny'


class TestDangerousCommands:
    def test_rm_rf_root(self, validator):
        r = validator.check('rm -rf /')
        assert r.action == 'deny'

    def test_rm_star(self, validator):
        r = validator.check('rm *')
        assert r.action == 'deny'

    def test_rm_within_allowed(self, validator, tmp_path):
        r = validator.check(f'rm {tmp_path}/test.txt')
        assert r.action == 'allow'


class TestWrapperStripping:
    def test_timeout_rm(self, validator):
        r = validator.check('timeout 10 rm -rf /')
        assert r.action == 'deny'

    def test_nice_rm(self, validator):
        r = validator.check('nice -10 rm -rf /')
        assert r.action == 'deny'

    def test_nohup_rm(self, validator):
        r = validator.check('nohup rm -rf /')
        assert r.action == 'deny'


class TestCompoundCommands:
    def test_cd_plus_write(self, validator, tmp_path):
        r = validator.check(f'cd {tmp_path} && rm {tmp_path}/test.txt')
        assert r.action == 'ask'

    def test_multiple_safe(self, validator, tmp_path):
        r = validator.check(f'ls {tmp_path} && cat {tmp_path}/f')
        assert r.action == 'allow'


class TestRedirects:
    def test_redirect_within_allowed(self, validator, tmp_path):
        r = validator.check(f'echo hello > {tmp_path}/out.txt')
        assert r.action == 'allow'

    def test_redirect_to_dev_null(self, validator):
        r = validator.check('echo hello > /dev/null')
        assert r.action == 'allow'

    def test_redirect_with_variable(self, validator):
        r = validator.check('echo hello > $HOME/file')
        assert r.action == 'deny'


class TestProcessSubstitution:
    def test_output_substitution(self, validator):
        r = validator.check('echo secret > >(tee .git/config)')
        assert r.action == 'ask'

    def test_input_substitution(self, validator):
        r = validator.check('diff <(cat a) <(cat b)')
        assert r.action == 'ask'


class TestPathOutsideAllowed:
    def test_write_outside(self, validator):
        r = validator.check('touch /etc/test')
        assert r.action in ('deny', 'ask')

    def test_read_outside(self, validator):
        r = validator.check('cat /etc/passwd')
        assert r.action == 'ask'


class TestShellExpansion:
    def test_variable_in_path(self, validator):
        r = validator.check('rm $HOME/.ssh/key')
        assert r.action in ('deny', 'ask')

    def test_env_var_rm(self, validator):
        r = validator.check('rm ${TMPDIR}/file')
        assert r.action in ('deny', 'ask')


class TestMvCpValidator:
    def test_mv_with_flags(self, validator, tmp_path):
        r = validator.check(f'mv -t /dst {tmp_path}/file')
        assert r.action == 'ask'

    def test_mv_simple(self, validator, tmp_path):
        r = validator.check(f'mv {tmp_path}/a {tmp_path}/b')
        assert r.action == 'allow'


class TestUnregisteredCommand:
    def test_unknown_passthrough(self, validator):
        r = validator.check('someunknowncommand arg1 arg2')
        assert r.action == 'allow'
