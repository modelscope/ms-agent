"""Security regression tests — attack vectors from design doc Section 17.3."""

import os
import tempfile

import pytest

from ms_agent.permission.config import SafetyConfig
from ms_agent.permission.safety import SafetyGuard


@pytest.fixture
def guard(tmp_path):
    config = SafetyConfig()
    return SafetyGuard(config=config, allowed_dirs=[str(tmp_path)])


class TestAttackVectors:
    def test_rm_rf_root(self, guard):
        """rm -rf / → deny (dangerous path)"""
        r = guard.check('code_executor---shell_executor', {'command': 'rm -rf /'})
        assert r.action == 'deny'

    def test_timeout_rm_rf_root(self, guard):
        """timeout 10 rm -rf / → deny (wrapper stripped, then dangerous path)"""
        r = guard.check('code_executor---shell_executor', {'command': 'timeout 10 rm -rf /'})
        assert r.action == 'deny'

    def test_rm_double_dash_tricky(self, guard):
        """rm -- -/../.claude/settings.json → deny (path outside allowed dirs)"""
        r = guard.check(
            'code_executor---shell_executor',
            {'command': 'rm -- -/../.claude/settings.json'},
        )
        assert r.action in ('deny', 'ask')

    def test_redirect_to_etc(self, guard):
        """echo "x" > /etc/passwd → ask/deny (redirect to sensitive path)"""
        r = guard.check(
            'code_executor---shell_executor',
            {'command': 'echo "x" > /etc/passwd'},
        )
        assert r.action in ('deny', 'ask')

    def test_cd_plus_mv(self, guard, tmp_path):
        """cd dir && mv a b → ask (cd + write compound)"""
        r = guard.check(
            'code_executor---shell_executor',
            {'command': f'cd {tmp_path} && mv {tmp_path}/a {tmp_path}/b'},
        )
        assert r.action == 'ask'

    def test_rm_dollar_home(self, guard):
        """rm $HOME/.ssh/* → ask/deny (shell expansion in path)"""
        r = guard.check(
            'code_executor---shell_executor',
            {'command': 'rm $HOME/.ssh/*'},
        )
        assert r.action in ('deny', 'ask')

    def test_env_home_override(self, guard):
        """env HOME=/tmp rm -rf ~ → HOME is unsafe, not stripped"""
        r = guard.check(
            'code_executor---shell_executor',
            {'command': 'env HOME=/tmp rm -rf ~'},
        )
        assert r.action == 'deny'

    def test_process_substitution(self, guard):
        """echo secret > >(tee .git/config) → ask (process substitution)"""
        r = guard.check(
            'code_executor---shell_executor',
            {'command': 'echo secret > >(tee .git/config)'},
        )
        assert r.action == 'ask'

    def test_mv_target_directory(self, guard, tmp_path):
        """mv --target-directory=/etc test.txt → ask (command validator)"""
        r = guard.check(
            'code_executor---shell_executor',
            {'command': f'mv --target-directory=/etc {tmp_path}/test.txt'},
        )
        assert r.action == 'ask'

    def test_sed_write_expression(self, guard, tmp_path):
        """sed -e 's/x/y/w /etc/passwd' file → deny (sed expression safety)"""
        r = guard.check(
            'code_executor---shell_executor',
            {'command': f"sed -e 's/x/y/w /etc/passwd' {tmp_path}/file"},
        )
        assert r.action == 'deny'


class TestSensitivePathWrites:
    def test_write_etc(self, guard):
        r = guard.check('file_system---write_file', {'path': '/etc/hosts'})
        assert r.action == 'deny'

    def test_write_ssh(self, guard):
        home = os.path.expanduser('~')
        r = guard.check('file_system---write_file', {'path': f'{home}/.ssh/authorized_keys'})
        assert r.action == 'deny'

    def test_write_git_hooks(self, guard):
        r = guard.check('file_system---write_file', {'path': '.git/hooks/pre-commit'})
        assert r.action == 'deny'

    def test_write_bashrc(self, guard):
        home = os.path.expanduser('~')
        r = guard.check('file_system---write_file', {'path': f'{home}/.bashrc'})
        assert r.action == 'deny'
