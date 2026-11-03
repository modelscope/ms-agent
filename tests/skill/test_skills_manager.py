import json
import pytest
from ms_agent.config.skills_manager import SkillsConfigManager


class TestSkillsConfigManager:
    @pytest.fixture
    def mgr(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'ms_agent.config.skills_manager.global_standard_skills_tree',
            lambda: tmp_path / 'missing-standard-skills',
        )
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

    def test_corrupt_file_is_preserved(self, mgr, tmp_path):
        path = tmp_path / 'skills.json'
        path.write_text('not json{{{')
        with pytest.raises(ValueError, match='valid JSON'):
            mgr.load_global()
        with pytest.raises(ValueError, match='valid JSON'):
            mgr.add_source('new-source')
        assert path.read_text() == 'not json{{{'

    def test_import_from_path_copies_skill_dir(self, mgr, tmp_path):
        src = tmp_path / 'pack' / 'demo-skill'
        src.mkdir(parents=True)
        (src / 'SKILL.md').write_text('# Demo\n')
        names = mgr.import_from_path(str(src), scope='global')
        assert names == ['demo-skill']
        dest = mgr.global_skills_tree() / 'demo-skill' / 'SKILL.md'
        assert dest.is_file()
        assert dest.read_text() == '# Demo\n'

    def test_import_from_path_project_scope(self, mgr, tmp_path):
        proj = tmp_path / 'repo'
        proj.mkdir()
        src = tmp_path / 'local-skill'
        src.mkdir()
        (src / 'SKILL.md').write_text('# Local\n')
        names = mgr.import_from_path(
            str(src), scope='project', project_path=str(proj))
        assert names == ['local-skill']
        dest = mgr.project_skills_tree(str(proj)) / 'local-skill' / 'SKILL.md'
        assert dest.is_file()

    def test_remove_imported_deletes_live_tree_dir(self, mgr, tmp_path):
        src = tmp_path / 'pack' / 'demo-skill'
        src.mkdir(parents=True)
        (src / 'SKILL.md').write_text('# Demo\n')
        mgr.import_from_path(str(src), scope='global')
        mgr.set_skill_enabled('demo-skill', False)
        dest = mgr.remove_imported('demo-skill', scope='global')
        assert not dest.exists()
        assert 'demo-skill' not in mgr.load_global().get('disabled', [])

    def test_remove_imported_rejects_non_managed(self, mgr):
        with pytest.raises(FileNotFoundError, match='not a managed skill'):
            mgr.remove_imported('ghost')

    def test_import_from_path_missing_raises(self, mgr, tmp_path):
        with pytest.raises(FileNotFoundError):
            mgr.import_from_path(str(tmp_path / 'missing'))
