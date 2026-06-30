import pytest
from ms_agent.project.manager import ProjectManager
from ms_agent.project.session import SessionManager
from ms_agent.project.types import SessionStatus


class TestSessionManager:
    @pytest.fixture
    def sm(self, tmp_path):
        pm = ProjectManager(base_dir=str(tmp_path))
        project = pm.create(name='TestProject')
        return SessionManager(project)

    def test_create_returns_session(self, sm):
        session = sm.create(name='Test Session')
        assert session.id
        assert session.project_id == sm.project.id
        assert session.name == 'Test Session'
        assert session.status == SessionStatus.IDLE

    def test_create_generates_session_key(self, sm):
        session = sm.create()
        assert session.session_key.startswith('session_')
        assert session.id in session.session_key

    def test_create_persists_to_disk(self, sm):
        session = sm.create()
        meta_file = sm.sessions_dir / session.id / 'session.json'
        assert meta_file.exists()

    def test_get_returns_created_session(self, sm):
        session = sm.create(name='Lookup')
        retrieved = sm.get(session.id)
        assert retrieved is not None
        assert retrieved.name == 'Lookup'
        assert retrieved.session_key == session.session_key

    def test_get_nonexistent_returns_none(self, sm):
        assert sm.get('nonexistent') is None

    def test_list_returns_sessions(self, sm):
        sm.create(name='A')
        sm.create(name='B')
        sessions = sm.list()
        names = {s.name for s in sessions}
        assert 'A' in names
        assert 'B' in names

    def test_list_newest_first(self, sm):
        s1 = sm.create(name='First')
        s2 = sm.create(name='Second')
        sessions = sm.list()
        ids = [s.id for s in sessions]
        assert ids.index(s2.id) < ids.index(s1.id)

    def test_update_status(self, sm):
        session = sm.create()
        updated = sm.update_status(session.id, SessionStatus.RUNNING)
        assert updated.status == SessionStatus.RUNNING
        reloaded = sm.get(session.id)
        assert reloaded.status == SessionStatus.RUNNING

    def test_update_name(self, sm):
        session = sm.create()
        updated = sm.update(session.id, name='Renamed')
        assert updated.name == 'Renamed'

    def test_update_nonexistent_raises(self, sm):
        with pytest.raises(ValueError, match='not found'):
            sm.update('ghost', name='X')

    def test_delete_removes_dir(self, sm):
        session = sm.create()
        sm.delete(session.id)
        assert sm.get(session.id) is None
        assert not (sm.sessions_dir / session.id).exists()

    def test_delete_nonexistent_is_noop(self, sm):
        sm.delete('nonexistent')

    def test_session_is_frozen(self, sm):
        session = sm.create()
        with pytest.raises(AttributeError):
            session.name = 'Mutated'

    def test_list_excludes_deleted(self, sm):
        session = sm.create()
        sm.delete(session.id)
        ids = [s.id for s in sm.list()]
        assert session.id not in ids

    def test_update_status_with_string(self, sm):
        session = sm.create()
        updated = sm.update(session.id, status='running')
        assert updated.status == SessionStatus.RUNNING
