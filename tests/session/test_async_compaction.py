"""Deterministic compaction scheduling tests: no credentials or model network I/O."""
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from functools import wraps
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.llm import io
from ms_agent.llm.utils import Message
from ms_agent.session.context_assembler import ContextAssembler
from ms_agent.session.session_log import SessionLog
from ms_agent.session.strategies.summary_compactor import SummaryCompactor
from ms_agent.session.strategies.tool_pruner import ToolOutputPruner
from ms_agent.ui.events import ContextCompacted, ErrorRaised


CONFIG = {
    'context_limit': 4000, 'input_limit': 3744, 'output_reserve': 256,
    'compression_threshold': 3400, 'compression_ratio': .85,
    'prune_protect': 0,
}
USAGE = {'model': 'fake', 'usage': {'prompt_tokens': 100,
                                  'completion_tokens': 10}}


def run_async(test):
    @wraps(test)
    def run(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))
    return run


def history(log):
    log.append_messages([
        {'role': 'system', 'content': 'Keep the instructions.'},
        {'role': 'user', 'content': 'old ' * 1000},
        {'role': 'assistant', 'content': '', 'id': 'response-id',
         'reasoning_content': 'reason', 'reasoning_signature': 'signature',
         'tool_calls': [{'id': 'call-1', 'tool_name': 'read',
                         'arguments': '{"path":"file.txt"}'}]},
        {'role': 'tool', 'content': 'file contents', 'name': 'read',
         'tool_call_id': 'call-1'},
        {'role': 'assistant', 'content': 'done', 'prompt_tokens': 3600,
         'completion_tokens': 10},
        {'role': 'user', 'content': 'latest'},
    ])


def snapshot(log):
    return (log._path.read_bytes(), log._meta_path.read_bytes(),
            deepcopy(log.get_all_messages()), log.last_consolidated)


class GateLLM:
    """The first summary returns only when the test explicitly releases it."""

    def __init__(self, *, release_on_interrupt=False, fail_late=False):
        self.loop = asyncio.get_running_loop()
        self.owner = threading.get_ident()
        self.entered = asyncio.Event()
        self.interrupted = asyncio.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.release_on_interrupt = release_on_interrupt
        self.fail_late = fail_late
        self.threads = []
        self.close_threads = []

    def generate(self, messages, tools=None, **kwargs):
        # A generator also detects accidental cross-thread generator.close().
        self.threads.append(threading.get_ident())
        try:
            if len(self.threads) == 1:
                self.loop.call_soon_threadsafe(self.entered.set)
                # Fail fast on the old synchronous path, rather than hang pytest.
                assert threading.get_ident() != self.owner, 'summary blocked event loop'
                assert self.release.wait(5), 'test did not release summary'
                if self.fail_late:
                    raise RuntimeError('late summary failure')
            yield Message('assistant', 'Concise prior findings.',
                          usage_records=[deepcopy(USAGE)])
        finally:
            self.close_threads.append(threading.get_ident())
            self.finished.set()

    def interrupt(self):
        self.interrupted.set()
        if self.release_on_interrupt:
            self.release.set()


class Compact:
    name = 'force_compact'

    def apply(self, visible, all_msgs, config):
        self._usage_records = [deepcopy(USAGE)]
        return visible[-1:], {'tokens_before': 100, 'tokens_after': 10,
                              'summary': 'summary'}


def make_agent(log, strategies, memory_tools=()):
    """Run the real run_loop, replacing only setup and the next model step."""
    agent = LLMAgent.__new__(LLMAgent)
    agent.config = OmegaConf.create({'max_chat_round': 10})
    agent.runtime = NS(round=1, should_stop=False)
    agent.tag = 'compaction-test'
    agent.load_cache = True
    agent.session_log = log
    agent.llm = next((s.llm for s in strategies if hasattr(s, 'llm')), None)
    agent.memory_tools = list(memory_tools)
    agent._on_user_turn = None
    agent._skill_runtime = None
    agent._event_sink = NS(emit=Mock())
    agent.tool_manager = NS(extra_tools=[], get_tools=AsyncMock(return_value=[]))
    for method in ('register_callback_from_config', 'prepare_llm',
                   'prepare_runtime', '_init_session_log', 'log_output',
                   'save_history', '_schedule_add_memory_after_task'):
        setattr(agent, method, Mock())
    for method in ('prepare_tools', 'prepare_skills', 'load_memory',
                   'prepare_rag', 'prepare_knowledge_search', 'add_memory',
                   'after_tool_call', 'on_task_end', 'cleanup_tools'):
        setattr(agent, method, AsyncMock())
    agent._resolve_interactive = Mock(return_value=False)
    agent._build_assembler_config = Mock(side_effect=lambda *a: dict(CONFIG))
    agent._apply_pending_rollback = lambda messages: messages
    agent.condense_memory = AsyncMock(side_effect=lambda messages: messages)
    agent.step_started = Mock()

    async def step(messages):
        agent.step_started(messages)
        agent.runtime.should_stop = True
        yield messages

    agent.step = step
    agent.context_assembler = ContextAssembler(
        log, strategies, dict(CONFIG), agent._make_memory_flush_callback())
    return agent


async def run_agent(agent):
    return [messages async for messages in agent.run_loop('unused')]


async def stop(task):
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@run_async
async def test_slow_summary_allows_heartbeat_and_second_request(tmp_path):
    log = SessionLog(tmp_path, 'slow')
    history(log)
    before = snapshot(log)
    llm = GateLLM()
    agent = make_agent(log, [SummaryCompactor(llm)])
    task = asyncio.create_task(run_agent(agent))
    try:
        await asyncio.wait_for(llm.entered.wait(), 2)
        assert not task.done()
        assert llm.threads[0] != threading.get_ident()
        tick = asyncio.Event()
        asyncio.get_running_loop().call_soon(tick.set)
        await asyncio.wait_for(tick.wait(), 1)
        other_log = SessionLog(tmp_path, 'second')
        other_log.append({'role': 'user', 'content': 'another request'})
        other = make_agent(other_log, [])
        await asyncio.wait_for(run_agent(other), 1)
        other.step_started.assert_called_once()
        agent.step_started.assert_not_called()
        assert snapshot(log) == before
        llm.release.set()
        await asyncio.wait_for(task, 2)
        agent.step_started.assert_called_once()
        events = [c.args[0] for c in agent._event_sink.emit.call_args_list]
        assert sum(isinstance(e, ContextCompacted) for e in events) == 1
        assert log.get_compaction_events()[0]['usage_records'] == [USAGE]
        assert llm.close_threads == llm.threads
    finally:
        llm.release.set()
        await stop(task)


@pytest.mark.parametrize('fail_late', [False, True])
@run_async
async def test_cancel_drains_late_summary_without_commit_or_next_step(tmp_path, fail_late):
    log = SessionLog(tmp_path)
    history(log)
    before = snapshot(log)
    llm = GateLLM(fail_late=fail_late)
    strategy = SummaryCompactor(llm)
    memory = NS(flush=AsyncMock())
    agent = make_agent(log, [strategy], [memory])
    task = asyncio.create_task(run_agent(agent))
    try:
        await asyncio.wait_for(llm.entered.wait(), 2)
        task.cancel()
        await asyncio.wait_for(llm.interrupted.wait(), 1)
        assert snapshot(log) == before
        assert not llm.finished.is_set()
        # Repeated cancellation must not detach a still-running worker.
        task.cancel()
        barrier = asyncio.Event()
        asyncio.get_running_loop().call_soon(barrier.set)
        await barrier.wait()
        assert not task.done()
        llm.release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert llm.finished.is_set()
        assert llm.close_threads == llm.threads
        assert snapshot(log)[1:] == before[1:]
        assert log.get_context_operations()[-1]['status'] == 'cancelled'
        assert not strategy._usage_records
        memory.flush.assert_not_awaited()
        agent.step_started.assert_not_called()
        agent._event_sink.emit.assert_not_called()
        # Reuse the SAME strategy/provider and log; no late usage is charged.
        llm.fail_late = False
        await asyncio.wait_for(run_agent(agent), 2)
        assert len(log.get_compaction_events()) == 1
        assert log.get_compaction_events()[0]['usage_records'] == [USAGE]
    finally:
        llm.release.set()
        await stop(task)


@pytest.mark.parametrize('provider_facade', [False, True])
@run_async
async def test_interrupt_releases_summary_and_does_not_use_host_executor(
        tmp_path, monkeypatch, provider_facade):
    from ms_agent.llm.router import LLMProvider

    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
    log = SessionLog(tmp_path)
    history(log)
    before = snapshot(log)
    llm = GateLLM(release_on_interrupt=True)
    provider = LLMProvider(OmegaConf.create({'llm': {'model': 'fake'}}),
                           spec=None, transport=llm) if provider_facade else llm
    with ThreadPoolExecutor(max_workers=1) as pool:
        monkeypatch.setattr(io, '_executor', pool)
        task = asyncio.create_task(ContextAssembler(
            log, [SummaryCompactor(provider)], dict(CONFIG)).assemble_async())
        try:
            await asyncio.wait_for(llm.entered.wait(), 2)
            assert await asyncio.wait_for(asyncio.to_thread(lambda: 'storage'), 1) == 'storage'
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            assert llm.interrupted.is_set() and llm.finished.is_set()
            assert snapshot(log) == before
            assert await asyncio.wait_for(
                io.run_in_llm_executor(lambda: 'next request'), 1) == 'next request'
        finally:
            llm.release.set()
            await stop(task)


@run_async
async def test_cancel_queued_strategy_never_starts_model(tmp_path, monkeypatch):
    log = SessionLog(tmp_path)
    history(log)
    before = snapshot(log)
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    llm = NS(interrupt=Mock(), generate=Mock())

    def occupy_worker():
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5), 'test did not release executor'

    with ThreadPoolExecutor(max_workers=1) as pool:
        monkeypatch.setattr(io, '_executor', pool)
        occupier = asyncio.create_task(io.run_in_llm_executor(occupy_worker))
        await asyncio.wait_for(entered.wait(), 2)
        task = asyncio.create_task(ContextAssembler(
            log, [SummaryCompactor(llm)], dict(CONFIG)).assemble_async())
        try:
            barrier = asyncio.Event()
            loop.call_soon(barrier.set)
            await barrier.wait()
            task.cancel()
            barrier.clear()
            loop.call_soon(barrier.set)
            await barrier.wait()
            llm.interrupt.assert_called_once()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            llm.generate.assert_not_called()
            assert snapshot(log) == before
        finally:
            release.set()
            await stop(task)
            await occupier


@run_async
async def test_flush_is_awaited_before_commit_and_preserves_tool_fields(tmp_path):
    log = SessionLog(tmp_path)
    history(log)
    before = snapshot(log)
    entered, release = asyncio.Event(), asyncio.Event()
    received = []

    async def flush(messages):
        received.extend(messages)
        entered.set()
        await release.wait()
        assert snapshot(log)[1:] == before[1:]

    memory = NS(flush=AsyncMock(side_effect=flush))
    agent = make_agent(log, [Compact()], [memory])
    task = asyncio.create_task(run_agent(agent))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert snapshot(log)[1:] == before[1:]
        agent.step_started.assert_not_called()
        agent._event_sink.emit.assert_not_called()
        assert received[1].tool_calls[0]['arguments'] == '{"path":"file.txt"}'
        assert received[1].id == 'response-id'
        assert received[1].reasoning_signature == 'signature'
        assert received[2].tool_call_id == 'call-1'
        assert received[2].name == 'read'
        release.set()
        await asyncio.wait_for(task, 2)
        assert log.last_consolidated > before[-1]
        memory.flush.assert_awaited_once()
        agent.step_started.assert_called_once()
    finally:
        release.set()
        await stop(task)


@run_async
async def test_flush_failure_allows_compaction_and_retries_original_sources(tmp_path):
    log = SessionLog(tmp_path, 'retry-memory')
    history(log)
    originals = deepcopy(log.get_all_messages())
    memory = NS(flush=AsyncMock(side_effect=RuntimeError('flush failed')))
    agent = make_agent(log, [Compact()], [memory])
    await run_agent(agent)
    assert log.last_consolidated > 0
    assert log.get_all_messages()[:len(originals)] == originals
    assert log.get_compaction_events()[0]['memory']['status'] == 'failed'
    agent.step_started.assert_called_once()
    assert any(isinstance(c.args[0], ContextCompacted)
               for c in agent._event_sink.emit.call_args_list)
    reopened = SessionLog(tmp_path, 'retry-memory')
    flush = AsyncMock(return_value='updated')
    await ContextAssembler(reopened, [Compact()], memory_flush_callback=flush).assemble_async()
    assert flush.call_args.args[0] == originals[1:]
    assert reopened.get_memory_flushes()[0]['status'] == 'updated'
    await ContextAssembler(reopened, [Compact()], memory_flush_callback=flush).assemble_async()
    flush.assert_awaited_once()


@run_async
async def test_cancel_during_flush_preserves_log_and_cancels_owned_work(tmp_path):
    log = SessionLog(tmp_path)
    history(log)
    before = snapshot(log)
    entered, finished = asyncio.Event(), asyncio.Event()

    async def flush(messages):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    agent = make_agent(log, [Compact()], [NS(flush=flush)])
    task = asyncio.create_task(run_agent(agent))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert finished.is_set()
        assert snapshot(log)[1:] == before[1:]
        agent.step_started.assert_not_called()
    finally:
        await stop(task)


@pytest.mark.parametrize('wrapped', [False, True])
def test_sync_assemble_explicitly_rejects_async_flush(tmp_path, wrapped):
    log = SessionLog(tmp_path)
    history(log)
    before = snapshot(log)
    flush = AsyncMock()
    callback = (lambda messages: flush(messages)) if wrapped else flush
    assembler = ContextAssembler(log, [Compact()], memory_flush_callback=callback)
    with pytest.raises(TypeError, match='assemble_async'):
        assembler.assemble()
    assert snapshot(log)[1:] == before[1:]
    flush.assert_not_awaited()


def test_sync_flush_failure_preserves_originals_and_allows_compaction(tmp_path):
    log = SessionLog(tmp_path)
    history(log)
    before = deepcopy(log.get_all_messages())
    flush = Mock(side_effect=RuntimeError('flush failed'))
    ContextAssembler(log, [Compact()], memory_flush_callback=flush).assemble()
    assert log.get_all_messages()[:len(before)] == before
    assert log.last_consolidated > 0
    assert log.get_compaction_events()[0]['memory']['status'] == 'failed'


@pytest.mark.parametrize('kind', ['prune', 'summary', 'retained'])
@run_async
async def test_async_and_sync_share_commit_budget_usage_semantics(tmp_path, kind):
    def build(key):
        log = SessionLog(tmp_path, key)
        history(log)
        if kind == 'prune':
            log.append_messages([
                {'role': 'assistant', 'content': '', 'tool_calls': [
                    {'id': 'large', 'tool_name': 'read', 'arguments': '{}'}]},
                {'role': 'tool', 'tool_call_id': 'large', 'content': 'X' * 16000},
                {'role': 'user', 'content': 'newest'},
            ])
        response = Message('assistant', '' if kind == 'retained' else 'A short summary.',
                           usage_records=[deepcopy(USAGE)])
        strategies = [ToolOutputPruner()] if kind == 'prune' else [
            SummaryCompactor(NS(generate=Mock(return_value=response)))]
        flush = Mock()
        assembler = ContextAssembler(log, strategies, dict(CONFIG), flush)
        return log, assembler, flush

    sync_log, sync, sync_flush = build('sync')
    async_log, asynchronous, async_flush = build('async')
    owner = threading.get_ident()
    for method in ('append', 'record_compaction', '_update_meta'):
        original = getattr(async_log, method)

        def checked(*args, _method=original, **kwargs):
            assert threading.get_ident() == owner, 'log commit escaped to worker'
            return _method(*args, **kwargs)
        setattr(async_log, method, checked)
    expected = sync.assemble()
    actual = await asynchronous.assemble_async()
    assert actual == expected
    assert async_log.last_consolidated == sync_log.last_consolidated
    assert async_flush.call_count == sync_flush.call_count == (kind != 'retained')
    events = [{k: v for k, v in e.items() if k != 'timestamp'}
              for e in async_log.get_compaction_events()]
    assert events == [{k: v for k, v in e.items() if k != 'timestamp'}
                      for e in sync_log.get_compaction_events()]
    assert len(events) == 1
    assert events[0]['budget']['input_limit'] == CONFIG['input_limit']
    assert events[0]['usage_records'] == ([] if kind == 'prune' else [USAGE] * (2 if kind == 'retained' else 1))
    if kind == 'retained':
        assert events[0]['status'] == 'retained'
    else:
        # Restored compacted messages never double-bill original/summary usage.
        assert all(not m.usage_records and not m.prompt_tokens for m in actual)
    assert async_log.get_all_messages()[1]['content'] == 'old ' * 1000


@run_async
async def test_multiple_strategies_do_not_flush_retained_sources_twice(tmp_path):
    log = SessionLog(tmp_path)
    history(log)
    originals = deepcopy(log.get_all_messages())
    flush = AsyncMock(return_value='unchanged')
    await ContextAssembler(log, [Compact(), Compact()],
                           memory_flush_callback=flush).assemble_async()
    flush.assert_awaited_once_with(originals[1:])
    events = log.get_compaction_events()
    assert len(events) == 2
    assert events[0]['boundary_before'] == 0
    assert events[1]['boundary_before'] > events[0]['boundary_after']
    assert len(log.get_all_messages()) == 8


@run_async
async def test_cancel_as_strategy_returns_never_flushes_or_commits(tmp_path):
    log = SessionLog(tmp_path)
    history(log)
    before = snapshot(log)
    loop = asyncio.get_running_loop()
    strategy = Compact()
    apply = strategy.apply

    def cancel_on_return(*args):
        result = apply(*args)
        loop.call_soon_threadsafe(task.cancel)
        return result

    strategy.apply = cancel_on_return
    flush = AsyncMock()
    assembler = ContextAssembler(log, [strategy], memory_flush_callback=flush)
    task = asyncio.create_task(assembler.assemble_async())
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert snapshot(log) == before
    assert not strategy._usage_records
    flush.assert_not_awaited()


def test_context_snapshot_and_paused_request_survive_restore(tmp_path):
    from ms_agent.session.context_status import context_snapshot
    log = SessionLog(tmp_path, 'paused')
    log.append_messages([{'role': 'system', 'content': 'instructions'},
                         {'role': 'user', 'content': 'original request'}])
    tail = log.get_all_messages()[-1]['seq']
    log.set_metadata_field('pending_context', {'id': 'request', 'status': 'paused', 'tail_seq': tail})
    log.append({'role': 'assistant', 'content': '', 'errored': True})
    snap = context_snapshot(log.get_visible_messages(), CONFIG, tools=[{'name': 'read'}])
    log.set_metadata_field('context_snapshot', snap)
    restored = SessionLog(tmp_path, 'paused')
    assert restored.get_metadata()['context_snapshot']['buckets'] == snap['buckets']
    assert sum(snap['buckets'].values()) == snap['input_tokens']
    assert snap['output_reserve'] == 256
    restored.resume_pending_context()
    again = SessionLog(tmp_path, 'paused')
    assert [m['role'] for m in again.get_visible_messages()] == ['system', 'user']
    assert again.get_visible_messages()[-1]['content'] == 'original request'
    assert again.get_metadata()['pending_context']['status'] == 'resuming'
    with pytest.raises(ValueError, match='No paused'):
        again.resume_pending_context()
    assert sum(m['role'] == 'user' for m in again.get_all_messages()) == 1


@run_async
async def test_resume_input_does_not_append_a_second_user_turn(tmp_path):
    from ms_agent.callbacks.input_callback import InputCallback
    from ms_agent.ui.input import ResumeContext
    from ms_agent.command import CommandRouter
    log = SessionLog(tmp_path, 'input')
    log.append({'role': 'user', 'content': 'original'})
    log.set_metadata_field('pending_context', {'id': 'request', 'status': 'paused', 'tail_seq': 0})
    log.append({'role': 'assistant', 'content': '', 'errored': True})
    callback = InputCallback(OmegaConf.create({}), command_router=CommandRouter(),
                             input_source=NS(read_prompt=AsyncMock(return_value=ResumeContext())))
    runtime = NS(resume_pending_context=log.resume_pending_context)
    messages = [Message('user', 'original'), Message('assistant', '')]
    await callback.after_tool_call(runtime, messages)
    assert len(messages) == 2
    assert runtime.resume_context_requested
    assert log.get_visible_messages()[-1]['content'] == 'original'
