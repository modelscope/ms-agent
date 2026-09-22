"""Pruned context must not retain usage measured over removed tool output."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from ms_agent.llm.utils import Message
from ms_agent.session.context_assembler import ContextAssembler
from ms_agent.session.session_log import SessionLog
from ms_agent.session.strategies.summary_compactor import SummaryCompactor
from ms_agent.session.strategies.tool_pruner import (
    ToolOutputPruner, _estimate_total_tokens)

CONFIG = {'context_limit': 2000, 'reserved_buffer': 0, 'prune_protect': 150}


def history():
    return [
        {'role': 'system', 'content': 'Be helpful.'},
        {'role': 'user', 'content': 'Inspect the logs.'},
        {'role': 'assistant', 'content': '', 'prompt_tokens': 80,
         'completion_tokens': 20,
         'tool_calls': [{'id': 'old', 'tool_name': 'read', 'arguments': '{}'}]},
        {'role': 'tool', 'tool_call_id': 'old', 'name': 'read', 'content': 'x' * 24000},
        {'role': 'assistant', 'content': 'Check more.', 'prompt_tokens': 6500,
         'completion_tokens': 40,
         'tool_calls': [{'id': 'new', 'tool_name': 'read', 'arguments': '{}'}]},
        {'role': 'tool', 'tool_call_id': 'new', 'name': 'read', 'content': 'y' * 400},
        {'role': 'user', 'content': 'Continue.'},
    ]


@pytest.mark.parametrize('earlier_usage', [True, False])
def test_pruning_reduces_estimate_without_changing_original_usage(earlier_usage):
    original = history()
    if not earlier_usage:
        original[2].pop('prompt_tokens')
        original[2].pop('completion_tokens')
    snapshot = deepcopy(original)
    result, meta = ToolOutputPruner().apply(deepcopy(original), original, CONFIG)

    assert meta['tokens_before'] > CONFIG['context_limit']
    assert meta['tokens_after'] < CONFIG['context_limit']
    assert _estimate_total_tokens(result) == meta['tokens_after']
    assert result[2] == original[2]  # usage before the changed prefix is valid
    assert original == snapshot


def test_assembler_avoids_unnecessary_summary_and_persists_correct_estimate(tmp_path):
    log = SessionLog(tmp_path, 'pruned')
    original = history()
    log.append_messages(original)
    llm = Mock()
    llm.generate.return_value = Message(role='assistant', content='Summary')

    def assemble(session):
        return ContextAssembler(
            session, [ToolOutputPruner(), SummaryCompactor(llm)], CONFIG).assemble()

    assemble(log)
    llm.generate.assert_not_called()
    events = log.get_compaction_events()
    assert len(events) == 1
    assert events[0]['tokens_after'] < CONFIG['context_limit']
    stored = log.get_all_messages()
    assert stored[4]['prompt_tokens'] == 6500
    assert stored[3]['content'] == original[3]['content']

    restored = SessionLog(tmp_path, 'pruned')
    assemble(restored)
    llm.generate.assert_not_called()
    assert len(restored.get_compaction_events()) == 1


def test_usage_is_unchanged_when_outputs_are_protected():
    original = history()
    result, meta = ToolOutputPruner().apply(
        deepcopy(original), original, {**CONFIG, 'prune_protect': 10000})
    assert result == original
    assert meta is None


def test_usage_before_all_pruned_outputs_remains_valid():
    original = history()[:4]
    result, meta = ToolOutputPruner().apply(deepcopy(original), original, CONFIG)
    assert result[2] == original[2]
    assert 100 < meta['tokens_after'] < CONFIG['context_limit']
