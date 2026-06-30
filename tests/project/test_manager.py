import pytest
from ms_agent.project.manager import ProjectManager
from ms_agent.project.types import DEFAULT_PROJECT_ID, Project


class TestProjectManager:
    @pytest.fixture
    def pm(self, tmp_path):
        return ProjectManager(base_dir=str(tmp_path))

    def test_default_project_exists_on_init(self, pm):
        default = pm.get_default_project()
        assert default is not None
        assert default.id == DEFAULT_PROJECT_ID
        assert default.name == 'Default'

    def test_create_and_get(self, pm):
        project = pm.create(name='Test Project')
        retrieved = pm.get(project.id)
        assert retrieved is not None
        assert retrieved.name == 'Test Project'
        assert retrieved.id == project.id

    def test_create_generates_unique_ids(self, pm):
        p1 = pm.create(name='A')
        p2 = pm.create(name='B')
        assert p1.id != p2.id

    def test_create_with_custom_path(self, pm, tmp_path):
        custom = tmp_path / 'custom_workspace'
        project = pm.create(name='Custom', path=str(custom))
        assert project.path == str(custom.resolve())

    def test_list_includes_default(self, pm):
        projects = pm.list()
        ids = [p.id for p in projects]
        assert DEFAULT_PROJECT_ID in ids

    def test_list_includes_created(self, pm):
        pm.create(name='Alpha')
        pm.create(name='Beta')
        projects = pm.list()
        names = [p.name for p in projects]
        assert 'Alpha' in names
        assert 'Beta' in names

    def test_update_returns_new_instance(self, pm):
        project = pm.create(name='Original')
        updated = pm.update(project.id, name='Updated')
        assert updated.name == 'Updated'
        assert updated.id == project.id
        assert project.name == 'Original'

    def test_update_nonexistent_raises(self, pm):
        with pytest.raises(ValueError, match='not found'):
            pm.update('nonexistent', name='X')

    def test_delete_removes_project(self, pm):
        project = pm.create(name='ToDelete')
        pm.delete(project.id)
        assert pm.get(project.id) is None

    def test_delete_default_raises(self, pm):
        with pytest.raises(ValueError, match='Cannot delete'):
            pm.delete(DEFAULT_PROJECT_ID)

    def test_delete_nonexistent_is_noop(self, pm):
        pm.delete('nonexistent')

    def test_list_excludes_deleted(self, pm):
        project = pm.create(name='Gone')
        pm.delete(project.id)
        ids = [p.id for p in pm.list()]
        assert project.id not in ids

    def test_workspace_dir_created(self, pm):
        project = pm.create(name='WithWorkspace')
        from pathlib import Path
        assert (Path(project.path) / 'workspace').is_dir()

    def test_sessions_dir_created(self, pm):
        project = pm.create(name='WithSessions')
        from pathlib import Path
        meta_dir = pm._projects_root / project.id / '.ms-agent'
        assert (meta_dir / 'sessions').is_dir()

    def test_project_is_frozen(self, pm):
        project = pm.create(name='Frozen')
        with pytest.raises(AttributeError):
            project.name = 'Mutated'
