"""The public input API and reconnect transport share one durable state."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.backends.ms_agent import conversations as module
from app.core.settings import settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path))
    monkeypatch.setattr(settings, 'ms_agent_llm_model', '')
    async def prepare(self, request):
        return {'prompt': request['message']['content']}
    monkeypatch.setattr(module.Conversation, 'prepare', prepare)
    monkeypatch.setattr(module.Conversation, 'kick', lambda self: None)
    from app.main import create_app
    with TestClient(create_app()) as client:
        yield client


def send(client, identity='one', session_id=None, content='hello'):
    return client.post('/api/chat/inputs', json={
        'input_id': identity, 'session_id': session_id,
        'message': {'role': 'user', 'content': content}})


def test_retry_of_first_input_reuses_session_and_acceptance(client):
    first = send(client).json()['data']
    retry = send(client).json()['data']
    assert retry['session_id'] == first['session_id']
    assert len(retry['pending']) == 1
    assert len(client.get('/api/sessions').json()['data']) == 1
    assert send(client, content='different').status_code == 409
    assert 'prepared' not in first['input']
    assert 'prepared' not in first['pending'][0]


def test_edit_withdraw_and_restart_agree_with_history(client):
    first = send(client).json()['data']
    sid = first['session_id']
    url = f'/api/chat/sessions/{sid}/inputs/one'
    body = {'revision': 1, 'request': {'message': {'role': 'user', 'content': 'edited'}}}
    assert client.patch(url, json=body).status_code == 200
    assert client.delete(url, params={'revision': 1}).status_code == 409
    assert client.get(f'/api/sessions/{sid}/messages').json()['data'] == []
    module.conversations.pop(sid)
    pending = client.get(f'/api/chat/sessions/{sid}/inputs').json()['data']['pending']
    assert pending[0]['request']['message']['content'] == 'edited'
    assert pending[0]['held'] == 'restart'
    assert client.delete(url, params={'revision': 2}).status_code == 200
    module.conversations.pop(sid)
    assert client.get(f'/api/chat/sessions/{sid}/inputs').json()['data']['pending'] == []


def test_mode_changes_only_affect_new_inputs_and_stale_target_conflicts(client):
    assert client.get('/api/agent-settings').json()['data']['follow_up_behavior'] == 'queue'
    first = send(client).json()['data']
    sid = first['session_id']
    c = module.get(sid).controller
    c.start_next()
    c.append_message({'role': 'user', 'content': 'hello'})
    assert send(client, 'queued', sid).status_code == 200
    before = client.get('/api/agent-settings').json()['data']
    changed = client.patch('/api/agent-settings', json={'follow_up_behavior': 'steer'}).json()['data']
    assert changed['default_memory_enabled'] == before['default_memory_enabled']
    assert send(client, 'stale', sid).status_code == 409
    steered = client.post('/api/chat/inputs', json={
        'session_id': sid, 'input_id': 'steered', 'expected_turn_id': c.active_turn,
        'message': {'role': 'user', 'content': 'correction'}}).json()['data']
    assert [item['delivery'] for item in steered['pending']] == ['queue', 'steer']
    assert client.patch('/api/agent-settings', json={'follow_up_behavior': 'unknown'}).status_code == 422


@pytest.mark.asyncio
async def test_cursor_replay_snapshot_fallback_and_viewer_cleanup(tmp_path, monkeypatch):
    from ms_agent.session.session_log import SessionLog
    log = SessionLog(tmp_path, session_key='transport')
    monkeypatch.setattr(module, 'sm_for', lambda project: SimpleNamespace(get_session_log=lambda session: log))
    monkeypatch.setattr(module.Conversation, '_history', lambda self: [])
    c = module.Conversation(SimpleNamespace(id='project', path=tmp_path), SimpleNamespace(id='session'))
    for i in range(2050):
        c.publish({'type': 'state', 'pending': [], 'running': False, 'turn_id': None})
    assert len(c.events) == 2048
    stale = c.subscribe(f'{c.epoch}:0')
    snapshot = json.loads((await anext(stale))['data'])
    assert snapshot['type'] == 'snapshot' and c.viewers == 1
    await stale.aclose()
    assert c.viewers == 0
    live = c.subscribe(snapshot['cursor'])
    c.publish({'type': 'begin', 'turn_id': 'next'})
    assert json.loads((await anext(live))['data'])['type'] == 'begin'
    await live.aclose()
    for _ in range(100):
        c._append_frame({'type': 'text', 'content': 'x', 'meta': {}})
    assert len(c.active_frames) == 1 and len(c.active_frames[0]['content']) == 100
    for i in range(100):
        c._append_frame({'type': 'thought', 'content': 'y', 'meta': {'block': 1, 'elapsed_ms': i}})
        c._append_frame({'type': 'turn', 'content': '', 'meta': {'elapsed_ms': i}})
    assert len(c.active_frames) == 2 and len(c.active_frames[-1]['content']) == 100
    assert c.active_frames[-1]['meta']['elapsed_ms'] == 99


def test_legacy_retry_of_completed_input_ends_without_reexecution(client):
    first = send(client).json()['data']
    c = module.get(first['session_id']).controller
    c.start_next()
    c.append_message({'role': 'user', 'content': 'hello'})
    c.append_message({'role': 'assistant', 'content': 'done'})
    c.finish()
    reply = client.post('/api/chat', json={
        'input_id': 'one', 'message': {'role': 'user', 'content': 'hello'}})
    assert reply.status_code == 200 and 'already_delivered' in reply.text
    assert len(c.log.get_all_messages()) == 2


@pytest.mark.asyncio
async def test_context_operation_releases_runtime_before_next_input_is_claimed(tmp_path, monkeypatch):
    from app.backends.ms_agent import context
    from ms_agent.session.session_log import SessionLog
    log = SessionLog(tmp_path, session_key='context-boundary')
    monkeypatch.setattr(module, 'sm_for', lambda project: SimpleNamespace(get_session_log=lambda session: log))
    monkeypatch.setattr(module.Conversation, '_history', lambda self: [])
    c = module.Conversation(SimpleNamespace(id='project', path=tmp_path), SimpleNamespace(id='context-boundary'))
    async def prepare(request):
        return {'prompt': 'next'}
    await c.controller.accept('next', {'message': {'role': 'user', 'content': 'next'}}, prepare)
    lock = asyncio.Lock()
    await lock.acquire()
    monkeypatch.setattr(context.registry, 'peek_exact', lambda sid: SimpleNamespace(turn_lock=lock))
    entered = asyncio.Event()
    start_next = c.controller.start_next
    def claim():
        assert not lock.locked()
        entered.set()
        start_next()
        return None
    monkeypatch.setattr(c.controller, 'start_next', claim)
    worker = asyncio.create_task(c._run())
    await asyncio.sleep(0)
    assert c.controller.active_turn is None and not entered.is_set()
    lock.release()
    await asyncio.wait_for(worker, 1)
    assert entered.is_set() and c.controller.active_turn is not None
    # The admission/claim window must also block a new manual operation,
    # before the SDK runtime has acquired its execution lock.
    monkeypatch.setitem(module.conversations, 'context-boundary', c)
    from app.backends.errors import Conflict
    with pytest.raises(Conflict):
        context._check_input_owner('context-boundary')


@pytest.fixture
def isolated_conversation(tmp_path, monkeypatch):
    from ms_agent.session.session_log import SessionLog
    log = SessionLog(tmp_path, session_key='lifecycle')
    monkeypatch.setattr(module, 'sm_for', lambda project: SimpleNamespace(get_session_log=lambda session: log))
    monkeypatch.setattr(module.Conversation, '_history', lambda self: [])
    conversation = module.Conversation(SimpleNamespace(id='project', path=tmp_path), SimpleNamespace(id='session'))
    monkeypatch.setattr(module, 'get', lambda sid: conversation)
    return conversation


@pytest.mark.asyncio
async def test_stop_cancels_startup_before_closing_runtime(isolated_conversation, monkeypatch):
    from app.backends.ms_agent.runtime import registry
    c = isolated_conversation
    await c.controller.accept('one', {'message': {'content': 'hello'}}, AsyncMock(return_value={'prompt': 'hello'}))
    c.controller.start_next()
    c.turn_id = c.controller.active_turn
    entered = asyncio.Event()
    async def startup():
        entered.set()
        await asyncio.Event().wait()
        pytest.fail('Stopped input was dispatched')
    c.worker = asyncio.create_task(startup())
    await entered.wait()
    async def interrupt(sid):
        assert c.worker.cancelled()
        return True
    monkeypatch.setattr(registry, 'interrupt', interrupt)
    assert await module.interrupt('session', c.turn_id)
    assert c.controller.pending()[0]['held'] == 'stopped'
    assert not c.snapshot()['running']


@pytest.mark.asyncio
async def test_managed_startup_is_cancelled_with_its_worker(monkeypatch):
    from app.backends.ms_agent import chat
    from app.schemas.chat import ChatRequest
    monkeypatch.setattr(chat, '_resolve_or_create', lambda req: (
        SimpleNamespace(id='project'), SimpleNamespace(id='session', name='existing')))
    monkeypatch.setattr(chat, 'autoname_session', lambda *args: None)
    monkeypatch.setattr(chat, '_is_default_name', lambda name: False)
    monkeypatch.setattr(chat, '_is_cheap_title', lambda *args: False)
    entered, closed = asyncio.Event(), asyncio.Event()
    async def startup(*args):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()
    monkeypatch.setattr(chat, '_start_turn', startup)
    stream = chat.run_turn(ChatRequest(message={'role': 'user', 'content': 'hello'}), prepared={'prompt': 'hello'})
    await anext(stream)  # session frame before runtime startup
    worker = asyncio.create_task(anext(stream))
    await entered.wait()
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)
    assert closed.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize('withdraw', [True, False])
async def test_legacy_stream_ends_when_delivery_frames_are_unavailable(isolated_conversation, monkeypatch, withdraw):
    from app.backends.ms_agent import chat
    from app.schemas.chat import ChatRequest
    c = isolated_conversation
    item = await c.controller.accept('one', {'message': {'content': 'hello'}}, AsyncMock(return_value={'prompt': 'hello'}))
    monkeypatch.setattr(module, 'submit', AsyncMock(return_value={
        'session_id': 'session', 'project_id': 'project', 'input': item,
        'cursor': f'{c.epoch}:0'}))
    stream = chat.stream(ChatRequest(message={'role': 'user', 'content': 'hello'}))
    await anext(stream)
    if withdraw:
        c.controller.withdraw('one', 1)
    else:
        c.controller.start_next()
        c.controller.append_message({'role': 'user', 'content': 'hello'})
        c.controller.append_message({'role': 'assistant', 'content': 'done'})
        c.controller.finish()
        # Force a snapshot after the complete task has left the event buffer.
        for _ in range(2050):
            c.publish({'type': 'state', **c.state()})
    result = json.loads((await asyncio.wait_for(anext(stream), 1))['data'])
    assert result['type'] == 'done'
    await stream.aclose()


@pytest.mark.asyncio
async def test_legacy_stream_replays_completed_turn_before_ending(isolated_conversation, monkeypatch):
    from app.backends.ms_agent import chat
    from app.schemas.chat import ChatRequest
    c = isolated_conversation
    item = await c.controller.accept('one', {'message': {'content': 'hello'}}, AsyncMock(return_value={'prompt': 'hello'}))
    monkeypatch.setattr(module, 'submit', AsyncMock(return_value={
        'session_id': 'session', 'project_id': 'project', 'input': item,
        'cursor': f'{c.epoch}:{c.sequence}'}))
    stream = chat.stream(ChatRequest(message={'role': 'user', 'content': 'hello'}))
    await anext(stream)
    c.controller.start_next()
    c.controller.append_message({'role': 'user', 'content': 'hello'})
    for chunk in [
        {'type': 'input', 'meta': {'input_id': 'one', 'turn_id': c.controller.active_turn}},
        {'type': 'text', 'content': 'complete answer'},
        {'type': 'done'},
    ]:
        c.publish({'type': 'chunk', 'chunk': chunk})
    c.controller.finish()
    received = []
    async with asyncio.timeout(1):
        async for event in stream:
            received.append(json.loads(event['data']))
    assert [chunk['type'] for chunk in received] == ['input', 'text', 'done']
    assert received[1]['content'] == 'complete answer'
    assert c.viewers == 0


@pytest.mark.asyncio
async def test_cancel_preparation_closes_initialization_waiter(isolated_conversation, monkeypatch):
    from app.backends.ms_agent.runtime import registry
    entered, closed = asyncio.Event(), asyncio.Event()
    class Waiting:
        async def wait(self):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
    driver = asyncio.create_task(asyncio.Event().wait())
    rt = SimpleNamespace(agent=SimpleNamespace(), run_task=driver,
                         input_source=SimpleNamespace(waiting=Waiting()))
    monkeypatch.setattr(registry, 'get', AsyncMock(return_value=rt))
    task = asyncio.create_task(isolated_conversation.prepare({'message': {'role': 'user', 'content': 'hello'}}))
    try:
        await entered.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert closed.is_set()
        assert not driver.done()
    finally:
        driver.cancel()
        await asyncio.gather(driver, return_exceptions=True)
