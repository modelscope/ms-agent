"""Historical replay, failure recovery, and independent session creation."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from ms_agent.project import ProjectManager, SessionManager
from ms_agent.session import ContextAssembler, SessionLog
from ms_agent.session.replay import InvalidForkPoint, fork_points, read_records


def turn(log, question='question', answer='answer'):
    log.append({'role': 'user', 'content': question})
    log.append({'role': 'assistant', 'content': answer})
    log.record_turn_checkpoint(1, {'active_model': 'test-model'})
    return fork_points(log.records())[-1].after_seq


def context(log):
    return [m.content for m in ContextAssembler(log).assemble()]


@pytest.mark.parametrize('failure', ['message', 'sidecar'])
def test_failed_compaction_recovers_only_committed_context(tmp_path, monkeypatch, failure):
    log = SessionLog(tmp_path, 'test')
    turn(log)
    original = context(log)
    if failure == 'message':
        append = log.append
        def fail(message):
            if message.get('role') == 'assistant':
                raise OSError('disk failure')
            return append(message)
        monkeypatch.setattr(log, 'append', fail)
    else:
        def fail(meta):
            raise OSError('sidecar failure')
        monkeypatch.setattr(log, '_write_meta', fail)
    with pytest.raises(OSError):
        log.commit_compaction([{'role': 'user', 'content': 'summary'},
                               {'role': 'assistant', 'content': 'answer'}], {'strategy': 'test'})
    restored = SessionLog(tmp_path, 'test')
    assert context(restored) == (original if failure == 'message' else ['summary', 'answer'])
    assert context(log) == context(restored)


@pytest.fixture
def sessions(tmp_path):
    pm = ProjectManager(base_dir=tmp_path)
    project = pm.create('test', path=str(tmp_path / 'workspace'), init_workspace=False)
    return SessionManager(project, base_dir=tmp_path)


@pytest.mark.parametrize('legacy', [False, True])
def test_multiple_compactions_fork_historical_view(sessions, legacy):
    source = sessions.create('Original', model='m', model_provider='provider')
    log = sessions.get_session_log(source)
    if legacy:
        header = log._path.read_text().replace('"checkpoint_from_seq": 0, ', '')
        log._path.write_text(header)
        log.invalidate_cache()
    points, expected = [], []
    for i in range(3):
        log.append({'role': 'user', 'content': f'question {i}'})
        if i:
            rows = [{'role': 'user', 'content': f'summary {i}'},
                    {'role': 'user', 'content': f'question {i}'}]
            if legacy:
                log.record_compaction({'strategy': 'summary'})
                seqs = [log.append({**m, '_source': 'compaction'}) for m in rows]
                log.last_consolidated = seqs[0]
            else:
                log.commit_compaction(rows, {'strategy': 'summary'})
        log.append({'role': 'assistant', 'content': f'answer {i}'})
        if not legacy:
            log.record_turn_checkpoint(i + 1)
        else:
            log.record_loop_end({'duration_ms': i})
        points.append(fork_points(log.records())[-1].after_seq)
        expected.append(context(log))
    original = log._path.read_bytes()
    # A later incomplete write does not prevent branching from a valid prefix.
    with log._path.open('ab') as f:
        f.write(b'{"role":"user","content":')
    for point, messages in zip(points, expected):
        child = sessions.fork(source.id, after_seq=point)
        assert context(sessions.get_session_log(child)) == messages
    assert log._path.read_bytes().startswith(original)


def test_fork_numbering_retry_and_source_deletion(sessions):
    source = sessions.create('Topic')
    log = sessions.get_session_log(source)
    point = turn(log)
    with ThreadPoolExecutor(max_workers=4) as pool:
        children = list(pool.map(lambda _: sessions.fork(source.id, after_seq=point, request_id='one'), range(4)))
    assert len({s.id for s in children}) == 1
    child = children[0]
    assert child.name == 'Topic (2)'
    next_child = sessions.fork(child.id, after_seq=point)
    assert next_child.name == 'Topic (3)'
    assert next_child.forked_from['session_id'] == child.id
    with pytest.raises(InvalidForkPoint):
        sessions.fork(source.id, after_seq=point - 1, request_id='one')
    sessions.delete(source.id)
    assert context(sessions.get_session_log(child)) == ['question', 'answer']
    child_log = sessions.get_session_log(child)
    turn(child_log, 'only child', 'only child answer')
    assert context(sessions.get_session_log(next_child)) == ['question', 'answer']


@pytest.mark.parametrize('state', ['tool', 'interrupted', 'errored', 'error_marker'])
def test_incomplete_or_failed_turn_has_no_fork_point(tmp_path, state):
    log = SessionLog(tmp_path, 'test')
    log.append({'role': 'user', 'content': 'q'})
    response = {'role': 'assistant', 'content': 'a'}
    if state == 'tool':
        response['tool_calls'] = [{'id': 'pending', 'tool_name': 'test'}]
    elif state != 'error_marker':
        response[state] = True
    log.append(response)
    if state == 'error_marker':
        log.record_error({'message': 'failed'})
    log.record_loop_end({})
    assert not fork_points(log.records())


def test_corrupt_prefix_is_not_silently_skipped(sessions):
    source = sessions.create('broken')
    log = sessions.get_session_log(source)
    point = turn(log)
    data = log._path.read_text().splitlines(True)
    log._path.write_text(data[0] + '{bad}\n' + ''.join(data[1:]))
    with pytest.raises(InvalidForkPoint):
        sessions.fork(source.id, after_seq=point)
    assert len(sessions.list()) == 1


def test_fork_preserves_tool_results_and_plan(sessions):
    source = sessions.create('plan')
    log = sessions.get_session_log(source)
    log.append({'role': 'user', 'content': 'plan'})
    log.append({'role': 'assistant', 'tool_calls': [{'id': 'todo', 'tool_name': 'todo_list---todo_write'}]})
    todos = [{'id': '1', 'content': 'Earlier task', 'status': 'pending'}]
    log.append({'role': 'tool', 'tool_call_id': 'todo', 'content': json.dumps({'status': 'ok', 'todos': todos})})
    log.append({'role': 'assistant', 'content': 'Planned'})
    log.record_turn_checkpoint(2, {'prompt_surface': {'version': 1, 'sources': {'test': 'old'}}})
    point = fork_points(log.records())[-1].after_seq
    (log.directory / 'plan.json').write_text('{"todos":[]}')
    (log.directory / 'prompt_surface.json').write_text('{"sources":{"test":"future"}}')
    child = sessions.fork(source.id, after_seq=point)
    child_log = sessions.get_session_log(child)
    assert json.loads((child_log.directory / 'plan.json').read_text())['todos'] == todos
    assert json.loads((child_log.directory / 'prompt_surface.json').read_text())['sources']['test'] == 'old'
    assert child_log.get_visible_messages()[2]['tool_call_id'] == 'todo'


def test_manual_compaction_is_durable_and_failure_keeps_live_context(tmp_path, monkeypatch):
    import asyncio
    from ms_agent.command.builtin.context_cmds import cmd_compact
    from ms_agent.command.types import CommandContext
    from ms_agent.agent.llm_agent import LLMAgent

    log = SessionLog(tmp_path, 'manual')
    log.append({'role': 'user', 'content': 'inspect'})
    for i in range(4):
        log.append({'role': 'assistant', 'tool_calls': [{'id': str(i), 'tool_name': 'test'}]})
        log.append({'role': 'tool', 'tool_call_id': str(i), 'content': str(i) * 500})
    log.append({'role': 'assistant', 'content': 'done'})
    log.record_turn_checkpoint(4)
    live = ContextAssembler(log).assemble()
    agent = object.__new__(LLMAgent)
    agent.session_log = log
    ctx = CommandContext(raw_input='/compact', command_name='compact',
                         extra={'messages': live, 'persist_context': agent._persist_manual_compaction})
    save = log.commit_compaction
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(log, 'commit_compaction', fail)
    with pytest.raises(OSError):
        asyncio.run(cmd_compact(ctx))
    assert live[2].content == '0' * 500
    monkeypatch.setattr(log, 'commit_compaction', save)
    asyncio.run(cmd_compact(ctx))
    assert live[2].content.startswith('[compacted')
    assert context(SessionLog(tmp_path, 'manual')) == [m.content for m in live]
    assert fork_points(log.records())[-1].context_start == log.last_consolidated


def test_new_format_waits_for_durable_turn_completion(tmp_path):
    log = SessionLog(tmp_path, 'new')
    log.append({'role': 'user', 'content': 'q'})
    log.append({'role': 'assistant', 'content': 'a'})
    assert not fork_points(log.records())
    log.record_turn_checkpoint(1)
    assert len(fork_points(log.records())) == 1
    original = log._path.read_bytes()
    log.record_turn_checkpoint(1)
    assert log._path.read_bytes() == original


@pytest.mark.parametrize('change', ['delete', 'replace', 'append'])
def test_source_change_during_preparation(sessions, monkeypatch, change):
    import importlib
    module = importlib.import_module('ms_agent.project.fork')
    source = sessions.create('Concurrent')
    log = sessions.get_session_log(source)
    point = turn(log)

    def during_copy(records, directory):
        if change == 'delete':
            sessions.delete(source.id)
        elif change == 'replace':
            replacement = log._path.with_suffix('.replacement')
            replacement.write_bytes(log._path.read_bytes())
            replacement.replace(log._path)
        else:
            log.append({'role': 'user', 'content': 'Later input'})

    monkeypatch.setattr(module, '_copy_plan', during_copy)
    if change == 'append':
        child = sessions.fork(source.id, after_seq=point)
        assert context(sessions.get_session_log(child)) == ['question', 'answer']
    else:
        with pytest.raises((FileNotFoundError, InvalidForkPoint)):
            sessions.fork(source.id, after_seq=point)
        assert not any(s.forked_from for s in sessions.list())
    assert not any(p.is_dir() for p in (sessions.sessions_dir.parent / '.fork-staging').iterdir())


def test_concurrent_distinct_requests_have_unique_numbers(sessions):
    source = sessions.create('Topic')
    point = turn(sessions.get_session_log(source))
    with ThreadPoolExecutor(max_workers=4) as pool:
        children = list(pool.map(
            lambda i: sessions.fork(source.id, after_seq=point, request_id=str(i)), range(4)))
    assert {s.name for s in children} == {f'Topic ({i})' for i in range(2, 6)}


@pytest.mark.parametrize('rows', [
    [{'role': 'assistant', 'content': 'No user or summary'}],
    [{'role': 'user', 'content': 'q'}, {'role': 'tool', 'tool_call_id': 'missing'}],
    [{'role': 'user', 'content': 'q'}, {'role': 'assistant', 'tool_calls': [{'id': 'missing'}]}],
])
def test_invalid_saved_compaction_cannot_be_forked(sessions, rows):
    source = sessions.create('Invalid context')
    log = sessions.get_session_log(source)
    turn(log)
    log.commit_compaction([*rows, {'role': 'assistant', 'content': 'done'}], {})
    point = fork_points(log.records())[-1]
    with pytest.raises(InvalidForkPoint):
        sessions.fork(source.id, after_seq=point.after_seq)


def test_fork_retains_image_delivery_without_later_messages(sessions):
    source = sessions.create('Picture')
    log = sessions.get_session_log(source)
    log.append({'role': 'user', 'content': 'Describe', 'attachments': [
        {'path': '/workspace/picture.png', 'name': 'picture.png', 'type': 'image/png'}]})
    log.record_image_delivery([{'path': '/workspace/picture.png', 'delivery': 'delivered'}])
    log.append({'role': 'assistant', 'content': 'A picture'})
    log.record_turn_checkpoint(1)
    point = fork_points(log.records())[-1]
    before = log.get_visible_messages()
    child = sessions.fork(source.id, after_seq=point.after_seq)
    assert sessions.get_session_log(child).get_visible_messages() == before


@pytest.mark.parametrize('decision', ['allow', 'block'])
def test_completion_checkpoint_follows_stop_hook(tmp_path, decision):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from ms_agent.agent.llm_agent import LLMAgent
    from ms_agent.agent.runtime import Runtime
    from ms_agent.hooks.events import HookResult

    log = SessionLog(tmp_path, 'hook')
    log.append({'role': 'user', 'content': 'q'})
    log.append({'role': 'assistant', 'content': 'a'})
    agent = LLMAgent.__new__(LLMAgent)
    agent.session_log = log
    agent.runtime = Runtime(round=1)
    agent._hook_runtime = SimpleNamespace(is_empty=False, run_stop=AsyncMock(
        return_value=HookResult(action=decision, reason='Finish checking')))
    agent.loop_callback = AsyncMock()
    asyncio.run(agent.after_tool_call(ContextAssembler(log).assemble()))
    assert bool(fork_points(log.records())) == (decision == 'allow')
    assert agent.runtime.should_stop == (decision == 'allow')


def test_resume_waits_for_new_input_before_compaction_and_execution(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from omegaconf import OmegaConf
    from ms_agent.agent.llm_agent import LLMAgent
    from ms_agent.agent.runtime import Runtime
    from ms_agent.hooks.events import HookResult
    from ms_agent.llm.utils import Message

    log = SessionLog(tmp_path, 'resume')
    turn(log)
    log.commit_compaction([{'role': 'user', 'content': 'saved summary'},
                           {'role': 'assistant', 'content': 'old answer'}], {})
    log.round = 1
    original = log._path.read_bytes()
    agent = LLMAgent.__new__(LLMAgent)
    agent.config = OmegaConf.create({})
    agent.tag, agent.load_cache = 'test', True
    agent.session_log = log
    agent.runtime = Runtime()
    agent.tool_manager = SimpleNamespace(extra_tools=[])
    agent._skill_runtime, agent._event_sink = None, None
    agent.memory_tools = []
    agent._resolve_interactive = lambda _: True
    agent._has_restorable_history = lambda: True
    for method in ('register_callback_from_config', 'prepare_llm', 'prepare_runtime',
                   '_init_session_log', 'log_output', 'save_history',
                   '_schedule_add_memory_after_task'):
        setattr(agent, method, Mock())
    for method in ('prepare_tools', 'prepare_skills', 'load_memory', 'prepare_rag',
                   'prepare_knowledge_search', '_attach_memory_recall', 'add_memory',
                   'on_task_end', 'cleanup_tools'):
        setattr(agent, method, AsyncMock())
    agent._attach_prompt_update_notice = lambda _: None
    agent._attach_model_switch_notice = lambda _: None
    agent._apply_pending_rollback = lambda messages: messages
    agent.condense_memory = AsyncMock(side_effect=lambda messages: messages)
    agent.context_assembler = ContextAssembler(log)
    agent.context_assembler.assemble = Mock(wraps=agent.context_assembler.assemble)
    agent._hook_runtime = SimpleNamespace(is_empty=False, run_stop=AsyncMock(
        return_value=HookResult(action='allow')))
    seen = []

    async def callback(point, messages):
        if not seen:
            assert log._path.read_bytes() == original
            agent.context_assembler.assemble.assert_not_called()
            assert [m.content for m in messages] == ['saved summary', 'old answer']
            agent._hook_runtime.run_stop.assert_not_called()
            messages.append(Message(role='user', content='new question'))
            agent.runtime.should_stop = False

    async def step(messages):
        seen.append([m.content for m in messages])
        messages.append(Message(role='assistant', content='new answer'))
        yield messages

    agent.loop_callback, agent.step = callback, step
    async def run():
        async for _ in agent.run_loop(None):
            pass
    asyncio.run(run())
    assert seen == [['saved summary', 'old answer', 'new question']]
    assert agent._hook_runtime.run_stop.await_count == 1
    assert context(log) == ['saved summary', 'old answer', 'new question', 'new answer']


@pytest.mark.parametrize('legacy', [False, True])
def test_round_number_is_the_selected_step_not_the_future_session(sessions, legacy):
    source = sessions.create('Rounds')
    log = sessions.get_session_log(source)
    if legacy:
        rows = read_records(log._path)
        rows[0].pop('checkpoint_from_seq')
        log._path.write_text(json.dumps(rows[0]) + '\n')
        log.invalidate_cache()
    log.append({'role': 'user', 'content': 'first'})
    log.append({'role': 'assistant', 'content': 'first reply'})
    if not legacy:
        log.record_turn_checkpoint(0)
    first = fork_points(log.records())[-1]
    assert first.round == 0
    log.append({'role': 'user', 'content': 'second'})
    log.append({'role': 'assistant', 'tool_calls': [{'id': 'one', 'tool_name': 'test'}]})
    log.append({'role': 'tool', 'tool_call_id': 'one', 'content': 'result'})
    log.append({'role': 'assistant', 'content': 'second reply'})
    if not legacy:
        log.record_turn_checkpoint(2)
    second = fork_points(log.records())[-1]
    assert second.round == 2
    log.round = 100
    for point in (first, second):
        child = sessions.fork(source.id, after_seq=point.after_seq)
        assert sessions.get_session_log(child).round == point.round
