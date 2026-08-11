"""Tests for workspace root resolution."""

import os
from types import SimpleNamespace

import pytest

from ms_agent.utils.workspace_context import WorkspaceContext, resolve_workspace_root


class TestResolveWorkspaceRoot:
    def test_defaults_to_cwd_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config = SimpleNamespace()
        assert resolve_workspace_root(config) == tmp_path.resolve()

    def test_defaults_to_cwd_when_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config = SimpleNamespace(output_dir='')
        assert resolve_workspace_root(config) == tmp_path.resolve()

    def test_expands_explicit_output_dir(self, tmp_path):
        custom = tmp_path / 'artifacts'
        config = SimpleNamespace(output_dir=str(custom))
        assert resolve_workspace_root(config) == custom.resolve()

    def test_workspace_context_uses_same_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config = SimpleNamespace(tools=SimpleNamespace(workspace_policy=None))
        ctx = WorkspaceContext.from_config(config)
        assert ctx.root == tmp_path.resolve()

    def test_permission_allowed_dirs_aligns_with_workspace_root(self, tmp_path, monkeypatch):
        """allowed_dirs[0] and SafetyGuard workspace_root must match resolve_workspace_root."""
        monkeypatch.chdir(tmp_path)
        from ms_agent.permission.config import PermissionConfig
        from ms_agent.permission.safety import SafetyGuard
        from ms_agent.utils.workspace_context import resolve_workspace_root

        config = SimpleNamespace(permission=None, tools=SimpleNamespace(workspace_policy=None))
        workspace_root = str(resolve_workspace_root(config))
        perm_config = PermissionConfig.from_dict({}, project_root=workspace_root)
        allowed_dirs = [workspace_root]
        guard = SafetyGuard(
            config=perm_config.safety,
            allowed_dirs=allowed_dirs,
            workspace_root=workspace_root,
        )
        assert allowed_dirs[0] == workspace_root
        assert guard._workspace_root == workspace_root
        assert guard._allowed_dirs[0] == workspace_root


class TestShellValidatorWorkspaceRoot:
    def test_relative_path_resolves_against_workspace_root(self, tmp_path, monkeypatch):
        workspace = tmp_path / 'workspace'
        workspace.mkdir()
        other = tmp_path / 'other'
        other.mkdir()
        (workspace / 'file.txt').write_text('hello', encoding='utf-8')

        monkeypatch.chdir(other)

        from ms_agent.permission.shell_validator import PathSafetyConfig, ShellPathValidator

        validator = ShellPathValidator(
            allowed_dirs=[str(workspace)],
            safety_config=PathSafetyConfig(workspace_root=str(workspace)),
        )
        result = validator.check('cat file.txt')
        assert result.action == 'allow'

        validator_without_root = ShellPathValidator(allowed_dirs=[str(workspace)])
        result_other = validator_without_root.check('cat file.txt')
        assert result_other.action in ('deny', 'ask')
