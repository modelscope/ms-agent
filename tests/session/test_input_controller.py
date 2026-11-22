import asyncio
import json

import pytest

from ms_agent.session.input_controller import (InputConflict,
                                               SessionInputController,
                                               skipped_tool_result)
from ms_agent.session.session_log import SessionLog


def controller(tmp_path):
    return SessionInputController(SessionLog(tmp_path, session_key='test'))


async def prepare(request):
    return {'prompt': request['message']['content']}


async def accept(c, identity, mode='queue', target=None):
    return await c.accept(identity, {'message': {'role': 'user', 'content': identity}},
                          prepare, mode, target)


def deliver(c, item):
    c.append_message({'role': 'user', 'content': item['prepared']['prompt'],
                      'input_id': item['input_id']})


@pytest.mark.asyncio
async def test_queue_and_steering_have_distinct_consumption_boundaries(tmp_path):
    c = controller(tmp_path)
    await accept(c, 'a')
    deliver(c, c.start_next())
    turn = c.active_turn
    await accept(c, 'q1')
    await accept(c, 'q2')
    await accept(c, 's1', 'steer', turn)
    await accept(c, 's2', 'steer', turn)
    assert c.finish() is False
    batch = c.take_steering()
    assert [i['input_id'] for i in batch] == ['s1', 's2']
    for item in batch:
        deliver(c, item)
    assert c.active_turn == turn
    assert c.finish()
    next_input = c.start_next()
    assert next_input['input_id'] == 'q1'
    assert c.active_turn != turn
    assert [m['input_id'] for m in c.log.get_all_messages()] == ['a', 's1', 's2']


@pytest.mark.asyncio
async def test_concurrent_retry_and_disconnect_do_not_repeat_preparation(tmp_path):
    c = controller(tmp_path)
    gate = asyncio.Event()
    count = 0

    async def slow(request):
        nonlocal count
        count += 1
        await gate.wait()
        return await prepare(request)

    request = {'message': {'content': 'hello'}}
    first = asyncio.create_task(c.accept('same', request, slow))
    await asyncio.sleep(0)
    retry = asyncio.create_task(c.accept('same', request, slow))
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    gate.set()
    receipt = await retry
    assert receipt['state'] == 'pending'
    assert count == 1
    assert len(c.pending()) == 1
    with pytest.raises(InputConflict):
        await c.accept('same', {'message': {'content': 'different'}}, slow)


@pytest.mark.asyncio
async def test_stop_holds_only_covered_inputs_and_resume_does_not_restart_task(tmp_path):
    c = controller(tmp_path)
    await accept(c, 'a')
    deliver(c, c.start_next())
    await accept(c, 'b')
    c.hold()
    await accept(c, 'during-stop')
    c.stopped()
    assert c.start_next() is None
    await accept(c, 'manual-new-task')
    new = c.start_next()
    assert new['input_id'] == 'manual-new-task'
    deliver(c, new)
    await accept(c, 'new-followup')
    assert c.finish()
    assert c.start_next()['input_id'] == 'new-followup'
    deliver(c, c.inputs['new-followup'])
    c.finish()
    c.resume()
    assert c.start_next()['input_id'] == 'b'


@pytest.mark.asyncio
async def test_recovery_uses_user_row_as_delivery_commit(tmp_path):
    c = controller(tmp_path)
    await accept(c, 'delivered')
    deliver(c, c.start_next())
    await accept(c, 'pending')
    restored = controller(tmp_path)
    assert restored.inputs['delivered']['state'] == 'delivered'
    assert restored.pending()[0]['held'] == 'restart'
    assert restored.start_next() is None
    restored.resume()
    assert restored.start_next()['input_id'] == 'pending'
    records = restored.log.records()
    seqs = [r['seq'] for r in records if 'seq' in r]
    assert seqs == sorted(set(seqs))
    assert sum(row['role'] == 'user' for row in restored.log.get_all_messages()) == 1
    assert restored.log.get_all_messages()[-1]['interrupted'] is True


@pytest.mark.asyncio
async def test_edit_cannot_race_delivery_or_overwrite_new_revision(tmp_path):
    c = controller(tmp_path)
    await accept(c, 'a')
    await c.edit('a', 1, {'message': {'content': 'edited'}}, prepare)
    with pytest.raises(InputConflict):
        c.withdraw('a', 1)
    item = c.start_next()
    assert item['prepared']['prompt'] == 'edited'
    with pytest.raises(InputConflict):
        await c.edit('a', 2, {'message': {'content': 'too late'}}, prepare)
    deliver(c, item)
    assert c.pending() == []


@pytest.mark.asyncio
async def test_steering_preparation_cannot_land_in_later_task(tmp_path):
    c = controller(tmp_path)
    await accept(c, 'a')
    deliver(c, c.start_next())
    old_turn = c.active_turn
    gate = asyncio.Event()

    async def slow(request):
        await gate.wait()
        return await prepare(request)

    submission = asyncio.create_task(c.accept(
        'late', {'message': {'content': 'late'}}, slow, 'steer', old_turn))
    await asyncio.sleep(0)
    assert c.finish()
    await accept(c, 'b')
    c.start_next()
    gate.set()
    with pytest.raises(InputConflict):
        await submission
    assert 'late' not in c.inputs


def test_skipped_tool_is_explicit_non_success_without_fabricated_output():
    message = skipped_tool_result({'id': 'write-1', 'tool_name': 'write_file'})
    result = json.loads(message.content)
    assert message.tool_call_id == 'write-1'
    assert message.is_error is True
    assert result['result'] is None
    assert result['status'] == 'not_executed'
    assert 'stdout' not in result and 'exit_code' not in result
    assert message.execution_status == 'skipped'


def test_anthropic_pairs_every_skipped_result_before_followup_text():
    from ms_agent.llm.transport.anthropic_messages import AnthropicMessagesTransport
    from ms_agent.llm.utils import Message
    transport = AnthropicMessagesTransport.__new__(AnthropicMessagesTransport)
    transport._vision = None
    transport._vision_supported = False
    calls = [{'id': str(i), 'tool_name': 'write_file', 'arguments': '{}'} for i in range(2)]
    wire = transport._format_input_message([
        Message(role='assistant', tool_calls=calls),
        *(skipped_tool_result(call) for call in calls),
        Message(role='user', content='Do not write the files'),
    ])
    assert [part['tool_use_id'] for part in wire[1]['content']] == ['0', '1']
    assert all(part['is_error'] for part in wire[1]['content'])
    assert wire[2]['content'][0]['text'] == 'Do not write the files'


@pytest.mark.asyncio
async def test_preparation_crossing_stop_is_held_even_after_stop_returns(tmp_path):
    c = controller(tmp_path)
    gate = asyncio.Event()
    async def slow(request):
        await gate.wait()
        return await prepare(request)
    task = asyncio.create_task(c.accept('slow', {'message': {'content': 'slow'}}, slow))
    await asyncio.sleep(0)
    c.hold()
    c.stopped()
    gate.set()
    assert (await task)['held'] == 'stopped'
    assert c.start_next() is None


@pytest.mark.asyncio
async def test_missing_attachment_is_held_before_delivery_and_survives_restart(tmp_path):
    from ms_agent.project import Workspace
    workspace = Workspace(tmp_path / 'workspace')
    workspace.write_file('note.txt', 'secret fixture')
    c = controller(tmp_path)
    c.workspace = workspace
    await c.accept('file', {'message': {'content': 'read this', 'files': [{'path': 'note.txt'}]}}, prepare)
    workspace.delete('note.txt')
    with pytest.raises(ValueError, match='no longer available'):
        c.start_next()
    assert c.log.get_all_messages() == []
    restored = controller(tmp_path)
    assert restored.pending()[0]['held'] == 'unavailable'
    assert 'note.txt' in restored.pending()[0]['error']


@pytest.mark.asyncio
async def test_restart_never_fabricates_success_for_unrecorded_tool_outcome(tmp_path):
    c = controller(tmp_path)
    await accept(c, 'task')
    deliver(c, c.start_next())
    c.append_message({'role': 'assistant', 'tool_calls': [
        {'id': 'effect', 'tool_name': 'shell', 'arguments': '{}'}]})
    restored = controller(tmp_path)
    rows = restored.log.get_all_messages()
    result = next(row for row in rows if row.get('tool_call_id') == 'effect')
    assert result['is_error'] and 'unknown' in result['content']
    assert 'not executed' not in result['content']
    assert rows[-1]['interrupted']
    assert restored.pending() == []
    assert len(controller(tmp_path).log.get_all_messages()) == len(rows)


@pytest.mark.asyncio
async def test_limit_includes_preparing_inputs_and_retries_do_not_use_slots(tmp_path):
    c = controller(tmp_path)
    c.MAX_PENDING = 1
    await accept(c, 'one')
    assert (await accept(c, 'one'))['input_id'] == 'one'
    with pytest.raises(InputConflict, match='limit'):
        await accept(c, 'two')


@pytest.mark.asyncio
async def test_task_end_record_distinguishes_final_text_from_finished_execution(tmp_path):
    c = controller(tmp_path)
    await accept(c, 'task')
    deliver(c, c.start_next())
    c.append_message({'role': 'assistant', 'content': 'provisional final'})
    # A Stop hook (or steering) may still keep the logical task open here.
    restored = controller(tmp_path)
    assert restored.log.get_all_messages()[-1]['interrupted']
    assert restored.log.records()[-1]['task']['state'] == 'interrupted'
    await accept(restored, 'new')
    deliver(restored, restored.start_next())
    restored.append_message({'role': 'assistant', 'content': 'complete'})
    restored.finish()
    assert controller(tmp_path).log.get_all_messages()[-1]['content'] == 'complete'
