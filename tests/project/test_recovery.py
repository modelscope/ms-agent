"""Explicit recovery preserves existing data and refuses unsafe replacements."""
import json
import shutil
from concurrent.futures import ThreadPoolExecutor

import pytest

from ms_agent.project import ProjectManager
from ms_agent.project.manager import DefaultProjectMissingError


@pytest.fixture
def lost_project(tmp_path):
    manager = ProjectManager(str(tmp_path / 'home'))
    project = manager.get_default_project()
    sessions = manager.session_manager(project)
    session = sessions.create(name='Keep this conversation', model='M1', model_provider='P1')
    (sessions.sessions_dir / session.id / 'history.jsonl').write_text('{"content":"keep"}\n')
    (manager.base_dir / 'settings.json').write_text('{"custom":"keep"}')
    (manager.base_dir / 'projects/_default/report.txt').write_text('Keep this file')
    manager._meta_file(project.id).unlink()
    return manager, sessions, session


def test_recovery_backs_up_and_preserves_sessions_and_global_settings(lost_project):
    manager, sessions, session = lost_project
    root = manager.base_dir
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    with pytest.raises(DefaultProjectMissingError, match='metadata is missing'):
        manager.initialize()
    backup = manager.repair_default_project()
    assert backup.parent == root / 'backups'
    for relative, content in before.items():
        assert (root / relative).read_bytes() == content
        if relative.parts[:2] == ('projects', '_default'):
            assert (backup / relative).read_bytes() == content
    assert manager.get_default_project().memory_enabled is False
    assert sessions.get(session.id) == session
    assert manager.repair_default_project() is None
    assert len(list((root / 'backups').iterdir())) == 1


@pytest.mark.parametrize('content', ['not json', '{}', '[]', '{"name":"incomplete"}'])
def test_recovery_never_replaces_existing_invalid_metadata(lost_project, content):
    manager, _, _ = lost_project
    metadata = manager._meta_file('_default')
    metadata.write_text(content)
    with pytest.raises(ValueError):
        manager.repair_default_project()
    assert metadata.read_text() == content
    assert not (manager.base_dir / 'backups').exists()


def test_backup_failure_keeps_missing_record_and_all_source_files(lost_project, monkeypatch):
    manager, sessions, session = lost_project

    def fail(*args, **kwargs):
        raise OSError('Disk full')

    monkeypatch.setattr(shutil, 'copy2', fail)
    with pytest.raises(OSError, match='Backup failed'):
        manager.repair_default_project()
    assert not manager._meta_file('_default').exists()
    assert sessions.get(session.id) == session
    assert json.loads((manager.base_dir / 'settings.json').read_text()) == {'custom': 'keep'}


def test_concurrent_repairs_only_create_one_backup(lost_project):
    manager, sessions, session = lost_project
    other = ProjectManager(str(manager.base_dir), auto_initialize=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda m: m.repair_default_project(), [manager, other]))
    assert sum(result is not None for result in results) == 1
    assert len(list((manager.base_dir / 'backups').iterdir())) == 1
    assert sessions.get(session.id) == session
