import json
import pytest
from ms_agent.config.skills_manager import SkillsConfigManager


class TestSkillsConfigManager:
    @pytest.fixture
    def mgr(self, tmp_path):
        return SkillsConfigManager(global_dir=str(tmp_path))

    def test_load_global_empty(self, mgr):
        assert mgr.load_global() == {}

    def test_set_skill_disabled_persists(self, mgr):
        mgr.set_skill_enabled('skill-a', False)
        data = mgr.load_global()
        assert 'skill-a' in data['disabled']

    def test_set_skill_enabled_removes_from_disabled(self, mgr):
        mgr.set_skill_enabled('skill-a', False)
        mgr.set_skill_enabled('skill-a', True)
        data = mgr.load_global()
        assert 'skill-a' not in data.get('disabled', [])

    def test_disabled_list_sorted(self, mgr):
        mgr.set_skill_enabled('zzz', False)
        mgr.set_skill_enabled('aaa', False)
        data = mgr.load_global()
        assert data['disabled'] == ['aaa', 'zzz']

    def test_disable_idempotent(self, mgr):
        mgr.set_skill_enabled('x', False)
        mgr.set_skill_enabled('x', False)
        data = mgr.load_global()
        assert data['disabled'].count('x') == 1

    def test_add_source(self, mgr):
        mgr.add_source('/path/to/skills')
        assert mgr.list_sources() == ['/path/to/skills']

    def test_add_source_dedup(self, mgr):
        mgr.add_source('/p')
        mgr.add_source('/p')
        assert mgr.list_sources() == ['/p']

    def test_remove_source(self, mgr):
        mgr.add_source('/a')
        mgr.add_source('/b')
        mgr.remove_source('/a')
        assert mgr.list_sources() == ['/b']

    def test_remove_nonexistent_source_noop(self, mgr):
        mgr.remove_source('/ghost')
        assert mgr.list_sources() == []

    def test_project_scope(self, mgr, tmp_path):
        proj = tmp_path / 'myproject'
        proj.mkdir()
        mgr.set_skill_enabled('s1', False, scope='project', project_path=str(proj))
        mgr.add_source('/proj/skills', scope='project', project_path=str(proj))

        proj_data = mgr.load_project(str(proj))
        assert 's1' in proj_data['disabled']
        assert '/proj/skills' in proj_data['sources']

        global_data = mgr.load_global()
        assert global_data == {}

    def test_project_scope_requires_path(self, mgr):
        with pytest.raises(ValueError, match='project_path'):
            mgr.set_skill_enabled('x', False, scope='project')

    def test_load_merged(self, mgr, tmp_path):
        mgr.set_skill_enabled('g1', False)
        mgr.add_source('/global/skills')

        proj = tmp_path / 'proj'
        proj.mkdir()
        mgr.set_skill_enabled('p1', False, scope='project', project_path=str(proj))
        mgr.add_source('/proj/skills', scope='project', project_path=str(proj))

        merged = mgr.load_merged(project_path=str(proj))
        assert 'g1' in merged['disabled']
        assert 'p1' in merged['disabled']
        assert '/global/skills' in merged['sources']
        assert '/proj/skills' in merged['sources']

    def test_load_merged_global_only(self, mgr):
        mgr.add_source('/src')
        merged = mgr.load_merged()
        assert '/src' in merged['sources']

    def test_corrupt_file_returns_empty(self, mgr, tmp_path):
        path = tmp_path / 'skills.json'
        path.write_text('not json{{{')
        assert mgr.load_global() == {}
