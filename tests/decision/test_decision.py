import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from omegaconf import OmegaConf

from ms_agent.config.decision import DEFAULTS, DecisionSettings, profile
from ms_agent.decision.client import SystemOneClient
from ms_agent.decision.types import DecisionCapabilities, DecisionError, DecisionRequest, DecisionResponse
from ms_agent.decision.supervisor import DecisionSupervisor
from ms_agent.project.session import ExecutionModeLocked, SessionManager
from ms_agent.project.types import Project
from ms_agent.session.context_assembler import ContextAssembler
from ms_agent.session.session_log import SessionLog
from ms_agent.session.strategies.decision_compactor import DecisionContextCompactor, ContextBudgetExceeded
from ms_agent.tools.context_read import ContextReadTool


class Judge:
    capabilities = DecisionCapabilities()

    def __init__(self, p=0, fail=False, gate=None):
        self.p, self.fail, self.gate = p, fail, gate
        self.calls = []

    async def decide(self, request, **kwargs):
        self.calls.append(request)
        if self.gate:
            await self.gate.wait()
        if self.fail:
            raise DecisionError('unavailable')
        answers = {}
        for key, q in request.questions.items():
            if q['type'] == 'noul':
                answers[key] = {'type': 'noul', 'noul': self.p}
            else:
                choice = next(k for k in q['criteria'] if k != 'none')
                answers[key] = {'type': 'choice', 'choice': choice}
        return DecisionResponse(answers)


class Summarizer:

    def __init__(
            self,
            response='Retain the task and verification; irrelevant logs omitted.'
    ):
        self.response, self.calls = response, []

    def generate(self, messages, **kwargs):
        self.calls.append(messages)
        return SimpleNamespace(content=self.response)


def log_fixture(tmp_path, size=3000):
    log = SessionLog(str(tmp_path), session_key='test')
    log.append({'role': 'system', 'content': 'Follow the user requirements.'})
    log.append({
        'role': 'user',
        'content': 'Fix the bug and verify the regression test.'
    })
    for i in range(3):
        log.append({
            'role':
            'assistant',
            'content':
            '',
            'tool_calls': [{
                'id': f'c{i}',
                'tool_name': 'read',
                'arguments': '{}'
            }]
        })
        log.append({
            'role': 'tool',
            'content': f'UNIQUE_SOURCE_{i} ' + 'x' * size,
            'tool_call_id': f'c{i}',
            'name': 'read'
        })
    return log


def compactor(log, judge, summary=None):
    strategy = DecisionContextCompactor(
        summary or Summarizer(),
        client=judge,
        options={'protect_recent_groups': 1},
        log=log)
    return strategy, ContextAssembler(log, [strategy], {
        'context_limit': 4000,
        'reserved_buffer': 500
    })


def test_transport_and_rounding():

    async def run():

        def handler(req):
            assert req.url.path == '/v1/systemone'
            assert req.headers['authorization'] == 'Bearer fixture-key'
            body = json.loads(req.content)
            assert 'messages' not in body
            return httpx.Response(
                200, json={'answers': {
                    'q': {
                        'type': 'noul',
                        'noul': .9
                    }
                }})

        client = SystemOneClient(
            base_url='https://example.test/v1',
            api_key='fixture-key',
            model='decision',
            transport=httpx.MockTransport(handler))
        answer = await client.decide(
            DecisionRequest({},
                            {'q': {
                                'type': 'noul',
                                'instructions': 'Test'
                            }}))
        assert answer.answers['q']['noul'] == .9
        await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize('body', [
    '{"answers":{"q":{"type":"noul","noul":NaN}}}',
    '{"answers":{"q":{"type":"noul","noul":2}}}',
    '{"answers":{"q":{"type":"noul","noul":true}}}',
    '{"answers":{"wrong":{"type":"noul","noul":1}}}',
    '{"answers":{"q":{"type":"choice","choice":"x"}}}',
    '{"answers":{},"answers":{}}', 'null', '{}', 'not-json'
])
def test_invalid_answers(body):
    with pytest.raises(DecisionError):
        DecisionResponse.parse(
            body,
            DecisionRequest({},
                            {'q': {
                                'type': 'noul',
                                'instructions': 'Test'
                            }}))


def test_selection_skips_summary_and_recovers_original(tmp_path):

    async def run():
        log = log_fixture(tmp_path)
        judge, summary = Judge(), Summarizer()
        _, assembler = compactor(log, judge, summary)
        await assembler.aassemble()
        assert len(judge.calls) == 1
        assert not summary.calls
        assert len(log.get_compaction_events()) == 1
        visible = log.get_visible_messages()
        previews = [r for r in visible if r.get('decision_preview')]
        assert len(previews) == 2
        row = previews[0]
        tool = ContextReadTool(OmegaConf.create({}), log)
        result = json.loads(await tool.call_tool(
            'context',
            tool_name='context_read',
            tool_args={
                'ref': f"ctx:{row['origin_seq']}:{row['tool_call_id']}",
                'limit': 8000
            }))
        assert result['content'].startswith('UNIQUE_SOURCE_0')
        assert len(result['content']) > 3000
        restored = SessionLog(str(tmp_path), session_key='test')
        assert any(
            r.get('decision_preview') for r in restored.get_visible_messages())

    asyncio.run(run())


@pytest.mark.parametrize('judge', [Judge(p=1), Judge(fail=True)])
def test_summary_uses_original_not_preview(tmp_path, judge):

    async def run():
        log = log_fixture(tmp_path)
        summary = Summarizer()
        _, assembler = compactor(log, judge, summary)
        await assembler.aassemble()
        assert summary.calls
        body = summary.calls[0][0].content
        assert 'UNIQUE_SOURCE_0' in body and 'x' * 300 in body
        assert '[Tool output preview' not in body
        assert len(log.get_compaction_events()) == 1
        assert log.get_compaction_events()[0]['strategy'] == 'llm_summary'

    asyncio.run(run())


def test_failed_summary_is_bounded(tmp_path):

    async def run():
        log = log_fixture(tmp_path, size=4000)
        summary = Summarizer('')
        _, assembler = compactor(log, Judge(fail=True), summary)
        for _ in range(2):
            with pytest.raises(ContextBudgetExceeded):
                await assembler.aassemble()
        assert len(summary.calls) == 1
        assert not log.get_compaction_events()

    asyncio.run(run())


def test_cancel_does_not_commit_or_summarize(tmp_path):

    async def run():
        log = log_fixture(tmp_path)
        summary, gate = Summarizer(), asyncio.Event()
        _, assembler = compactor(log, Judge(gate=gate), summary)
        task = asyncio.create_task(assembler.aassemble())
        await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not summary.calls and not log.get_compaction_events()

    asyncio.run(run())


def test_changed_snapshot_does_not_commit(tmp_path):

    async def run():
        log = log_fixture(tmp_path)
        gate = asyncio.Event()
        _, assembler = compactor(log, Judge(gate=gate))
        task = asyncio.create_task(assembler.aassemble())
        await asyncio.sleep(.01)
        log.append({'role': 'user', 'content': 'Changed task'})
        gate.set()
        await task
        assert not log.get_compaction_events()

    asyncio.run(run())


def test_finish_correction_survives_restart_and_stops_once(tmp_path):

    async def run():
        log = log_fixture(tmp_path, size=20)
        judge = Judge(p=1)
        for i in range(3):
            guard = DecisionSupervisor(judge, DEFAULTS['supervision'], log)
            feedback = await guard.check(finishing=True, reply=f'Complete {i}')
            assert bool(feedback) == (i == 0)
        assert len(judge.calls) == 2

    asyncio.run(run())


def test_success_supersedes_matching_failure(tmp_path):
    from ms_agent.decision.evidence import evidence
    log = log_fixture(tmp_path, size=20)
    log.append({
        'role':
        'assistant',
        'tool_calls': [{
            'id': 'x',
            'tool_name': 'check',
            'arguments': '{}'
        }]
    })
    log.append({
        'role': 'tool',
        'name': 'check',
        'tool_call_id': 'x',
        'content': '{"exit_code": 1}'
    })
    assert evidence(log.records()).unresolved
    log.append({
        'role':
        'assistant',
        'tool_calls': [{
            'id': 'y',
            'tool_name': 'check',
            'arguments': '{}'
        }]
    })
    log.append({
        'role': 'tool',
        'name': 'check',
        'tool_call_id': 'y',
        'content': '{"exit_code": 0}'
    })
    assert not evidence(log.records()).unresolved


def settings_fixture(tmp_path):
    (tmp_path / 'settings.json').write_text(
        json.dumps({
            'providers': {
                'fixture': {
                    'api_key': 'private-test-key',
                    'base_url': 'https://example.test/v1',
                    'models': ['chat']
                }
            },
            'decision': {
                'provider': 'fixture',
                'model': 'decision-model-preview'
            }
        }))
    return DecisionSettings(tmp_path)


def test_mode_lock_and_default_isolation(tmp_path):
    settings = settings_fixture(tmp_path)
    manager = SessionManager(
        Project('p', 'p', str(tmp_path / 'work')), base_dir=tmp_path)
    first = manager.create()
    manager.set_execution_mode(first.id, 'decision')
    second = manager.create()
    manager.set_execution_mode(second.id, 'standard')
    frozen = manager.prepare_execution(first.id)
    assert frozen.execution_mode == 'decision'
    assert 'private-test-key' not in json.dumps(frozen.execution_profile)
    assert settings.get()['default_execution_mode'] == 'standard'
    with pytest.raises(ExecutionModeLocked):
        manager.set_execution_mode(first.id, 'standard')
    manager.set_execution_mode(first.id, 'decision')
    assert settings.get()['default_execution_mode'] == 'standard'
    with pytest.raises(ValueError):
        manager.update(first.id, execution_mode='standard')


@pytest.mark.parametrize('patch', [{
    'context': {
        'target_ratio': .99
    }
}, {
    'supervision': {
        'max_reflections': -1
    }
}, {
    'protocol': 'chat'
}, {
    'policy_version': 'v2'
}])
def test_invalid_configuration(patch):
    with pytest.raises(ValueError):
        profile(patch)


def test_all_unresolved_errors_protected_when_decision_coverage_is_bounded(
        tmp_path):
    from ms_agent.decision.evidence import evidence
    log = SessionLog(tmp_path, 'failures')
    log.append({'role': 'user', 'content': 'Repair all checks'})
    seqs = set()
    for i in range(14):
        log.append({
            'role':
            'assistant',
            'tool_calls': [{
                'id': str(i),
                'tool_name': 'check',
                'arguments': {
                    'index': i
                }
            }]
        })
        seqs.add(
            log.append({
                'role': 'tool',
                'tool_call_id': str(i),
                'content': '{"return_code": 1}'
            }))
    snapshot = evidence(log.records())
    assert not snapshot.covered
    assert snapshot.protected_seqs == seqs
    assert len(snapshot.state()['evidence']) <= 20


def test_unknown_call_cannot_clear_another_failure(tmp_path):
    from ms_agent.decision.evidence import evidence
    log = SessionLog(tmp_path, 'unknown')
    log.append({'role': 'user', 'content': 'Repair'})
    log.append({
        'role': 'tool',
        'name': 'shell',
        'tool_call_id': 'a',
        'content': '{"return_code": 1}'
    })
    log.append({
        'role': 'tool',
        'name': 'shell',
        'tool_call_id': 'b',
        'content': '{"return_code": 0}'
    })
    assert len(evidence(log.records()).unresolved) == 1


def test_internal_feedback_is_one_task_and_only_accepted_reply_is_forkable(
        tmp_path):
    from ms_agent.session.replay import fork_points
    from ms_agent.decision.evidence import evidence
    log = SessionLog(tmp_path, 'feedback')
    user = log.append({'role': 'user', 'content': 'Fix and test'})
    log.append({'role': 'assistant', 'content': 'Done too early'})
    log.append({
        'role': 'user',
        'content': 'Verify first',
        'decision_feedback': True
    })
    assert not fork_points(log.records(), require_checkpoint=False)
    assert evidence(log.records()).task_id == str(user)
    final = log.append({'role': 'assistant', 'content': 'Verified now'})
    log.record_turn_checkpoint(2)
    assert [p.assistant_seq for p in fork_points(log.records())] == [final]


def test_cancel_during_memory_flush_leaves_no_committed_view(tmp_path):

    async def run():
        log = log_fixture(tmp_path)
        _, assembler = compactor(log, Judge())
        started, release = asyncio.Event(), asyncio.Event()

        async def flush(_):
            started.set()
            await release.wait()

        assembler._memory_flush_callback = flush
        task = asyncio.create_task(assembler.aassemble())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not any(
            r.get('_type') == 'compaction_commit' for r in log.records())

    asyncio.run(run())


def test_capacity_errors_are_not_retried():
    from ms_agent.utils.llm_utils import is_retryable_error
    assert not is_retryable_error(
        ContextBudgetExceeded('Protected input cannot fit'))


def test_client_deadline_cancels_transport():

    async def run():
        cancelled = asyncio.Event()

        async def handler(_):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        client = SystemOneClient(
            base_url='https://example.test/v1',
            api_key='test',
            model='test',
            transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(DecisionError, match='timed out'):
                await client.decide(
                    DecisionRequest(
                        {}, {'q': {
                            'type': 'noul',
                            'instructions': 'q'
                        }}),
                    timeout=.02)
            assert cancelled.is_set()
        finally:
            await client.aclose()

    asyncio.run(run())


def test_cancel_summary_interrupts_stream_and_closes_late_result():
    import threading
    from ms_agent.session.strategies.decision_compactor import collect_summary

    async def run():
        opening, release, closed = threading.Event(), threading.Event(
        ), threading.Event()

        class Stream:

            def close(self):
                closed.set()

        class SlowModel:

            def generate(self, *args, **kwargs):
                opening.set()
                release.wait(2)
                return Stream()

            def interrupt(self):
                release.set()

        task = asyncio.create_task(
            collect_summary(SlowModel(), 'summary', 500))
        assert await asyncio.to_thread(opening.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(closed.wait, 2)

    asyncio.run(run())


def test_review_precedes_memory_checkpoint_and_waiting(tmp_path):
    from unittest.mock import AsyncMock
    from ms_agent.agent.llm_agent import LLMAgent
    from ms_agent.agent.runtime import Runtime
    from ms_agent.llm.utils import Message
    from ms_agent.session.replay import fork_points

    async def run():
        log = log_fixture(tmp_path, size=20)
        log.append({'role': 'assistant', 'content': 'Everything is finished.'})
        agent = LLMAgent.__new__(LLMAgent)
        agent.session_log, agent.runtime = log, Runtime(round=2)
        agent.callbacks, agent.max_chat_round = [], 10
        agent._hook_runtime = None
        agent._decision_supervisor = DecisionSupervisor(
            Judge(p=1), DEFAULTS['supervision'], log)
        agent.add_memory, agent.loop_callback = AsyncMock(), AsyncMock()
        messages = ContextAssembler(log).assemble()
        await agent.after_tool_call(messages)
        assert messages[-1]._decision_feedback
        agent.add_memory.assert_not_called()
        assert not fork_points(log.records())
        log.append(agent._msg_to_dict(messages[-1]))
        messages.append(
            Message(
                role='assistant',
                content='Rechecked; cannot proceed without access.'))
        log.append(agent._msg_to_dict(messages[-1]))
        await agent.after_tool_call(messages)
        assert agent.runtime.should_stop
        agent.add_memory.assert_awaited_once()
        assert len(fork_points(log.records())) == 1

    asyncio.run(run())


def test_pending_rollback_discards_completed_context_candidate(tmp_path):

    async def run():
        log = log_fixture(tmp_path)
        _, assembler = compactor(log, Judge())
        before = log._path.read_bytes()
        await assembler.aassemble(is_current=lambda: False)
        assert log._path.read_bytes() == before

    asyncio.run(run())
