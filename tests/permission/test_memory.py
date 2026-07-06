"""Tests for PermissionMemory."""

import json
import tempfile
from pathlib import Path

import pytest

from ms_agent.permission.memory import PermissionMemory


@pytest.fixture
def memory(tmp_path):
    project_path = tmp_path / 'project'
    project_path.mkdir()
    global_path = tmp_path / 'global' / 'permission_memory.json'
    return PermissionMemory(project_path=project_path, global_path=global_path)


class TestAdd:
    def test_add_project(self, memory, tmp_path):
        memory.add('file_system---read_*', scope='project')
        entries = memory.list_all()
        assert len(entries) == 1
        assert entries[0].pattern == 'file_system---read_*'
        assert entries[0].scope == 'project'

    def test_add_global(self, memory):
        memory.add('web_search---*', scope='global')
        entries = memory.list_all()
        assert len(entries) == 1
        assert entries[0].scope == 'global'


class TestMatches:
    def test_match_persistent(self, memory):
        memory.add('file_system---read_*', scope='project')
        assert memory.matches('file_system---read_file', {})
        assert not memory.matches('file_system---write_file', {})

    def test_match_session(self, memory):
        memory.add_session('code_executor---shell_executor:ls *')
        assert memory.matches('code_executor---shell_executor', {'command': 'ls -la'})
        assert not memory.matches('code_executor---shell_executor', {'command': 'rm file'})

    def test_match_content_pattern(self, memory):
        memory.add('code_executor---shell_executor:pip *', scope='project')
        assert memory.matches('code_executor---shell_executor', {'command': 'pip install requests'})
        assert not memory.matches('code_executor---shell_executor', {'command': 'npm install'})


class TestRevoke:
    def test_revoke(self, memory):
        memory.add('file_system---*', scope='project')
        assert memory.matches('file_system---read_file', {})
        count = memory.revoke('file_system---*')
        assert count == 1
        assert not memory.matches('file_system---read_file', {})

    def test_revoke_nonexistent(self, memory):
        count = memory.revoke('nonexistent')
        assert count == 0


class TestPersistence:
    def test_reload(self, tmp_path):
        project_path = tmp_path / 'project'
        project_path.mkdir()
        global_path = tmp_path / 'global' / 'permission_memory.json'

        mem1 = PermissionMemory(project_path=project_path, global_path=global_path)
        mem1.add('file_system---*', scope='project')
        mem1.add('web_search---*', scope='global')

        mem2 = PermissionMemory(project_path=project_path, global_path=global_path)
        assert mem2.matches('file_system---read_file', {})
        assert mem2.matches('web_search---fetch_page', {})

    def test_session_not_persisted(self, tmp_path):
        project_path = tmp_path / 'project'
        project_path.mkdir()

        mem1 = PermissionMemory(project_path=project_path)
        mem1.add_session('temp_pattern')

        mem2 = PermissionMemory(project_path=project_path)
        assert not mem2.matches('temp_pattern', {})


class TestEdgeCases:
    def test_no_project_path(self, tmp_path):
        global_path = tmp_path / 'global' / 'permission_memory.json'
        mem = PermissionMemory(project_path=None, global_path=global_path)
        mem.add('test', scope='global')
        assert mem.matches('test', {})

    def test_corrupt_file(self, tmp_path):
        project_path = tmp_path / 'project'
        project_path.mkdir()
        mem_file = project_path / '.ms_agent' / 'permission_memory.json'
        mem_file.parent.mkdir(parents=True)
        mem_file.write_text('not json')

        mem = PermissionMemory(project_path=project_path)
        assert mem.list_all() == []
