"""Tests for ShellPathValidator pipeline."""

import os
import tempfile

import pytest

from ms_agent.permission.shell_validator import (PathSafetyConfig,
                                                 ShellPathValidator)


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
        assert r.action == 'allow'  # cd target resolved, paths validated against resolved cwd

    def test_multiple_safe(self, validator, tmp_path):
        r = validator.check(f'ls {tmp_path} && cat {tmp_path}/f')
        assert r.action == 'allow'

    def test_newline_separator(self, validator):
        r = validator.check('true\nrm -rf /')
        assert r.action == 'deny'

    def test_background_ampersand(self, validator):
        r = validator.check('true & rm -rf /')
        assert r.action == 'deny'

    def test_newline_inside_single_quotes(self, validator):
        r = validator.check("echo 'line1\nrm -rf /'")
        assert r.action == 'allow'

    def test_ampersand_inside_double_quotes(self, validator):
        r = validator.check('echo "foo & bar"')
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


class TestRedirectCwdTracking:
    """Relative redirect targets must resolve against the cd-tracked cwd.

    The shell resolves ``>`` targets against the current working directory,
    so a compound command like ``cd sub && echo x > ../f`` writes to
    ``<cwd>/sub/../f``. Validating the target against the workspace root
    instead disagrees with what actually happens on disk in both directions.
    """

    @pytest.fixture
    def layout(self, tmp_path):
        work = tmp_path / 'a' / 'b' / 'work'
        work2 = tmp_path / 'a' / 'b' / 'work2'
        cache = tmp_path / 'cache'
        for p in (work / 'sub', work2, cache):
            p.mkdir(parents=True)
        allowed = (str(work), str(work2), str(cache))
        validator = ShellPathValidator(
            allowed_dirs=list(allowed),
            safety_config=PathSafetyConfig(
                allowed_directories=allowed, workspace_root=str(work)),
        )
        return validator, work, work2, cache

    def test_relative_redirect_after_cd_into_subdir(self, layout):
        """``cd work/sub && echo x > ../f`` writes work/f — inside allowed."""
        validator, work, _, _ = layout
        r = validator.check(f'cd {work}/sub && echo x > ../f')
        assert r.action == 'allow'

    def test_relative_redirect_escaping_after_cd(self, layout):
        """``cd cache && echo x > ../work2/f`` writes outside allowed dirs.

        Resolved against the workspace root the target would look like
        ``work/../work2/f`` (an allowed directory), but the shell writes to
        ``cache/../work2/f``, which is not allowed.
        """
        validator, _, _, cache = layout
        r = validator.check(f'cd {cache} && echo x > ../work2/f')
        assert r.action != 'allow'

    def test_redirect_without_cd_uses_workspace_root(self, layout):
        validator, _, _, _ = layout
        r = validator.check('echo x > f')
        assert r.action == 'allow'

    def test_redirect_matches_argument_path_validation(self, layout):
        """Redirects and ordinary path arguments must agree on the cwd."""
        validator, work, _, _ = layout
        rm = validator.check(f'cd {work}/sub && rm ../f')
        redirect = validator.check(f'cd {work}/sub && echo x > ../f')
        assert rm.action == redirect.action == 'allow'


class TestProcessSubstitution:
    def test_output_substitution(self, validator):
        r = validator.check('echo secret > >(tee .git/config)')
        assert r.action == 'ask'

    def test_input_substitution(self, validator):
        r = validator.check('diff <(cat a) <(cat b)')
        assert r.action == 'ask'


class TestCommandSubstitution:
    def test_dollar_paren_rm(self, validator):
        r = validator.check('echo $(rm -rf /)')
        assert r.action == 'deny'

    def test_backtick_rm(self, validator):
        r = validator.check('echo `rm -rf /`')
        assert r.action == 'deny'

    def test_dollar_paren_in_double_quotes(self, validator):
        r = validator.check('echo "$(rm -rf /)"')
        assert r.action == 'deny'

    def test_dollar_paren_safe_allowed(self, validator, tmp_path):
        r = validator.check(f'echo $(ls {tmp_path})')
        assert r.action == 'allow'

    def test_single_quoted_literal_allowed(self, validator):
        r = validator.check("echo '$(rm -rf /)'")
        assert r.action == 'allow'

    def test_nested_substitution(self, validator):
        r = validator.check('echo $(echo $(rm -rf /))')
        assert r.action == 'deny'

    def test_parameter_expansion_with_substitution(self, validator):
        r = validator.check('echo ${UNUSED:-$(rm -rf /)}')
        assert r.action == 'deny'


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


class TestFindValidator:
    def test_exec_rm_deny(self, validator):
        r = validator.check('find . -exec rm -rf /etc/important {} ;')
        assert r.action == 'deny'

    def test_delete_outside_allowed(self, validator):
        r = validator.check('find /etc -name hosts -delete')
        assert r.action in ('deny', 'ask')

    def test_safe_find_allowed(self, validator, tmp_path):
        r = validator.check(f'find {tmp_path} -name "*.txt"')
        assert r.action == 'allow'


class TestUnregisteredCommand:
    def test_unknown_passthrough(self, validator):
        r = validator.check('someunknowncommand arg1 arg2')
        assert r.action == 'allow'
