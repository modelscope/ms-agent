"""Decision mode invariants across shared budgets, memory and steering."""
import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from omegaconf import OmegaConf

from ms_agent.decision.evidence import evidence
from ms_agent.llm.utils import Message
from ms_agent.session.context_assembler import ContextAssembler
from ms_agent.session.strategies.decision_compactor import (
    DecisionContextCompactor, count_tokens)
from test_decision import Judge, Summarizer, log_fixture


def test_steering_extends_objective_without_resetting_review_budget(tmp_path):
    log = log_fixture(tmp_path, size=10)
    before = evidence(log.records())
    log.append({'role': 'user', 'content': 'Also check the return code.', 'delivery': 'steer'})
    after = evidence(log.records())
    assert after.task_id == before.task_id
    assert before.objective in after.objective
    assert 'Also check' in after.objective
    assert len(after.tools) == len(before.tools)


def test_selection_invalidates_usage_and_preserves_inline_images(tmp_path):
    async def run():
        log = log_fixture(tmp_path)
        image = [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}}]
        log.append({'role': 'tool', 'content': image, 'tool_call_id': 'image'})
        # Independent valid image exchange.
        rows = log.get_all_messages()[:-1]
        rows.extend([{'role': 'assistant', 'seq': 8, 'tool_calls': [{'id': 'image', 'tool_name': 'view', 'arguments': '{}'}]},
                     {'role': 'tool', 'seq': 9, 'tool_call_id': 'image', 'content': image}])
        rows[2]['usage_records'] = [{'usage': {'prompt_tokens': 100000}}]
        strategy = DecisionContextCompactor(Summarizer(), client=Judge(), options={'protect_recent_groups': 1})
        result, meta = await strategy.aapply(rows, rows, {'input_limit': 4500, 'context_limit': 100000, 'tool_tokens': 20})
        assert meta and meta['strategy'] == 'decision_selection'
        assert any(r.get('content') == image for r in result)
        assert count_tokens(result, 20) < 4500
        assert rows[2]['usage_records'][0]['usage']['prompt_tokens'] == 100000
    asyncio.run(run())


def test_memory_retry_uses_original_rows_and_excludes_review_feedback(tmp_path):
    async def run():
        log = log_fixture(tmp_path)
        feedback = log.append({'role': 'user', 'content': 'Internal review', 'decision_feedback': True})
        flush = AsyncMock(side_effect=[RuntimeError('unavailable'), 'unchanged'])
        strategy = DecisionContextCompactor(Summarizer(), client=Judge(), options={'protect_recent_groups': 1}, log=log)
        assembler = ContextAssembler(log, [strategy], {'context_limit': 3000, 'reserved_buffer': 500}, flush)
        await assembler.assemble_async()
        assert log.get_memory_flushes()[-1]['status'] == 'failed'
        assert log.get_compaction_events()[-1]['status'] == 'completed'
        assert all(r['seq'] != feedback for r in flush.call_args.args[0])
        first_sources = deepcopy(flush.call_args.args[0])
        pending = assembler._flush_memory(log.get_all_messages(), 0, 0, async_mode=True)
        await pending
        assert flush.call_args.args[0] == first_sources
        assert log.get_memory_flushes()[-1]['status'] == 'unchanged'
    asyncio.run(run())


@pytest.mark.parametrize('protected_groups,expected', [(2, 'completed'),
                                                      (3, 'failed')])
def test_manual_decision_compaction_works_at_stopped_input_boundary(
        tmp_path, protected_groups, expected):
    from ms_agent.agent.llm_agent import LLMAgent
    from types import SimpleNamespace
    async def run():
        agent = LLMAgent.__new__(LLMAgent)
        agent.session_log = log_fixture(tmp_path)
        agent.config = OmegaConf.create({
            'execution': {'mode': 'decision'},
            'decision': {'context': {'protect_recent_groups': protected_groups}}
        })
        agent.llm = Summarizer()
        agent.runtime = SimpleNamespace(should_stop=True)
        agent._event_sink = None
        agent.memory_tools = []
        agent.tool_manager = SimpleNamespace(get_tools=AsyncMock(return_value=[]))
        cfg = {'context_limit': 6000, 'input_limit': 5500, 'output_reserve': 500}
        agent._build_assembler_config = lambda *_: cfg.copy()
        agent.context_assembler = ContextAssembler(agent.session_log)
        result = await agent.compact_context(force=True, trigger='manual')
        assert result['status'] == expected
        if expected == 'completed':
            event = agent.session_log.get_compaction_events()[-1]
            assert event['strategy'] == 'llm_summary'
        else:
            assert not agent.session_log.get_compaction_events()
            assert not agent.llm.calls
        assert agent.runtime.should_stop
    asyncio.run(run())


def test_memory_injection_preserves_review_markers_and_source_references():
    from ms_agent.memory.unified.orchestrator import _messages_to_dicts
    from ms_agent.session.context_assembler import _dicts_to_messages

    feedback = Message(role='user', content='Check the failed test.')
    feedback._decision_feedback = True
    feedback._origin_seq = 7
    summary = Message(role='user', content='Earlier work')
    summary._context_summary = True
    restored = _dicts_to_messages(_messages_to_dicts([feedback, summary]))
    assert restored[0]._decision_feedback
    assert restored[0]._origin_seq == 7
    assert restored[1]._context_summary and restored[1].context_summary


def test_summary_does_not_treat_old_usage_as_protected_input_size(tmp_path):
    async def run():
        log = log_fixture(tmp_path)
        rows = log.get_all_messages()
        rows[-2]['prompt_tokens'] = 100000
        rows[-2]['usage_records'] = [{'usage': {'prompt_tokens': 100000}}]
        strategy = DecisionContextCompactor(Summarizer(), log=log)
        result, meta = await strategy.aapply(rows, rows, {
            'context_limit': 6000,
            'input_limit': 5500,
            'force_compaction': True,
        })
        assert meta and meta['strategy'] == 'llm_summary'
        assert count_tokens(result) < 5500
        assert rows[-2]['prompt_tokens'] == 100000
    asyncio.run(run())
