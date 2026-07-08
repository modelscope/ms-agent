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
        assert (pm._projects_root / project.id / 'sessions').is_dir()

    def test_project_is_frozen(self, pm):
        project = pm.create(name='Frozen')
        with pytest.raises(AttributeError):
            project.name = 'Mutated'

    def test_create_init_workspace_false_skips_workspace(self, pm, tmp_path):
        from pathlib import Path
        custom = tmp_path / 'no_ws'
        project = pm.create(
            name='NoWs', path=str(custom), init_workspace=False)
        assert not (Path(project.path) / 'workspace').exists()

    # -- open_folder (Codex "use an existing folder") --

    def test_open_folder_id_is_path_key(self, pm, tmp_path):
        from ms_agent.project.paths import project_key
        folder = tmp_path / 'my-repo'
        folder.mkdir()
        project = pm.open_folder(str(folder))
        assert project.id == project_key(str(folder))
        assert project.path == str(folder.resolve())
        assert project.name == 'my-repo'  # defaults to the folder basename

    def test_open_folder_does_not_create_workspace(self, pm, tmp_path):
        from pathlib import Path
        folder = tmp_path / 'existing-repo'
        folder.mkdir()
        pm.open_folder(str(folder))
        # The existing folder must stay clean — no injected workspace/.
        assert not (Path(folder) / 'workspace').exists()

    def test_open_folder_dedups_same_path(self, pm, tmp_path):
        folder = tmp_path / 'repo'
        folder.mkdir()
        p1 = pm.open_folder(str(folder), name='First')
        p2 = pm.open_folder(str(folder), name='Second')
        assert p1.id == p2.id
        # Reopening returns the existing project, not a duplicate.
        assert p2.name == 'First'
        matching = [p for p in pm.list() if p.path == str(folder.resolve())]
        assert len(matching) == 1

    def test_open_folder_appears_in_list(self, pm, tmp_path):
        folder = tmp_path / 'listed-repo'
        folder.mkdir()
        project = pm.open_folder(str(folder))
        assert project.id in [p.id for p in pm.list()]

    def test_open_folder_roundtrips_via_get(self, pm, tmp_path):
        folder = tmp_path / 'gettable'
        folder.mkdir()
        project = pm.open_folder(str(folder), instruction='be terse')
        again = pm.get(project.id)
        assert again is not None
        assert again.path == project.path
        assert again.instruction == 'be terse'
