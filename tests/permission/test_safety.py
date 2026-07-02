"""Tests for SafetyGuard."""

import os
import tempfile

import pytest

from ms_agent.permission.config import SafetyConfig
from ms_agent.permission.safety import SafetyGuard


@pytest.fixture
def guard(tmp_path):
    config = SafetyConfig()
    return SafetyGuard(config=config, allowed_dirs=[str(tmp_path)])


class TestSafetyRules:
    def test_rm_rf_blocked(self, guard):
        r = guard.check(
            'code_executor---shell_executor',
            {'command': 'rm -rf /'},
        )
        assert r.action == 'deny'

    def test_mkfs_blocked(self, guard):
        r = guard.check(
            'code_executor---shell_executor',
            {'command': 'mkfs /dev/sda'},
        )
        assert r.action == 'deny'

    def test_dd_blocked(self, guard):
        r = guard.check(
            'code_executor---shell_executor',
            {'command': 'dd if=/dev/zero of=/dev/sda'},
        )
        assert r.action == 'deny'


class TestFilePathChecks:
    def test_read_within_allowed(self, guard, tmp_path):
        r = guard.check(
            'file_system---read_file',
            {'path': str(tmp_path / 'test.txt')},
        )
        assert r.action == 'allow'

    def test_write_outside_allowed(self, guard):
        r = guard.check(
            'file_system---write_file',
            {'path': '/etc/passwd'},
        )
        assert r.action == 'deny'

    def test_edit_within_allowed(self, guard, tmp_path):
        r = guard.check(
            'file_system---edit_file',
            {'path': str(tmp_path / 'test.py')},
        )
        assert r.action == 'allow'

    def test_empty_path(self, guard):
        r = guard.check('file_system---write_file', {'path': ''})
        assert r.action == 'deny'


class TestSensitivePaths:
    def test_write_git_config(self, guard):
        r = guard.check(
            'file_system---write_file',
            {'path': '.git/config'},
        )
        assert r.action == 'deny'

    def test_write_ssh_key(self, guard):
        home = os.path.expanduser('~')
        r = guard.check(
            'file_system---write_file',
            {'path': f'{home}/.ssh/id_rsa'},
        )
        assert r.action == 'deny'


class TestShellCommands:
    def test_safe_command(self, guard, tmp_path):
        r = guard.check(
            'code_executor---shell_executor',
            {'command': f'ls {tmp_path}'},
        )
        assert r.action == 'allow'

    def test_empty_command(self, guard):
        r = guard.check(
            'code_executor---shell_executor',
            {'command': ''},
        )
        assert r.action == 'deny'


class TestUnknownTool:
    def test_passthrough(self, guard):
        r = guard.check('unknown---tool', {'arg': 'value'})
        assert r.action == 'allow'


class TestCustomConfig:
    def test_custom_patterns_tool_level(self, tmp_path):
        config = SafetyConfig(
            patterns=('custom---dangerous_tool',),
        )
        guard = SafetyGuard(config=config, allowed_dirs=[str(tmp_path)])
        r = guard.check('custom---dangerous_tool', {'arg': 'value'})
        assert r.action == 'deny'

    def test_custom_patterns_shell(self, tmp_path):
        config = SafetyConfig(
            patterns=('code_executor---shell_executor:curl *',),
        )
        guard = SafetyGuard(config=config, allowed_dirs=[str(tmp_path)])
        r = guard.check(
            'code_executor---shell_executor',
            {'command': 'curl https://evil.com'},
        )
        assert r.action == 'deny'


class TestProcessSubstitution:
    """Process substitution split into input/output categories."""

    def test_input_sub_category(self, guard):
        r = guard.check(
            'code_executor---shell_executor',
            {'command': 'diff <(sort a.txt) <(sort b.txt)'},
        )
        assert r.action == 'ask'
        assert r.category == 'process_input_sub'

    def test_output_sub_category(self, guard):
        r = guard.check(
            'code_executor---shell_executor',
            {'command': 'echo secret > >(tee log.txt)'},
        )
        assert r.action == 'ask'
        assert r.category == 'process_output_sub'

    def test_output_sub_takes_precedence(self, guard):
        r = guard.check(
            'code_executor---shell_executor',
            {'command': 'cat <(echo a) > >(tee b)'},
        )
        assert r.category == 'process_output_sub'


class TestReadOnlyDirs:
    """SafetyGuard respects read_only_directories."""

    def test_read_allowed_in_read_only_dir(self, tmp_path):
        ro_dir = tmp_path / 'readonly'
        ro_dir.mkdir()
        config = SafetyConfig()
        guard = SafetyGuard(config=config, allowed_dirs=[str(tmp_path)], read_only_dirs=[str(ro_dir)])
        # ro_dir is under tmp_path anyway; use a truly separate dir
        import tempfile
        with tempfile.TemporaryDirectory() as separate_ro:
            guard2 = SafetyGuard(config=config, allowed_dirs=[str(tmp_path)], read_only_dirs=[separate_ro])
            r = guard2.check('file_system---read_file', {'path': f'{separate_ro}/data.csv'})
            assert r.action == 'allow'

    def test_write_denied_in_read_only_dir(self, tmp_path):
        import tempfile
        with tempfile.TemporaryDirectory() as separate_ro:
            config = SafetyConfig()
            guard = SafetyGuard(config=config, allowed_dirs=[str(tmp_path)], read_only_dirs=[separate_ro])
            r = guard.check('file_system---write_file', {'path': f'{separate_ro}/data.csv'})
            assert r.action == 'deny'

    def test_shell_read_in_read_only_dir(self, tmp_path):
        import tempfile
        with tempfile.TemporaryDirectory() as separate_ro:
            config = SafetyConfig()
            guard = SafetyGuard(config=config, allowed_dirs=[str(tmp_path)], read_only_dirs=[separate_ro])
            r = guard.check('code_executor---shell_executor', {'command': f'cat {separate_ro}/data.csv'})
            assert r.action == 'allow'

    def test_shell_write_in_read_only_dir(self, tmp_path):
        import tempfile
        with tempfile.TemporaryDirectory() as separate_ro:
            config = SafetyConfig()
            guard = SafetyGuard(config=config, allowed_dirs=[str(tmp_path)], read_only_dirs=[separate_ro])
            r = guard.check('code_executor---shell_executor', {'command': f'rm {separate_ro}/data.csv'})
            assert r.action == 'deny'


class TestCategoryPropagation:
    """SafetyDecision carries category from validators."""

    def test_parse_failure_category(self, guard):
        r = guard.check(
            'code_executor---shell_executor',
            {'command': "echo 'unterminated"},
        )
        assert r.action == 'ask'
        assert r.category == 'parse_failure'

    def test_shell_expansion_category(self, guard):
        r = guard.check(
            'file_system---read_file',
            {'path': '$HOME/secrets.txt'},
        )
        assert r.action == 'ask'
        assert r.category == 'shell_expansion'


class TestConfigParsing:
    """SafetyConfig.from_dict parses read_only_directories."""

    def test_read_only_directories_parsed(self, tmp_path):
        d = {'read_only_directories': [str(tmp_path / 'data')]}
        config = SafetyConfig.from_dict(d)
        assert config.read_only_directories == (str(tmp_path / 'data'),)

    def test_read_only_directories_project_root(self):
        d = {'read_only_directories': ['${PROJECT_ROOT}']}
        config = SafetyConfig.from_dict(d, project_root='/my/project')
        assert config.read_only_directories == ('/my/project',)

    def test_read_only_directories_default_empty(self):
        config = SafetyConfig.from_dict({})
        assert config.read_only_directories == ()

    def test_write_policy_removed(self):
        assert not hasattr(SafetyConfig, 'write_policy') or 'write_policy' not in SafetyConfig.__dataclass_fields__


class TestGrepGlobCoverage:
    """SafetyGuard checks grep and glob path arguments."""

    def test_grep_within_allowed(self, guard, tmp_path):
        r = guard.check('file_system---grep', {'path': str(tmp_path / 'src')})
        assert r.action == 'allow'

    def test_grep_outside_allowed(self, guard):
        r = guard.check('file_system---grep', {'path': '/etc'})
        assert r.action in ('deny', 'ask')

    def test_glob_within_allowed(self, guard, tmp_path):
        r = guard.check('file_system---glob', {'path': str(tmp_path)})
        assert r.action == 'allow'

    def test_glob_outside_allowed(self, guard):
        r = guard.check('file_system---glob', {'path': '/etc'})
        assert r.action in ('deny', 'ask')

    def test_grep_default_path(self, guard):
        r = guard.check('file_system---grep', {'pattern': 'foo'})
        assert r.action in ('allow', 'ask')

    def test_glob_default_path(self, guard):
        r = guard.check('file_system---glob', {'pattern': '*.py'})
        assert r.action in ('allow', 'ask')


class TestWorkspaceRoot:
    """SafetyGuard respects workspace_root for relative path resolution."""

    def test_relative_path_resolved_via_workspace_root(self, tmp_path):
        config = SafetyConfig()
        guard = SafetyGuard(
            config=config,
            allowed_dirs=[str(tmp_path)],
            workspace_root=str(tmp_path),
        )
        r = guard.check('file_system---read_file', {'path': 'test.txt'})
        assert r.action == 'allow'

    def test_relative_path_outside_workspace_root(self):
        config = SafetyConfig()
        guard = SafetyGuard(
            config=config,
            allowed_dirs=['/some/dir'],
            workspace_root='/some/dir',
        )
        r = guard.check('file_system---write_file', {'path': '../../etc/passwd'})
        assert r.action == 'deny'


class TestDefaultBlacklist:
    """PermissionConfig includes default network command blacklist."""

    def test_default_blacklist_contains_curl(self):
        from ms_agent.permission.config import PermissionConfig
        config = PermissionConfig()
        assert any('curl' in p for p in config.blacklist)

    def test_default_blacklist_contains_wget(self):
        from ms_agent.permission.config import PermissionConfig
        config = PermissionConfig()
        assert any('wget' in p for p in config.blacklist)

    def test_user_blacklist_merged(self):
        from ms_agent.permission.config import PermissionConfig
        config = PermissionConfig.from_dict({'blacklist': ['custom---tool']})
        assert any('curl' in p for p in config.blacklist)
        assert 'custom---tool' in config.blacklist
