# Copyright (c) ModelScope Contributors. All rights reserved.
"""Tests for WorkspacePolicyKernel."""

import tempfile
from pathlib import Path

import pytest

from ms_agent.utils.workspace_policy import WorkspacePolicyError, WorkspacePolicyKernel


def test_default_root_is_output_dir():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / 'out'
        out.mkdir()
        k = WorkspacePolicyKernel(out)
        p = k.resolve_under_roots('foo/bar')
        assert p == (out / 'foo' / 'bar').resolve()


def test_rejects_escape():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / 'out'
        out.mkdir()
        k = WorkspacePolicyKernel(out)
        with pytest.raises(WorkspacePolicyError):
            k.resolve_under_roots('../../etc/passwd')


def test_extra_allow_root():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / 'out'
        other = Path(td) / 'other'
        out.mkdir()
        other.mkdir()
        k = WorkspacePolicyKernel(out, extra_allow_roots=[str(other)])
        assert k.resolve_under_roots(str(other / 'x')) == (other / 'x').resolve()


def test_read_only_blocks_redirect():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / 'out'
        out.mkdir()
        k = WorkspacePolicyKernel(
            out,
            shell_default_mode='read_only',
        )
        with pytest.raises(WorkspacePolicyError):
            k.assert_shell_command_allowed('echo x > file.txt')


def test_workspace_write_allows_redirect_but_blocks_network():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / 'out'
        out.mkdir()
        k = WorkspacePolicyKernel(
            out,
            shell_default_mode='workspace_write',
            shell_network_enabled=False,
        )
        k.assert_shell_command_allowed('echo x > file.txt')
        with pytest.raises(WorkspacePolicyError):
            k.assert_shell_command_allowed('curl https://example.com')


def test_artifact_manager_spill(tmp_path):
    from ms_agent.utils.artifact_manager import ArtifactManager

    am = ArtifactManager(tmp_path, max_combined_bytes=32)
    big = 'a' * 100
    packed = am.pack_text_result(
        tool_name='t',
        call_id='c1',
        stdout=big,
        stderr='',
    )
    assert packed.get('truncated') is True
    assert 'artifact_path' in packed
