"""Cooperating writers preserve data, including across independent processes."""
import json
import multiprocessing
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from ms_agent.config.model_settings import ModelSettingsManager
from ms_agent.config.mcp_manager import MCPConfigManager
from ms_agent.personalization import PersonalizationSettings
from ms_agent.project import ProjectManager
from ms_agent.utils.file_lock import file_lock
from ms_agent.utils.json_store import json_transaction, read_json


@pytest.fixture
def spawn():
    children = []

    def start(target, *args):
        child = multiprocessing.get_context('spawn').Process(target=target, args=args)
        child.start()
        children.append(child)
        return child

    yield start
    for child in children:
        if child.is_alive():
            child.terminate()
        child.join(5)
        if child.is_alive():
            child.kill()
            child.join(5)
        child.close()


def _write_models(home, start, count, barrier):
    manager = ModelSettingsManager(home)
    barrier.wait(timeout=10)
    for index in range(start, start + count):
        manager.add_model('provider', f'model-{index}')


def _hold_lock(resource, ready, finish):
    with file_lock(resource):
        ready.set()
        finish.wait()


@pytest.mark.parametrize('writers', ['threads', 'processes'])
def test_concurrent_model_updates_preserve_every_model(tmp_path, spawn, writers):
    home = str(tmp_path)
    if writers == 'threads':
        barrier = Barrier(4)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: _write_models(home, i * 10, 10, barrier), range(4)))
    else:
        barrier = multiprocessing.get_context('spawn').Barrier(4)
        processes = [spawn(_write_models, home, i * 10, 10, barrier) for i in range(4)]
        for process in processes:
            process.join(20)
            assert process.exitcode == 0
    models = ModelSettingsManager(home).list_custom_providers()['provider']['models']
    assert set(models) == {f'model-{i}' for i in range(40)}


def test_shared_settings_writers_merge_independent_fields(tmp_path):
    with json_transaction(tmp_path / 'settings.json') as data:
        data['unknown'] = {'preserve': True}
    barrier = Barrier(12, timeout=5)

    def change(index):
        barrier.wait()
        if index % 3 == 0:
            ModelSettingsManager(tmp_path).add_model('provider', str(index))
        elif index % 3 == 1:
            PersonalizationSettings(str(tmp_path)).update(memory_enabled=True)
        else:
            MCPConfigManager(tmp_path).add(str(index), {'command': 'echo'}, scope='global')
    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(change, range(12)))
    data = read_json(tmp_path / 'settings.json')
    assert data['unknown'] == {'preserve': True}
    assert data['personalization']['memory_enabled'] is True
    assert set(data['providers']['provider']['models']) == {str(i) for i in range(0, 12, 3)}
    assert set(data['mcp_servers']) == {str(i) for i in range(2, 12, 3)}
    assert read_json(tmp_path / 'mcp.json')['mcpServers'] == data['mcp_servers']


def test_lock_reentry_timeout_and_process_exit(tmp_path, spawn):
    resource = tmp_path / 'settings.json'
    with file_lock(resource):
        with file_lock(resource):
            pass
    ctx = multiprocessing.get_context('spawn')
    ready = ctx.Event()
    finish = ctx.Event()
    child = spawn(_hold_lock, str(resource), ready, finish)
    try:
        assert ready.wait(10)
        with pytest.raises(TimeoutError):
            with file_lock(resource, timeout=0.05):
                pass
    finally:
        child.terminate()
        child.join(5)
    assert not child.is_alive()
    with file_lock(resource, timeout=1):
        pass


@pytest.mark.parametrize('content', ['not json', '[]', 'null', '"secret text"'])
def test_invalid_settings_never_become_empty(tmp_path, content):
    path = tmp_path / 'settings.json'
    path.write_text(content)
    for operation in (lambda: ModelSettingsManager(tmp_path).add_model('p', 'm'),
                      lambda: PersonalizationSettings(str(tmp_path)).update(memory_enabled=True),
                      lambda: MCPConfigManager(tmp_path).add('x', {'command': 'echo'}, scope='global')):
        with pytest.raises(ValueError):
            operation()
        assert path.read_text() == content


def test_transaction_aborts_without_touching_original(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text('{"original": true}')
    before = path.stat().st_mtime_ns
    with pytest.raises(RuntimeError):
        with json_transaction(path) as data:
            data['original'] = False
            raise RuntimeError('abort')
    assert path.read_text() == '{"original": true}'
    assert path.stat().st_mtime_ns == before
    with json_transaction(path):
        pass
    assert path.stat().st_mtime_ns == before


def test_explicit_initialization_queries_and_missing_metadata(tmp_path):
    manager = ProjectManager(str(tmp_path), auto_initialize=False)
    assert manager.list() == []
    assert not list(tmp_path.iterdir())
    manager.initialize()
    project = manager.get_default_project()
    sessions = manager.session_manager(project, auto_initialize=False)

    def snapshot():
        return {p: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in tmp_path.rglob('*') if p.is_file()}

    before = snapshot()
    manager.list()
    sessions.list()
    assert snapshot() == before
    metadata = tmp_path / 'projects' / project.id / '.ms_agent' / 'project.json'
    metadata.unlink()
    with pytest.raises(ValueError, match='missing'):
        manager.initialize()
    assert not metadata.exists()


def test_explicit_home_and_conditional_title_do_not_resurrect(tmp_path, monkeypatch):
    other = tmp_path / 'other'
    monkeypatch.setenv('MS_AGENT_HOME', str(other))
    manager = ProjectManager(str(tmp_path / 'home'))
    project = manager.create('Project')
    sm = manager.session_manager(project)
    session = sm.create(model='M1', model_provider='P1')
    sm.update(session.id, name='User title')
    saved = sm.update_if(session.id, expected={'name': session.name}, name='Late title')
    assert saved.name == 'User title'
    assert not other.exists()
    manager.delete(project.id)
    assert sm.update_if(session.id, expected={'name': 'User title'}, name='Late') is None
    with pytest.raises(ValueError):
        sm.update(session.id, name='Late')
    with pytest.raises(ValueError):
        sm.create()
    assert not (manager.base_dir / 'projects' / project.id).exists()


def test_open_folder_and_partial_project_changes(tmp_path):
    manager = ProjectManager(str(tmp_path / 'home'))
    barrier = Barrier(8, timeout=5)

    def open_together(_):
        barrier.wait()
        return manager.open_folder(str(tmp_path / 'workspace'))

    with ThreadPoolExecutor(max_workers=8) as pool:
        projects = list(pool.map(open_together, range(8)))
    assert len({p.id for p in projects}) == 1
    assert len({p.created_at for p in projects}) == 1
    project = projects[0]
    metadata = manager._meta_store(project.id)
    data = metadata.read()
    data['future_field'] = 42
    metadata.write(data)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(manager.update, project.id, name='Changed'),
                   pool.submit(manager.update, project.id, memory_enabled=True)]
        for future in futures:
            future.result()
    saved = manager.get(project.id)
    assert saved.name == 'Changed' and saved.memory_enabled
    assert manager._meta_store(project.id).read()['future_field'] == 42


def _initialize_home(home, barrier):
    manager = ProjectManager(home, auto_initialize=False)
    barrier.wait(timeout=10)
    manager.initialize()


def test_multiple_processes_initialize_once(tmp_path, spawn):
    barrier = multiprocessing.get_context('spawn').Barrier(4)
    children = [spawn(_initialize_home, str(tmp_path), barrier) for _ in range(4)]
    for child in children:
        child.join(20)
        assert child.exitcode == 0
    manager = ProjectManager(str(tmp_path), auto_initialize=False)
    assert len(manager.list()) == 1
    project = manager.get_default_project()
    manager.update(project.id, name='User default')
    manager.initialize()
    assert manager.get_default_project().name == 'User default'


def test_legacy_session_copy_resumes_and_never_overwrites(tmp_path, monkeypatch):
    manager = ProjectManager(str(tmp_path / 'home'))
    project = manager.open_folder(str(tmp_path / 'workspace'))
    legacy = Path(project.path) / '.ms-agent/sessions/old'
    legacy.mkdir(parents=True)
    (legacy / 'session.json').write_text(json.dumps({'id': 'old', 'project_id': project.id, 'name': 'History'}))
    (legacy / 'history.jsonl').write_text('{"role":"user","content":"keep"}\n')
    sm = manager.session_manager(project, auto_initialize=False)
    copy = shutil.copyfile
    attempts = []

    def fail_once(src, dst):
        attempts.append(src)
        if len(attempts) == 2:
            raise OSError('injected interruption')
        return copy(src, dst)

    with monkeypatch.context() as patch:
        patch.setattr(shutil, 'copyfile', fail_once)
        with pytest.raises(OSError, match='injected interruption'):
            sm.initialize()
    assert not sm._migration_marker.exists()
    assert not list(sm.sessions_dir.rglob('.migration-*'))
    sm.initialize()
    assert sm.get('old').name == 'History'
    assert (sm.sessions_dir / 'old/history.jsonl').read_bytes() == (legacy / 'history.jsonl').read_bytes()
    sm.delete('old')
    sm.initialize()
    assert sm.get('old') is None  # the retained legacy copy must not revive it


def test_conflicting_migration_preserves_both_originals(tmp_path):
    manager = ProjectManager(str(tmp_path / 'home'))
    project = manager.open_folder(str(tmp_path / 'workspace'))
    sm = manager.session_manager(project, auto_initialize=False)
    source = Path(project.path) / '.ms-agent/sessions/old/session.json'
    target = sm.sessions_dir / 'old/session.json'
    for path, name in ((source, 'legacy'), (target, 'current')):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'id': 'old', 'project_id': project.id, 'name': name}))
    with pytest.raises(ValueError, match='Conflicting'):
        sm.initialize()
    assert json.loads(target.read_text())['name'] == 'current'
    assert json.loads(source.read_text())['name'] == 'legacy'
    assert not sm._migration_marker.exists()


def test_unreadable_settings_are_not_replaced(tmp_path, monkeypatch):
    path = tmp_path / 'settings.json'
    path.write_text('{"preserve":true}')
    original_open = Path.open

    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError('denied')
        return original_open(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, 'open', denied)
        with pytest.raises(PermissionError):
            ModelSettingsManager(tmp_path).add_model('p', 'm')
    assert path.read_text() == '{"preserve":true}'


def test_session_corruption_is_reported_and_preserved(tmp_path):
    manager = ProjectManager(str(tmp_path))
    sessions = manager.session_manager(manager.get_default_project())
    session = sessions.create()
    path = sessions.sessions_dir / session.id / 'session.json'
    path.write_text('{broken session')
    with pytest.raises(ValueError, match='valid JSON'):
        sessions.list()
    with pytest.raises(ValueError, match='valid JSON'):
        sessions.update(session.id, name='do not replace')
    assert path.read_text() == '{broken session'
