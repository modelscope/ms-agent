"""Fork API keeps history boundaries, models and origin links consistent."""
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


def test_fork_api_history_origin_and_source_deletion(client):
    source = client.post('/api/sessions', json={'title': 'Source'}).json()['data']
    project, session, manager = common.find_session(source['id'])
    log = manager.get_session_log(session)
    log.append({'role': 'user', 'content': 'First question'})
    answer = log.append({'role': 'assistant', 'content': 'First answer'})
    log.record_turn_checkpoint(1)
    log.record_loop_end({'duration_ms': 10})
    endpoint = f"/api/sessions/{session.id}"
    history = client.get(endpoint + '/messages').json()['data']
    point = history[-1]['fork_after_seq']
    assert history[-1]['log_seq'] == answer
    # Source advances; the old UI selection is still a valid prefix.
    log.append({'role': 'user', 'content': 'Later question'})
    fork = client.post(endpoint + '/fork', json={'after_seq': point, 'request_id': 'retry'})
    assert fork.status_code == 201, fork.text
    child = fork.json()['data']
    assert child['title'] == 'Source (2)' and child['model_id'] == source['model_id']
    retry = client.post(endpoint + '/fork', json={'after_seq': point, 'request_id': 'retry'})
    assert retry.json()['data']['id'] == child['id']
    child_endpoint = f"/api/sessions/{child['id']}"
    copied = client.get(child_endpoint + '/messages').json()['data']
    assert [m['content'] for m in copied] == ['First question', 'First answer']
    assert copied[-1]['fork_origin']['assistant_seq'] == answer
    assert copied[-1]['fork_origin']['available']
    client.delete(endpoint)
    copied = client.get(child_endpoint + '/messages').json()['data']
    assert not copied[-1]['fork_origin']['available']
    assert client.get(child_endpoint).status_code == 200


def test_incomplete_fork_rejected_and_missing_source_not_created(client):
    source = client.post('/api/sessions', json={'title': 'Incomplete'}).json()['data']
    _, session, manager = common.find_session(source['id'])
    log = manager.get_session_log(session)
    seq = log.append({'role': 'user', 'content': 'still waiting'})
    url = f"/api/sessions/{session.id}/fork"
    assert client.post(url, json={'after_seq': seq, 'request_id': 'one'}).status_code == 409
    assert client.post(url, json={'after_seq': True, 'request_id': 'one'}).status_code == 422
    assert client.post('/api/sessions/missing/fork', json={'after_seq': 1, 'request_id': 'one'}).status_code == 404
    assert len(client.get('/api/sessions').json()['data']) == 1


def test_compacted_tool_history_keeps_original_results_and_no_future_plan(client):
    source = client.post('/api/sessions', json={'title': 'Tool history'}).json()['data']
    project, session, manager = common.find_session(source['id'])
    log = manager.get_session_log(session)
    log.append({'role': 'user', 'content': 'Inspect file'})
    log.append({'role': 'assistant', 'tool_calls': [{
        'id': 'read', 'tool_name': 'file_system---read_file', 'arguments': '{"path":"a.txt"}'}]})
    log.append({'role': 'tool', 'tool_call_id': 'read', 'content': 'COMPLETE ORIGINAL RESULT'})
    log.append({'role': 'assistant', 'content': 'Done'})
    log.record_turn_checkpoint(1)
    saved = [dict(row) for row in log.get_visible_messages()]
    saved[2]['content'] = '[compacted]'
    log.commit_compaction(saved, {})
    endpoint = f'/api/sessions/{session.id}'
    history = client.get(endpoint + '/messages').json()['data']
    assert 'COMPLETE ORIGINAL RESULT' in str(history)
    assert '[compacted]' not in str(history)
    # A branch with no historical plan must not pick up a later shared plan.
    from pathlib import Path
    import json
    (Path(project.path) / 'plan.json').write_text(json.dumps({
        'todos': [{'id': 'later', 'content': 'Future task', 'status': 'pending'}]}))
    child = client.post(endpoint + '/fork', json={
        'after_seq': history[-1]['fork_after_seq'], 'request_id': 'tool'}).json()['data']
    assert not client.get(f"/api/sessions/{child['id']}/plan").json()['data']['tasks']
    copied = client.get(f"/api/sessions/{child['id']}/messages").json()['data']
    assert 'COMPLETE ORIGINAL RESULT' in str(copied)
