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


def test_null_switch_leaves_memory_on_for_webui_and_tui(client):
    """JSON null does not turn memory off. The file the TUI reads stays on.

    An explicit true/false still writes, and a null string pin still clears.
    """
    assert client.patch(
        '/api/agent-settings',
        json={'default_memory_enabled': True}).status_code == 200
    assert client.put(
        '/api/agent-settings',
        json={'default_memory_enabled': None}).status_code == 200
    data = client.get('/api/agent-settings').json()['data']
    assert data['default_memory_enabled'] is True

    from ms_agent.personalization import PersonalizationSettings
    from app.backends.ms_agent.common import home
    assert PersonalizationSettings(global_dir=home()).load().memory_enabled is True

    assert client.patch(
        '/api/agent-settings',
        json={'memory_llm_model': 'one'}).status_code == 200
    assert client.patch(
        '/api/agent-settings',
        json={'memory_llm_model': None}).status_code == 200
    data = client.get('/api/agent-settings').json()['data']
    assert data['memory_llm_model'] is None
    assert data['default_memory_enabled'] is True

    assert client.patch(
        '/api/agent-settings',
        json={'default_memory_enabled': False}).status_code == 200
    assert client.get('/api/agent-settings').json()['data']['default_memory_enabled'] is False


def test_parallel_api_patches_merge_fields_and_last_save_wins(client):
    start = Barrier(2, timeout=5)

    def patch_together(fields):
        start.wait()
        return client.patch('/api/agent-settings', json=fields)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(patch_together, {'default_memory_enabled': True})
        b = pool.submit(patch_together, {'global_skill_auto_attach': False})
        assert a.result().status_code == b.result().status_code == 200
    data = client.get('/api/agent-settings').json()['data']
    assert data['default_memory_enabled'] is True
    assert data['global_skill_auto_attach'] is False
    assert client.patch('/api/agent-settings', json={'default_memory_enabled': False}).status_code == 200
    assert client.get('/api/agent-settings').json()['data']['default_memory_enabled'] is False


def test_model_api_and_deleted_session_error(client):
    assert client.post('/api/providers', json={'id': 'api_test', 'name': 'API test'}).status_code == 201
    assert client.patch('/api/providers/api_test', json={'api_key': 'not-a-real-key'}).status_code == 200
    model = client.post('/api/models', json={'provider_id': 'api_test', 'name': 'M1'})
    assert model.status_code == 201
    mid = model.json()['data']['id']
    assert client.patch('/api/agent-settings', json={'default_model_id': mid}).status_code == 200
    created = client.post('/api/sessions', json={'title': 'Test'})
    assert created.status_code == 201
    session = created.json()['data']
    assert session['model_id'] == mid
    other = client.post('/api/models', json={'provider_id': 'api_test', 'name': 'M2'})
    assert other.status_code == 201
    other_id = other.json()['data']['id']
    switched = client.patch(f"/api/sessions/{session['id']}/model", json={'model_id': other_id})
    assert switched.status_code == 200
    assert switched.json()['data']['session']['model_id'] == other_id
    assert switched.json()['data']['settings']['default_model_id'] == other_id
    assert client.get(f"/api/sessions/{session['id']}").json()['data']['model_id'] == other_id
    assert client.get('/api/agent-settings').json()['data']['default_model_id'] == other_id
    assert client.delete(f"/api/sessions/{session['id']}").status_code == 200
    missing = client.patch(f"/api/sessions/{session['id']}/model", json={'model_id': mid})
    assert missing.status_code == 404
    assert missing.json() == {'code': 404, 'message': 'Conversation not found.', 'data': None}
    assert client.get('/api/sessions').json()['data'] == []


def test_lost_default_is_reported_without_recreating_data(client):
    manager = common.pm()
    metadata = manager._meta_file('_default')
    metadata.unlink()
    with pytest.raises(ValueError, match='Default project is not initialized or its metadata is missing'):
        client.post('/api/sessions', json={'title': 'No ghost'})
    assert not metadata.exists()
    assert not list(manager.base_dir.rglob('session.json'))


def _provider_ids(client):
    return [p['id'] for p in client.get('/api/providers').json()['data']]


def test_new_provider_is_listed_first(client):
    default = _provider_ids(client)
    assert default and default[0] != 'zzz'  # built-ins lead by default
    assert client.post('/api/providers', json={'id': 'zzz'}).status_code == 201
    assert _provider_ids(client)[0] == 'zzz'


def test_reorder_persists_and_ignores_unknown_ids(client):
    ids = _provider_ids(client)
    # Move the last built-in to the front; tack on an id that does not exist.
    reordered = client.put(
        '/api/providers/order',
        json={'order': [ids[-1], 'ghost', *ids[:-1]]},
    )
    assert reordered.status_code == 200
    assert [p['id'] for p in reordered.json()['data']] == [ids[-1], *ids[:-1]]
    assert _provider_ids(client) == [ids[-1], *ids[:-1]]


def test_deleting_provider_drops_it_from_the_order(client):
    assert client.post('/api/providers', json={'id': 'temp'}).status_code == 201
    assert _provider_ids(client)[0] == 'temp'
    assert client.delete('/api/providers/temp').status_code == 200
    assert 'temp' not in _provider_ids(client)


def test_thinking_is_session_scoped_and_turn_snapshot_is_immutable(client):
    from app.backends.ms_agent import session_models, sidecar, config
    from app.backends.ms_agent.common import find_session

    model = client.post('/api/models', json={'provider_id': 'dashscope', 'name': 'qwen3.8-flash'}).json()['data']
    mid = model['id']
    a, b = [client.post('/api/sessions', json={'title': label, 'model_id': mid}).json()['data'] for label in ('A', 'B')]
    change = lambda sid, effort: client.patch(f'/api/sessions/{sid}/thinking', json={'model_id': mid, 'reasoning_effort': effort})
    assert change(a['id'], 'off').status_code == 200
    project, session, manager = find_session(a['id'])
    _, frozen = session_models.prepare(project, session)
    assert change(b['id'], 'low').status_code == 200
    assert client.get(f"/api/sessions/{a['id']}").json()['data']['reasoning_efforts'][mid] == 'off'
    assert client.get(f"/api/sessions/{b['id']}").json()['data']['reasoning_efforts'][mid] == 'low'
    assert sidecar.get('models', mid)['advanced_params']['reasoning_effort'] == 'low'
    # Resolving an existing conversation must not mutate the global default.
    _, current = session_models.prepare(project, manager.get(a['id']))
    for snapshot in (frozen, current):
        token = config._model_snapshot.set(snapshot)
        try:
            assert config._webui_generation_params('dashscope', 'qwen3.8-flash')['reasoning_effort'] == 'off'
        finally:
            config._model_snapshot.reset(token)
    assert sidecar.get('models', mid)['advanced_params']['reasoning_effort'] == 'low'
    other = client.post('/api/models', json={'provider_id': 'dashscope', 'name': 'qwen3.8-max'}).json()['data']['id']
    assert client.patch(f"/api/sessions/{a['id']}/model", json={'model_id': other}).status_code == 200
    assert change(a['id'], 'off').status_code == 400
    restored = client.patch(f"/api/sessions/{a['id']}/model", json={'model_id': mid}).json()['data']['session']
    assert restored['reasoning_efforts'][mid] == 'off'
    # SDK metadata, rather than frontend-local state, survives a fresh read.
    assert manager.get(a['id']).reasoning_efforts['dashscope']['qwen3.8-flash'] == 'off'
    assert client.patch(f'/api/models/{mid}', json={'advanced_params': {'extra_body': {'reasoning_effort': 'low'}}}).status_code == 200
    defaults = client.get('/api/models/generation-defaults', params={'provider_id': 'dashscope', 'model': 'qwen3.8-flash'}).json()['data']
    assert defaults['raw_override'] is True
    assert change(a['id'], 'low').status_code == 400
