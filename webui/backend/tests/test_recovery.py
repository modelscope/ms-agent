"""A lost default project can be recovered through the running WebUI API."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.core.settings import settings
from ms_agent.project import ProjectManager


@pytest.fixture
def lost_home(tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path))
    monkeypatch.setattr(settings, 'ms_agent_llm_model', '')
    from app.main import create_app
    with TestClient(create_app()) as client:
        result = client.post('/api/sessions', json={'title': 'Recovery history'})
        assert result.status_code == 201
        session = result.json()['data']
    manager = ProjectManager(str(tmp_path), auto_initialize=False)
    manager._meta_file('_default').unlink()
    return tmp_path, session


def test_recovery_requires_confirmation_then_restores_normal_apis(lost_home):
    from app.main import create_app
    home, session = lost_home
    record = home / 'projects/_default/.ms_agent/project.json'
    with TestClient(create_app()) as client:
        assert client.get('/api/health').json() == {'status': 'ok', 'mode': 'recovery'}
        assert client.get('/api/recovery').json()['data']['required'] is True
        assert client.get('/api/projects').status_code == 503
        assert client.post('/api/sessions', json={'title': 'Must not create'}).status_code == 503
        assert client.post('/api/recovery/default-project', json={'confirm': False}).status_code == 422
        assert client.post('/api/recovery/default-project', json={}).status_code == 422
        assert not record.exists()
        assert not (home / 'backups').exists()
        result = client.post('/api/recovery/default-project', json={'confirm': True}).json()['data']
        assert result['required'] is False
        assert result['backup_path']
        assert client.get('/api/health').json() == {'status': 'ok'}
        assert client.get(f"/api/sessions/{session['id']}").json()['data']['title'] == session['title']
        assert client.post('/api/sessions', json={'title': 'After recovery'}).status_code == 201
        assert client.post('/api/recovery/default-project', json={'confirm': True}).json()['data'] == result
        assert len(list((home / 'backups').iterdir())) == 1


@pytest.mark.parametrize('failure', ['backup', 'startup'])
def test_recovery_failure_stays_paused_and_can_retry(lost_home, monkeypatch, failure):
    from app.main import create_app
    from app.backends.ms_agent import bootstrap
    home, _ = lost_home
    with TestClient(create_app()) as client:
        def fail(*args, **kwargs):
            raise OSError('Injected failure')

        with monkeypatch.context() as patch:
            if failure == 'backup':
                patch.setattr(ProjectManager, 'repair_default_project', fail)
            else:
                patch.setattr(bootstrap, 'bootstrap', fail)
            result = client.post('/api/recovery/default-project', json={'confirm': True}).json()['data']
        assert result['required'] is True
        assert result['error'] == ('backup_failed' if failure == 'backup' else 'startup_failed')
        assert client.get('/api/projects').status_code == 503
        result = client.post('/api/recovery/default-project', json={'confirm': True}).json()['data']
        assert result['required'] is False
        assert result['error'] is None
        assert len(list((home / 'backups').iterdir())) == 1


def test_two_recovery_requests_do_not_reset_each_other(lost_home):
    from app.main import create_app
    home, session = lost_home
    with TestClient(create_app()) as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: client.post('/api/recovery/default-project', json={'confirm': True}), range(2)))
        assert all(r.status_code == 200 and r.json()['data']['required'] is False for r in results)
        assert len(list((home / 'backups').iterdir())) == 1
        assert client.get(f"/api/sessions/{session['id']}").status_code == 200


@pytest.mark.parametrize('content', ['broken json', '{}'])
def test_unrelated_corruption_still_fails_startup(lost_home, content):
    from app.main import create_app
    home, _ = lost_home
    metadata = home / 'projects/_default/.ms_agent/project.json'
    metadata.write_text(content)
    with pytest.raises(ValueError):
        create_app()
    assert metadata.read_text() == content
    assert not (home / 'backups').exists()
