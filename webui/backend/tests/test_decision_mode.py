"""Decision modes share the SDK session transaction and never leak credentials."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.backends.errors import Conflict
from app.backends.ms_agent import common, model_link, session_models
from app.core.settings import settings
from ms_agent.config.decision import DecisionSettings
from ms_agent.config.model_settings import ModelSettingsManager


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path))
    monkeypatch.setattr(settings, 'ms_agent_llm_model', '')
    from app.main import create_app
    with TestClient(create_app()) as client:
        ModelSettingsManager(tmp_path).add_provider(
            'fixture', api_key='secret-fixture-key', base_url='https://example.invalid/v1', models=['chat'])
        model_link.set_active_model('fixture', 'chat')
        yield client


def test_config_select_lock_restore_and_fork(client):
    assert client.patch('/api/agent-settings', json={'default_execution_mode': 'decision'}).status_code == 400
    response = client.patch('/api/agent-settings', json={
        'decision_provider_id': 'fixture', 'decision_model': 'decision-model-preview'})
    assert response.status_code == 200 and response.json()['data']['decision_available']
    standard = client.post('/api/sessions', json={'title': 'Standard'}).json()['data']
    selected = client.patch(f"/api/sessions/{standard['id']}/execution-mode", json={'execution_mode': 'decision'})
    assert selected.status_code == 200 and selected.json()['data']['execution_mode'] == 'decision'
    assert client.get('/api/agent-settings').json()['data']['default_execution_mode'] == 'decision'
    project, session, manager = common.find_session(standard['id'])
    locked, snapshot = session_models.prepare(project, session)
    assert locked.execution_profile['model'] == 'decision-model-preview'
    assert 'secret-fixture-key' not in str(locked.execution_profile)
    assert snapshot.settings['execution']['mode'] == 'decision'
    endpoint = f'/api/sessions/{session.id}'
    assert client.patch(endpoint + '/execution-mode', json={'execution_mode': 'standard'}).status_code == 409
    assert client.get(endpoint).json()['data']['execution_mode_locked']
    client.patch('/api/agent-settings', json={'default_execution_mode': 'standard'})
    session_models.prepare(project, session)
    assert client.get('/api/agent-settings').json()['data']['default_execution_mode'] == 'standard'
    log = manager.get_session_log(locked)
    log.append({'role': 'user', 'content': 'Check'})
    log.append({'role': 'assistant', 'content': 'Verified'})
    log.record_turn_checkpoint(1)
    history = client.get(endpoint + '/messages').json()['data']
    child = client.post(endpoint + '/fork', json={'after_seq': history[-1]['fork_after_seq'], 'request_id': 'decision-fork'}).json()['data']
    assert child['execution_mode'] == 'decision' and child['execution_mode_locked']
    assert client.post('/api/sessions', json={'title': 'New'}).json()['data']['execution_mode'] == 'standard'


def test_legacy_history_is_locked_and_chat_cannot_override(client):
    from app.backends.ms_agent.chat import _resolve_or_create
    from app.schemas.chat import ChatRequest
    source = client.post('/api/sessions', json={'title': 'New'}).json()['data']
    _, session, manager = common.find_session(source['id'])
    manager.get_session_log(session).append({'role': 'user', 'content': 'Old task'})
    endpoint = f'/api/sessions/{session.id}'
    assert client.get(endpoint).json()['data']['execution_mode_locked']
    assert client.patch(endpoint + '/execution-mode', json={'execution_mode': 'decision'}).status_code == 409
    with pytest.raises(Conflict):
        _resolve_or_create(ChatRequest(session_id=session.id, execution_mode='decision'))


def test_first_start_races_selection_without_partial_profile(client):
    DecisionSettings(common.home()).update(decision={'provider': 'fixture', 'model': 'decision-model-preview'})
    source = client.post('/api/sessions', json={'title': 'New'}).json()['data']
    _, session, manager = common.find_session(source['id'])
    gate = Barrier(2)
    def select():
        gate.wait()
        try:
            return manager.set_execution_mode(session.id, 'decision')
        except ValueError:
            return None
    def start():
        gate.wait()
        return manager.prepare_execution(session.id)
    with ThreadPoolExecutor(2) as pool:
        a, b = pool.submit(select), pool.submit(start)
        a.result(); b.result()
    final = manager.get(session.id)
    assert final.execution_mode_locked_at
    assert (final.execution_profile is not None) == (final.execution_mode == 'decision')


def test_explicit_probe_closes_client_without_saving(client, monkeypatch):
    from ms_agent.decision.types import DecisionResponse
    calls = []
    class Probe:
        async def decide(self, request, **kwargs):
            calls.append('decide')
            return DecisionResponse({'valid': {'type': 'noul', 'noul': 1}}, elapsed_ms=4)
        async def aclose(self):
            calls.append('closed')
    monkeypatch.setattr(DecisionSettings, 'client', lambda *_: Probe())
    before = (Path(common.home()) / 'settings.json').read_bytes()
    result = client.post('/api/agent-settings/decision/test', json={'provider': 'fixture', 'model': 'decision-model-preview'})
    assert result.status_code == 200 and result.json()['data']['ok']
    assert calls == ['decide', 'closed']
    assert (Path(common.home()) / 'settings.json').read_bytes() == before
