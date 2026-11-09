"""Non-destructive compaction, response evidence, and restore regressions."""
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import pytest
from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.llm.context_budget import resolve_context_budget
from ms_agent.llm.cost import price_usage_records, response_usage
from ms_agent.llm.utils import Message
from ms_agent.session.context_assembler import (ContextAssembler, ContextBudgetExceeded,
                                                 _dicts_to_messages)
from ms_agent.session.session_log import SessionLog
from ms_agent.session.strategies.summary_compactor import SummaryCompactor
from ms_agent.session.strategies.tool_pruner import (ToolOutputPruner, _estimate_total_tokens,
                                                     _estimate_message_tokens)


def budget(context=4000, output=256):
    return resolve_context_budget({'generation_config': {'max_tokens': output}},
                                  metadata={'limit': {'context': context}})


def tool_round(text, call_id='call'):
    return [{'role': 'assistant', 'content': '',
             'tool_calls': [{'id': call_id, 'tool_name': 'read', 'arguments': '{}'}]},
            {'role': 'tool', 'content': text, 'tool_call_id': call_id}]


def summary_llm(text='The prior task and findings.'):
    return NS(generate=Mock(return_value=Message('assistant', text)))


@pytest.mark.parametrize('failure', ['before', 'partial', 'utf8', 'after_fsync'])
def test_compaction_commit_recovers_only_a_whole_window(tmp_path, monkeypatch, failure):
    """Exercise a torn commit through the assembler, then append after restart."""
    import json

    log = SessionLog(tmp_path, 'atomic')
    original = [{'role': 'user', 'content': 'old'},
                {'role': 'assistant', 'content': 'old answer'},
                {'role': 'user', 'content': 'latest'}]
    log.append_messages(original)
    replacement = [{'role': 'user', 'content': '摘要', 'context_summary': True},
                   original[-1]]
    strategy = NS(name='test', apply=lambda *_: (replacement, {
        'tokens_before': 100, 'tokens_after': 10}))
    append = log._append_line

    def fail(record):
        if failure == 'after_fsync':
            append(record)
        elif failure != 'before':
            payload = json.dumps(record, ensure_ascii=False).encode()
            cut = payload.index('摘要'.encode()) + 1 if failure == 'utf8' else len(payload) // 2
            with log._path.open('ab') as stream:
                stream.write(payload[:cut])
        raise OSError('injected commit failure')

    monkeypatch.setattr(log, '_append_line', fail)
    with pytest.raises(OSError, match='injected'):
        ContextAssembler(log, [strategy], budget()).assemble()
    expected = replacement if failure == 'after_fsync' else original
    # The still-running writer and a reopened reader agree on the outcome.
    for reader in (log, SessionLog(tmp_path, 'atomic')):
        assert [m['content'] for m in reader.get_visible_messages()] == [m['content'] for m in expected]
        assert len(reader.get_compaction_events()) == (failure == 'after_fsync')
    resumed = SessionLog(tmp_path, 'atomic')
    resumed.append({'role': 'assistant', 'content': 'continued'})
    reopened = SessionLog(tmp_path, 'atomic')
    assert reopened.get_visible_messages()[-1]['content'] == 'continued'
    rows = reopened.get_all_messages()
    assert len({m['seq'] for m in rows}) == len(rows)


def test_repeated_compaction_needs_no_sidecar_write(tmp_path, monkeypatch):
    log = SessionLog(tmp_path, 'repeated')
    log.append({'role': 'user', 'content': 'original'})
    monkeypatch.setattr(log, '_write_meta', Mock(side_effect=OSError('unavailable sidecar')))
    for text in ('first', 'second'):
        log.commit_compaction([{'role': 'user', 'content': text}], {'strategy': 'summary'})
    reader = SessionLog(tmp_path, 'repeated')
    assert [m['content'] for m in reader.get_all_messages()] == ['original', 'first', 'second']
    assert [m['content'] for m in reader.get_visible_messages()] == ['second']
    assert reader.get_metadata()['last_consolidated'] == reader.get_visible_messages()[0]['seq']
    assert len(reader.get_compaction_events()) == 2


def test_pruning_invalidates_old_usage_and_preserves_originals(tmp_path):
    log = SessionLog(tmp_path)
    rows = [{'role': 'system', 'content': 'instructions'}, {'role': 'user', 'content': 'old'}]
    rows += tool_round('X' * 16000)
    rows += [{'role': 'assistant', 'content': 'done', 'prompt_tokens': 6500,
              'completion_tokens': 20}, {'role': 'user', 'content': 'latest'}]
    log.append_messages(rows)
    assembler = ContextAssembler(log, [ToolOutputPruner(), SummaryCompactor(summary_llm())],
                                  {**budget(), 'prune_protect': 0})
    result = assembler.assemble()
    events = log.get_compaction_events()
    assert len(events) == 1 and events[0]['strategy'] == 'tool_output_pruner'
    assert events[0]['tokens_after'] < events[0]['tokens_before']
    assert events[0]['budget']['compression_threshold'] == 3400
    assert next(m for m in result if m.role == 'tool').tool_call_id == 'call'
    assert result[-1].content == 'latest'
    assert log.get_all_messages()[3]['content'] == 'X' * 16000
    lc = log.last_consolidated
    restored = ContextAssembler(SessionLog(tmp_path, log.session_key), assembler.strategies, assembler.config)
    restored.assemble()
    assert restored.session_log.last_consolidated == lc
    assert len(restored.session_log.get_compaction_events()) == 1


def test_tool_schemas_trigger_compaction_before_hard_input_limit(tmp_path):
    log = SessionLog(tmp_path)
    log.append_messages([
        {'role': 'user', 'content': 'X' * 11000},
        {'role': 'assistant', 'content': 'done'},
        {'role': 'user', 'content': 'latest'},
    ])
    llm = summary_llm()
    config = {**budget(), 'tool_tokens': 1000}
    result = ContextAssembler(log, [SummaryCompactor(llm)], config).assemble()
    assert llm.generate.called
    assert log.get_compaction_events()[0]['tokens_before'] > config['compression_threshold']
    assert result[-1].content == 'latest'


def test_tool_schema_tokens_are_not_added_twice_to_api_usage():
    messages = [{'role': 'assistant', 'content': 'answer', 'prompt_tokens': 3500}]
    assert _estimate_total_tokens(messages, tool_tokens=1000) == 3500


def test_estimate_uses_last_response_not_continuation_sum_or_cache_discount():
    m = Message('assistant', 'answer', **response_usage({'prompt_tokens': 3000,
                 'completion_tokens': 10, 'cached_tokens': 2900}))
    m.usage_records.append(response_usage({'prompt_tokens': 3200, 'completion_tokens': 20})['usage_records'][0])
    m.prompt_tokens = 6200
    assert _estimate_total_tokens([LLMAgent._msg_to_dict(m)]) == 3220


@pytest.mark.parametrize('delta,pruned', [(-1, False), (0, True), (1, True)])
def test_pruner_threshold_inclusive(delta, pruned):
    config = {**budget(), 'prune_protect': 0}
    rows = tool_round('X' * 2000) + [{'role': 'assistant', 'content': 'ok',
                                    'prompt_tokens': config['compression_threshold'] + delta}]
    _, meta = ToolOutputPruner().apply(deepcopy(rows), rows, config)
    assert (meta is not None) == pruned


def test_summary_preserves_system_latest_user_media_and_tool_groups(tmp_path):
    rows = [{'role': 'system', 'content': 'system1'}, {'role': 'system', 'content': 'system2'},
            {'role': 'user', 'content': 'old ' * 7500}]
    rows += tool_round('old tool details', 'old')
    rows += [{'role': 'user', 'content': 'LATEST', 'attachments': [{'type': 'image', 'path': 'user_files/a.png'}]}]
    rows += tool_round('current tool result', 'current')
    llm = summary_llm()
    log = SessionLog(tmp_path)
    log.append_messages(rows)
    result = ContextAssembler(log, [SummaryCompactor(llm)], budget(8000)).assemble()
    assert [m.content for m in result if m.role == 'system'] == ['system1', 'system2']
    latest = next(m for m in result if m.content == 'LATEST')
    assert latest.attachments[0]['path'] == 'user_files/a.png'
    assert result[-2].tool_calls[0]['id'] == result[-1].tool_call_id == 'current'
    assert not any(tc['id'] == 'old' for m in result for tc in m.tool_calls or [])
    sent = '\n'.join(m.content for c in llm.generate.call_args_list for m in c.args[0])
    assert 'old tool details' in sent and 'TOOL_CALLS' in sent


def test_summary_chunks_every_character_with_bounded_input_and_output():
    llm = summary_llm('condensed')
    strategy = SummaryCompactor(llm)
    long_text = 'A' * 9000 + 'IMPORTANT_END_DECISION'
    config = {**budget(2000), 'summary_input_char_limit': 512, 'summary_max_tokens': 100}
    summary = strategy._generate_summary([{'role': 'user', 'content': long_text}], config)
    assert summary and all(part == 'condensed' for part in summary.split('\n\n'))
    sent = ''.join(m.content for c in llm.generate.call_args_list for m in c.args[0])
    assert 'IMPORTANT_END_DECISION' in sent
    assert len(llm.generate.call_args_list) > 2
    for call in llm.generate.call_args_list:
        assert sum(_estimate_message_tokens(m.to_dict()) for m in call.args[0]) <= config['input_limit']
        assert call.kwargs['max_tokens'] == 100
        assert call.kwargs['stream'] is False


def test_summary_failure_and_oversized_latest_retain_log(tmp_path):
    log = SessionLog(tmp_path)
    original = [{'role': 'user', 'content': 'old' * 7000}, {'role': 'user', 'content': 'latest'}]
    log.append_messages(original)
    llm = summary_llm()
    llm.generate.side_effect = RuntimeError('summary unavailable')
    assembler = ContextAssembler(log, [SummaryCompactor(llm)], budget())
    with pytest.raises(ContextBudgetExceeded, match='Original session records were retained'):
        assembler.assemble()
    assert len(log.get_all_messages()) == 2
    assert not log.get_compaction_events()
    latest = SessionLog(tmp_path, 'huge-latest')
    latest.append({'role': 'user', 'content': 'X' * 20000})
    llm.generate.reset_mock()
    with pytest.raises(ContextBudgetExceeded, match='Shorten the latest'):
        ContextAssembler(latest, [SummaryCompactor(llm)], budget()).assemble()
    llm.generate.assert_not_called()


def test_disabled_compaction_still_checks_hard_budget(tmp_path):
    log = SessionLog(tmp_path)
    log.append({'role': 'user', 'content': 'X' * 20000})
    with pytest.raises(ContextBudgetExceeded):
        ContextAssembler(log, [], budget()).assemble()


def test_usage_roundtrip_no_repricing_and_no_duplicate_compaction_charges(tmp_path):
    msg = Message('assistant', 'answer', **response_usage({'prompt_tokens': 100, 'completion_tokens': 10}))
    metadata = {'cost': {'input': 1, 'output': 2}, 'catalog_revision': 'original'}
    price_usage_records(msg, {'llm': {'model': 'one'}}, metadata=metadata)
    row = LLMAgent._msg_to_dict(msg)
    restored = _dicts_to_messages([row])[0]
    price_usage_records(restored, {'llm': {'model': 'two'}}, metadata={'cost': {'input': 50, 'output': 60}})
    assert restored.usage_records == msg.usage_records
    assert restored.prompt_tokens == 100
    opaque = Message('assistant', '', _responses_output_items=[{'type': 'reasoning', 'encrypted_content': 'opaque'}])
    replay = _dicts_to_messages([LLMAgent._msg_to_dict(opaque)])[0]
    assert replay._responses_output_items == opaque._responses_output_items
    assert '_responses_output_items' not in replay.to_dict_clean()
    log = SessionLog(tmp_path)
    log.append_messages([{'role': 'user', 'content': 'old'}] + tool_round('X' * 16000) +
                        [row, {'role': 'user', 'content': 'latest'}])
    # Switch away from the recorded model: discard its usage anchor, not its bill.
    config = {**budget(), 'prune_protect': 0, 'model': 'two'}
    ContextAssembler(log, [ToolOutputPruner()], config).assemble()
    records = [r for m in log.get_all_messages() for r in m.get('usage_records', [])]
    assert len(records) == 1
    assert records[0]['cost']['revision'] == 'original'


def test_restored_agent_step_never_counts_usage_again():
    import asyncio

    agent = LLMAgent.__new__(LLMAgent)
    agent.config = OmegaConf.create({'llm': {'model': 'one'}, 'generation_config': {'stream': False}})
    agent.task_manager = None
    agent.load_cache = True
    agent._event_sink = None
    agent.save_history = Mock()
    agent.log_output = Mock()
    message = Message('assistant', 'done', **response_usage({'prompt_tokens': 123, 'completion_tokens': 45}))
    price_usage_records(message, agent.config, metadata={'cost': {'input': 1, 'output': 2}})
    restored = _dicts_to_messages([LLMAgent._msg_to_dict(message)])[0]
    before = (LLMAgent.TOTAL_PROMPT_TOKENS, LLMAgent.TOTAL_COMPLETION_TOKENS)

    async def run():
        return [rows async for rows in LLMAgent.step.__wrapped__(agent, [restored])]

    asyncio.run(run())
    assert before == (LLMAgent.TOTAL_PROMPT_TOKENS, LLMAgent.TOTAL_COMPLETION_TOKENS)
    assert not any('[usage_cost]' in str(c) for c in agent.log_output.call_args_list)


def test_rejected_summary_keeps_usage_evidence(tmp_path):
    log = SessionLog(tmp_path)
    log.append_messages([{'role': 'user', 'content': 'X' * 20000},
                         {'role': 'user', 'content': 'latest'}])
    response = Message('assistant', '', **response_usage({'prompt_tokens': 500, 'completion_tokens': 20}))
    llm = NS(generate=Mock(return_value=response))
    with pytest.raises(ContextBudgetExceeded):
        ContextAssembler(log, [SummaryCompactor(llm)], budget()).assemble()
    assert len(log.get_all_messages()) == 2
    event = log.get_compaction_events()[0]
    assert event['status'] == 'retained'
    assert len(event['usage_records']) == 2
    assert llm.generate.call_count == 2


def test_hook_attachments_roundtrip_and_hard_error_not_retried():
    from ms_agent.hooks.context import HookAttachment, condense_hook_attachments_for_llm
    from ms_agent.utils.llm_utils import is_retryable_error

    message = Message('user', 'hi', hook_attachments=[HookAttachment(
        type='hook_additional_context', hook_event='UserPromptSubmit',
        tool_call_id=None, content='critical context')])
    row = LLMAgent._msg_to_dict(message)
    import json
    restored = _dicts_to_messages(json.loads(json.dumps([row])))
    assert 'critical context' in condense_hook_attachments_for_llm(restored)[-1].content
    assert not is_retryable_error(ContextBudgetExceeded('too large'))


def test_agent_shared_budget_resolves_model_switch_and_disabled_config(tmp_path):
    agent = LLMAgent.__new__(LLMAgent)
    agent.config = OmegaConf.create({'llm': {'service': 'test', 'model': 'small'},
                                     'compaction': {'enabled': False},
                                     'session_log': {'dir': str(tmp_path)}})
    with patch('ms_agent.llm.context_budget.resolve_model_metadata', return_value={'limit': {'context': 8000}}):
        agent._init_session_log()
    assert agent.context_assembler.strategies == []
    assert agent.context_assembler.config['context_limit'] == 8000
    agent.config.llm.model = 'large'
    with patch('ms_agent.llm.context_budget.resolve_model_metadata', return_value={'limit': {'context': 32000}}):
        new = agent._build_assembler_config(agent.config.compaction, agent.config.session_log)
    assert new['context_limit'] == 32000
    assert new['model'] == 'large'
