"""Cold startup and management APIs preserve independent changes."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.backends.ms_agent import common
from app.core.settings import settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path))
    monkeypatch.setattr(settings, 'ms_agent_llm_model', '')
    from app.main import create_app
    with TestClient(create_app()) as client:
        yield client


def test_cold_homepage_queries_do_not_rewrite_entities(client):
    root = common.pm().base_dir
    original = {str(p): p.stat().st_mtime_ns for p in root.rglob('project.json')}
    assert len(original) == 1
    start = Barrier(8, timeout=5)

    def get_together(path):
        start.wait()
        return client.get(path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(get_together, ['/api/projects', '/api/sessions'] * 4))
    assert all(r.status_code == 200 for r in responses)
    assert client.get('/api/sessions').json()['data'] == []
    assert {str(p): p.stat().st_mtime_ns for p in root.rglob('project.json')} == original
    assert not list(root.rglob('session.json'))






def test_lost_default_is_reported_without_recreating_data(client):
    manager = common.pm()
    metadata = manager._meta_file('_default')
    metadata.unlink()
    with pytest.raises(ValueError, match='Default project is not initialized or its metadata is missing'):
        client.post('/api/sessions', json={'title': 'No ghost'})
    assert not metadata.exists()
    assert not list(manager.base_dir.rglob('session.json'))
