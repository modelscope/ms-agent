"""Offline regression tests for shared budgets and per-request accounting."""
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from omegaconf import OmegaConf

from ms_agent.llm.context_budget import resolve_context_budget, resolve_model_metadata
from ms_agent.llm.cost import (estimate_cost, merge_usage, normalize_usage,
                               price_usage_records, response_usage)
from ms_agent.llm.transport.openai_compat import OpenAICompatTransport
from ms_agent.llm.transport.anthropic_messages import AnthropicMessagesTransport
from ms_agent.llm.openai_llm import OpenAI
from ms_agent.llm.anthropic_llm import Anthropic
from ms_agent.llm.utils import Message

META = {'limit': {'context': 100000, 'input': 90000, 'output': 64000},
        'cost': {'input': 2, 'output': 8, 'cache_read': 0.2, 'cache_write': 2.5},
        'catalog_provider': 'test-provider', 'catalog_revision': 'sha256:test'}


def test_budget_default_and_explicit_limits():
    assert resolve_context_budget({}, metadata={}) == {
        'context_limit': 128000, 'model_context_limit': None,
        'input_limit': 119808, 'output_reserve': 8192,
        'compression_threshold': 108800, 'compression_ratio': 0.85}
    budget = resolve_context_budget({}, metadata=META)
    assert budget['output_reserve'] == 8192  # NOT the catalog's 64k max output
    assert budget['input_limit'] == 90000
    assert budget['compression_threshold'] == 85000
    config = OmegaConf.create({'llm': {'context_limit': 80000},
                               'generation_config': {'max_completion_tokens': 24000},
                               'compaction': {'context_limit': 95000, 'enabled': False}})
    budget = resolve_context_budget(config, metadata=META)
    assert budget['context_limit'] == 80000
    assert budget['input_limit'] == budget['compression_threshold'] == 56000
    assert budget['output_reserve'] == 24000


@pytest.mark.parametrize('reserve,expected', [(0, 90000), (1000, 90000), (30000, 70000)])
def test_explicit_legacy_reserve_never_crosses_hard_cap(reserve, expected):
    budget = resolve_context_budget({'session_log': {'reserved_buffer': reserve}}, metadata=META)
    assert budget['compression_threshold'] == expected


def test_bounded_default_uses_current_openai_parameter_and_responses_budget():
    from ms_agent.llm.context_budget import _output_token_parameter
    cfg = {'llm': {'service': 'openai', 'model': 'gpt-5'}}
    with patch('ms_agent.llm.context_budget.resolve_model_metadata',
               return_value={'catalog_provider': 'openai'}):
        assert _output_token_parameter(cfg) == 'max_completion_tokens'
        cfg['llm']['protocol'] = 'anthropic'
        assert _output_token_parameter(cfg) == 'max_tokens'
    cfg['generation_config'] = {'use_responses_api': True, 'max_tokens': 50000,
                                'max_output_tokens': 3000}
    assert _output_token_parameter(cfg) == 'max_output_tokens'
    assert resolve_context_budget(cfg, metadata=META)['output_reserve'] == 3000


def test_legacy_cap_precedence_unknown_and_small_models():
    c = {'session_log': {'context_limit': 8000}, 'compaction': {'context_limit': 4000}}
    b = resolve_context_budget(c, metadata={})
    assert (b['context_limit'], b['output_reserve'], b['compression_threshold']) == (4000, 500, 3400)
    assert resolve_context_budget({'llm': {'context_limit': 250000}}, metadata={})['context_limit'] == 250000
    assert resolve_context_budget({'generation_config': {'max_tokens': 100001}}, metadata=META)['input_limit'] == 0


@pytest.mark.parametrize('key', ['max_tokens', 'max_completion_tokens', 'max_output_tokens'])
def test_native_output_override_matches_the_request_budget(key):
    config = {'llm': {'context_limit': 8000}, 'generation_config': {
        key: 1000, 'extra_body': {key: 7000},
        'use_responses_api': key == 'max_output_tokens'}}
    before = deepcopy(config)
    budget = resolve_context_budget(config, metadata={})
    assert budget['output_reserve'] == 7000
    assert budget['input_limit'] == budget['compression_threshold'] == 1000
    assert config == before


def test_metadata_uses_resolver_identity_and_not_model_guess(monkeypatch):
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://env.test/v1')
    c = OmegaConf.create({'llm': {'service': 'my-gateway', 'model': 'deepseek-chat',
                                 'my-gateway_base_url': 'https://private.test/v1',
                                 'protocol': 'anthropic'}})
    with patch('ms_agent.llm.model_catalog.get_model', return_value=META) as lookup:
        assert resolve_model_metadata(c) == META
    lookup.assert_called_once_with('my-gateway', 'deepseek-chat', base_url='https://private.test/v1')
    del c.llm['my-gateway_base_url']
    with patch('ms_agent.llm.model_catalog.get_model', return_value=None) as lookup:
        assert resolve_model_metadata(c) is None
    lookup.assert_called_once_with('my-gateway', 'deepseek-chat', base_url='https://env.test/v1')


def test_anthropic_normalization_and_openai_cache_aliases():
    u = normalize_usage(NS(input_tokens=100, output_tokens=50,
                           cache_read_input_tokens=200, cache_creation_input_tokens=300),
                        protocol='anthropic')
    assert u['prompt_tokens'] == 600
    assert u['cached_tokens'] == 200
    assert u['cache_creation_input_tokens'] == 300
    for field in ('prompt_cache_hit_tokens', 'cache_hit_tokens', 'cache_hit'):
        u = normalize_usage({'prompt_tokens': 600, field: 200, 'completion_tokens': 50})
        assert u['prompt_tokens'] == 600  # OpenAI already includes cache
        assert u['cached_tokens'] == 200
    u = normalize_usage({'input_tokens': 600, 'output_tokens': 50,
                         'input_tokens_details': {'cached_tokens': 200},
                         'output_tokens_details': {'reasoning_tokens': 25}})
    assert u['reasoning_tokens'] == 25


def test_cost_cache_reasoning_and_missing_vs_zero():
    usage = {'prompt_tokens': 1000, 'completion_tokens': 100,
             'cached_tokens': 300, 'cache_creation_input_tokens': 200, 'reasoning_tokens': 40}
    c = estimate_cost(META, usage)
    assert c['total'] == pytest.approx((500 * 2 + 300 * .2 + 200 * 2.5 + 100 * 8) / 1e6)
    assert c['currency'] == 'USD' and c['estimated'] is True
    assert c['revision'] == 'sha256:test'
    meta = deepcopy(META)
    meta['cost']['reasoning'] = 10
    assert estimate_cost(meta, usage)['total'] == pytest.approx(c['total'] + 40 * 2 / 1e6)
    del meta['cost']['cache_read']
    assert estimate_cost(meta, usage)['total'] is None
    assert estimate_cost(meta, {'prompt_tokens': 100, 'completion_tokens': 5})['total'] is not None
    assert estimate_cost(None, usage)['total'] is None
    meta['cost'] = dict.fromkeys(('input', 'output', 'cache_read', 'cache_write', 'reasoning'), 0)
    assert estimate_cost(meta, usage)['total'] == 0


def tier_metadata():
    return {'catalog_revision': 'test', 'cost': {'input': 1, 'output': 2,
            'context_over_200k': {'input': 2, 'output': 4},
            'tiers': [{'tier': {'type': 'context', 'size': 300000}, 'input': 3, 'output': 6}]}}


@pytest.mark.parametrize('tokens,price,tier', [(200000, 1, None), (200001, 1, None),
                                               (300000, 1, None), (300001, 3, 300000)])
def test_tiers_strict_highest_whole_request(tokens, price, tier):
    c = estimate_cost(tier_metadata(), {'prompt_tokens': tokens, 'completion_tokens': 10})
    assert c['price']['input'] == price
    assert c['context_tier'] == tier
    assert c['total'] == pytest.approx((tokens * price + 10 * price * 2) / 1e6)


def test_legacy_price_tier_only_applies_without_structured_tiers():
    metadata = tier_metadata()
    del metadata['cost']['tiers']
    assert estimate_cost(metadata, {'prompt_tokens': 200000})['price']['input'] == 1
    assert estimate_cost(metadata, {'prompt_tokens': 200001})['price']['input'] == 2


def test_actual_catalog_tier_does_not_raise_price_before_its_threshold():
    from ms_agent.llm.model_catalog import get_model

    model = get_model('openai', 'gpt-5.6-sol')
    assert estimate_cost(model, {'prompt_tokens': 250000})['price']['input'] == 4
    assert estimate_cost(model, {'prompt_tokens': 272001})['price']['input'] == 8


def test_continued_records_price_individually_and_never_leak_wire():
    m = Message('assistant', **response_usage({'prompt_tokens': 150000, 'completion_tokens': 100}))
    n = Message('assistant', **response_usage({'prompt_tokens': 150001, 'completion_tokens': 200}))
    merge_usage(m, n)
    merge_usage(m, n)  # cumulative stream delivery cannot bill twice
    assert m.prompt_tokens == 300001 and m.completion_tokens == 300
    assert len(m.usage_records) == 2
    price_usage_records(m, {'llm': {'model': 'test'}}, metadata=tier_metadata())
    assert all(r['cost']['price']['input'] == 1 for r in m.usage_records)
    for key in ('usage_records', 'cached_tokens', 'reasoning_tokens', 'cache_creation_input_tokens',
                'prompt_tokens', 'completion_tokens'):
        setattr(m, key, getattr(m, key) or 1)
        assert key not in m.to_dict_clean()


def completion(text='answer', finish='stop', usage=None, response_id='r'):
    return NS(id=response_id, model='test', usage=usage, choices=[NS(
        message=NS(content=text, reasoning_content='', tool_calls=[]), finish_reason=finish)])


def chunk(text='', finish=None, usage=None, response_id='r', choices=True):
    return NS(id=response_id, usage=usage, choices=[NS(
        delta=NS(content=text, reasoning_content='', tool_calls=[]), finish_reason=finish)] if choices else [])


def engine(cls):
    obj = cls.__new__(cls)
    obj.model = 'test'
    obj._active_stream = None
    if cls is OpenAICompatTransport:
        obj.continue_gen_mode = 'partial'
        obj._continue_flag = 'partial'
    return obj


@pytest.mark.parametrize('cls', [OpenAICompatTransport, OpenAI])
def test_nonstream_final_usage_and_continuation(cls):
    t = engine(cls)
    u = NS(prompt_tokens=150000, completion_tokens=50, prompt_cache_hit_tokens=10)
    with patch.object(t, '_call_llm', return_value=completion(usage=u, response_id='second')):
        msg = t._continue_generate([Message('user', 'hi')], completion('part', 'length', u), max_runs=1)
    assert msg.content == 'partanswer'
    assert msg.prompt_tokens == 300000
    assert msg.cached_tokens == 20
    assert len(msg.usage_records) == 2


@pytest.mark.parametrize('cls', [OpenAICompatTransport, OpenAI])
@pytest.mark.parametrize('trailing', [False, True])
def test_stream_final_usage_is_cumulative_not_double_counted(cls, trailing):
    t = engine(cls)
    u = NS(prompt_tokens=100, completion_tokens=30, prompt_cache_hit_tokens=20)
    chunks = [chunk('A', usage=u), chunk('B', 'stop', usage=u)]
    if trailing:
        chunks.append(chunk(usage=u, choices=False))
    result = list(t._stream_continue_generate([Message('user', 'hi')], iter(chunks), max_runs=0))[-1]
    assert result.content == 'AB'
    assert (result.prompt_tokens, result.completion_tokens, result.cached_tokens) == (100, 30, 20)
    assert len(result.usage_records) == 1


@pytest.mark.parametrize('cls', [OpenAICompatTransport, OpenAI])
def test_stream_continuation_final_message_is_not_stale_or_duplicated(cls):
    t = engine(cls)
    u = NS(prompt_tokens=150000, completion_tokens=10)
    first = iter([chunk('A'), chunk(finish='length', usage=u)])
    second = iter([chunk('B', response_id='r2'), chunk(finish='stop', usage=u, response_id='r2')])
    with patch.object(t, '_call_llm', return_value=second):
        snapshots = [deepcopy(m) for m in t._stream_continue_generate([Message('user', 'hi')], first, max_runs=1)]
    result = snapshots[-1]
    assert result.content == 'AB'
    assert result.prompt_tokens == 300000
    assert result.completion_tokens == 20
    assert len(result.usage_records) == 2
    assert result.api_calls == 2


@pytest.mark.parametrize('cls', [OpenAICompatTransport, OpenAI])
@pytest.mark.parametrize('finish', [True, False])
def test_stream_usage_only_trailers_and_early_usage(cls, finish):
    t = engine(cls)
    chunks = [chunk('A', usage={'prompt_tokens': 100, 'completion_tokens': 20})]
    if finish:
        chunks.append(chunk(finish='stop'))
    chunks.extend([chunk(choices=False, usage={'prompt_tokens': 100, 'completion_tokens': 30}),
                   chunk(choices=False, usage={'prompt_tokens': 100, 'completion_tokens': 30,
                                                'cache_hit': 40})])
    result = list(t._stream_continue_generate([Message('user', 'hi')], chunks, max_runs=0))[-1]
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 30
    assert result.cached_tokens == 40
    assert len(result.usage_records) == 1


@pytest.mark.parametrize('stream', [False, True])
def test_responses_api_cache_and_reasoning_record(stream):
    t = engine(OpenAI)
    t._responses_state_mode = 'stateless'
    response = NS(id='resp', output_text='answer', output=[], usage=NS(
        input_tokens=100, output_tokens=30,
        input_tokens_details=NS(cached_tokens=20),
        output_tokens_details=NS(reasoning_tokens=10)))
    t._responses_client = NS(responses=NS(create=lambda **kwargs: response))
    with patch('ms_agent.llm.openai_llm.create_with_thinking_fallback') as call:
        if stream:
            call.return_value = iter([NS(type='response.output_text.delta', delta='answer'),
                                      NS(type='response.completed', response=response)])
            result = list(t._responses_stream_generate([Message('user', 'hi')]))[-1]
        else:
            call.return_value = response
            result = t._responses_generate([Message('user', 'hi')])
    assert (result.prompt_tokens, result.completion_tokens, result.cached_tokens, result.reasoning_tokens) == (100, 30, 20, 10)
    assert len(result.usage_records) == 1
    assert result.usage_records[0]['response_id'] == 'resp'


@pytest.mark.parametrize('cls,mode', [(OpenAICompatTransport, 'partial'),
                                     (OpenAICompatTransport, 'prefix'), (OpenAI, 'partial')])
def test_stream_agent_updates_shared_history_between_chunks(cls, mode):
    t = engine(cls)
    if cls is OpenAICompatTransport:
        t.continue_gen_mode = mode
        t._continue_flag = mode
        t.continue_gen_stop = []
    u = {'prompt_tokens': 100, 'completion_tokens': 10}
    messages = [Message('user', 'hi')]
    first = iter([chunk('A'), chunk(finish='length', usage=u)])
    second = iter([chunk('B', response_id='r2'), chunk('C', response_id='r2'),
                   chunk(finish='length', usage=u, response_id='r2')])
    third = iter([chunk('D', response_id='r3'), chunk(finish='stop', usage=u, response_id='r3')])
    with patch.object(t, '_call_llm', side_effect=[second, third]):
        gen = t._stream_continue_generate(messages, first, max_runs=2)
        snapshots = []
        for msg in gen:
            snapshots.append(deepcopy(msg))
            if messages[-1].role == 'user':
                messages.append(msg)
            else:
                messages[-1] = msg  # exactly what LLMAgent.step does
    assert [m.content for m in snapshots] == ['A', 'AB', 'ABC', 'ABCD', 'ABCD']
    assert snapshots[-1].prompt_tokens == 300
    assert len(snapshots[-1].usage_records) == 3


class StreamManager:
    def __init__(self, events):
        self.events = events
    def __enter__(self):
        return iter(self.events)
    def __exit__(self, *args):
        return False


@pytest.mark.parametrize('cls', [AnthropicMessagesTransport, Anthropic])
@pytest.mark.parametrize('has_final_message', [False, True])
def test_anthropic_stream_snapshots_and_final_usage(cls, has_final_message):
    t = engine(cls)
    start = NS(input_tokens=100, output_tokens=1, cache_read_input_tokens=200,
               cache_creation_input_tokens=300)
    final = NS(input_tokens=100, output_tokens=50, cache_read_input_tokens=200,
               cache_creation_input_tokens=300)
    stop = NS(type='message_stop')
    if has_final_message:
        stop.message = NS(usage=final, content=[NS(type='text', text='answer')])
    events = [NS(type='message_start', message=NS(id='a', usage=start)),
              NS(type='content_block_delta', delta=NS(type='text_delta', text='answer')),
              NS(type='message_delta', usage=NS(output_tokens=20)),
              NS(type='message_delta', usage=NS(output_tokens=50)), stop]
    result = list(t._stream_format_output_message(StreamManager(events)))[-1]
    assert result.content == 'answer'
    assert result.prompt_tokens == 600
    assert result.completion_tokens == 50
    assert result.cached_tokens == 200
    assert result.cache_creation_input_tokens == 300
    assert len(result.usage_records) == 1
    nonstream = t._format_output_message(NS(id='b', usage=final, content=[NS(type='text', text='answer')]))
    assert nonstream.prompt_tokens == 600


def test_usage_journal_survives_failed_commit_and_coalesces_partial_usage(tmp_path):
    from ms_agent.llm.cost import usage_scope, set_response_usage
    from ms_agent.session.session_log import SessionLog
    log = SessionLog(tmp_path, 'ledger')
    response = Message('assistant', id='provider-id')
    config = {'llm': {'model': 'test'}}
    with patch('ms_agent.llm.cost.resolve_model_metadata', return_value=META):
        with usage_scope(log.record_usage, config, 'compaction'):
            set_response_usage(response, {'prompt_tokens': 100, 'completion_tokens': 4}, complete=False)
            first = SessionLog(tmp_path, 'ledger').get_usage_records()
            assert len(first) == 1 and first[0]['cost']['status'] == 'partial'
            set_response_usage(response, {'prompt_tokens': 100, 'completion_tokens': 20})
            with patch.object(log, '_append_line', side_effect=OSError('commit fault')):
                with pytest.raises(OSError):
                    log.commit_compaction([{'role': 'assistant', 'content': 'summary'}], {'strategy': 'summary'})
    records = SessionLog(tmp_path, 'ledger').get_usage_records()
    assert len(records) == 1
    assert records[0]['record_id'] == first[0]['record_id']
    assert records[0]['usage']['completion_tokens'] == 20
    assert records[0]['cost']['status'] == 'complete'
    assert records[0]['cost']['total'] == pytest.approx(.00036)
    assert records[0]['cost']['revision'] == 'sha256:test'
    assert not log.get_all_messages()


def test_incomplete_cache_ttl_and_absent_usage_are_not_free():
    unknown = Message('assistant')
    price_usage_records(unknown, {}, metadata=META)
    assert unknown.usage_records[0]['cost']['status'] == 'unknown'
    assert unknown.usage_records[0]['cost']['total'] is None
    usage = dict(input_tokens=100, output_tokens=20, cache_creation_input_tokens=40,
                 cache_creation={'ephemeral_1h_input_tokens': 40})
    message = Message('assistant', **response_usage(usage, protocol='anthropic'))
    price_usage_records(message, {}, metadata=META)
    record = message.usage_records[0]
    assert record['raw_usage']['cache_creation']['ephemeral_1h_input_tokens'] == 40
    assert record['cost']['total'] is None
    assert 'cache_write_ttl_not_priced' in record['cost']['incomplete_reasons']
    assert record['usage']['prompt_tokens'] == 140


def test_interrupted_stream_keeps_observed_usage_in_journal(tmp_path):
    from ms_agent.llm.cost import usage_scope
    from ms_agent.session.session_log import SessionLog
    log = SessionLog(tmp_path, 'interrupted')
    transport = engine(OpenAICompatTransport)
    with usage_scope(log.record_usage, {'llm': {'model': 'test'}}, 'conversation'):
        stream = transport._stream_continue_generate([Message('user', 'hi')],
            iter([chunk('first', usage={'prompt_tokens': 30, 'completion_tokens': 2}), chunk('second')]), max_runs=0)
        next(stream)
        stream.close()
    records = SessionLog(tmp_path, 'interrupted').get_usage_records()
    assert len(records) == 1
    assert records[0]['usage_status'] == 'partial'
    assert records[0]['usage']['prompt_tokens'] == 30
    assert records[0]['cost']['total'] is None
