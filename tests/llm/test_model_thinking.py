# Copyright (c) ModelScope Contributors. All rights reserved.
"""Offline model capabilities and real SDK serialized request regression tests."""
import copy
import json
from types import SimpleNamespace

import httpx
import pytest
from omegaconf import OmegaConf

from ms_agent.llm import model_catalog, thinking as T, vision as V
from ms_agent.llm.utils import Message


@pytest.fixture
def catalog(monkeypatch):
    records, queries = {}, []

    def get_model(provider_id, model_id, *, base_url=''):
        queries.append((provider_id, model_id, base_url))
        return copy.deepcopy(records.get((provider_id, model_id)))

    monkeypatch.setattr(model_catalog, 'get_model', get_model)
    return records, queries


def _meta(options, **extra):
    return {'reasoning': True, 'reasoning_options': options, **extra}


def _effort(*values):
    return {'type': 'effort', 'values': list(values)}


TOGGLE = {'type': 'toggle'}
BUDGET = {'type': 'budget_tokens', 'min': 1024, 'max': 8192}


@pytest.mark.parametrize('meta,control,options,reasoning', [
    (None, 'unknown', list(T.offered_tiers('openai')), None),
    ({}, 'unknown', list(T.offered_tiers('openai')), None),
    ({'reasoning': True}, 'unknown', list(T.offered_tiers('openai')), True),
    ({'reasoning': False}, 'none', ['auto'], False),
    (_meta([]), 'none', ['auto'], True),
    (_meta([_effort('minimal', 'high')]), 'effort',
     ['auto', 'minimal', 'high'], True),
    (_meta([_effort(None, 'low', 'high')]), 'effort',
     ['auto', 'off', 'low', 'high'], True),
    (_meta([_effort('none', 'low', 'high')]), 'effort',
     ['auto', 'off', 'low', 'high'], True),
])
def test_missing_empty_false_and_null_are_distinct(catalog, meta, control,
                                                   options, reasoning):
    catalog[0]['openai', 'm'] = meta
    result = T.plan('auto', provider_id='openai', model='m')
    assert result['reasoning'] is reasoning
    assert result['reasoning_control'] == control
    assert result['effort_options'] == options
    assert result['params'] == {}


@pytest.mark.parametrize('provider,protocol', [
    ('dashscope', ''), ('anthropic', 'anthropic'), ('minimax', ''),
])
@pytest.mark.parametrize('meta', [{}, {'reasoning': False}, _meta([]),
                                  _meta([TOGGLE])])
def test_catalog_auto_never_forces_thinking(catalog, provider, protocol, meta):
    catalog[0][provider, 'm'] = meta
    for value in ('auto', None, ''):
        result = T.plan(value, provider_id=provider, protocol=protocol, model='m')
        assert not any(k in str(result['params']) for k in
                       ('enable_thinking', '"thinking"', 'reasoning_effort'))
        assert 'thinking' not in result['params']


@pytest.mark.parametrize('provider,options,control,expected', [
    ('deepseek', [TOGGLE], 'toggle', ['auto', 'off', 'on']),
    ('deepseek', [TOGGLE, _effort('low', 'high', 'max')], 'effort',
     ['auto', 'off', 'low', 'high', 'max']),
    ('anthropic', [BUDGET], 'budget', ['auto', 'on']),
    ('anthropic', [TOGGLE, BUDGET], 'budget', ['auto', 'off', 'on']),
    ('dashscope', [BUDGET], 'budget', ['auto', 'on']),
    ('google', [BUDGET, TOGGLE], 'unknown', ['auto']),
    ('google', [_effort('low', 'medium', 'high')], 'effort',
     ['auto', 'low', 'medium', 'high']),
    ('private', [TOGGLE], 'unknown', ['auto']),
    ('minimax', [TOGGLE, _effort('low', 'high')], 'toggle', ['auto', 'off', 'on']),
    ('modelscope', [TOGGLE, BUDGET], 'toggle', ['auto', 'off', 'on']),
    ('deepseek', [BUDGET], 'unknown', ['auto']),
])
def test_controls_only_advertise_implemented_dialects(catalog, provider, options,
                                                    control, expected):
    catalog[0][provider, 'm'] = _meta(options)
    result = T.plan('auto', provider_id=provider, model='m',
                    protocol='anthropic' if provider == 'anthropic' else '')
    assert result['reasoning_control'] == control
    assert result['effort_options'] == expected


@pytest.mark.parametrize('options', [[_effort('minimal', 'high')], [], [BUDGET]])
def test_off_without_evidence_is_not_minimal(catalog, options):
    catalog[0]['anthropic', 'm'] = _meta(options)
    result = T.plan('off', provider_id='anthropic', protocol='anthropic', model='m')
    assert 'off' not in result['effort_options']
    assert result['effective'] == 'auto'
    assert result['params'] == {}


def test_kwargs_model_identity_wins_and_provenance_survives(catalog):
    catalog[0]['private', 'requested'] = _meta(
        [_effort('low', 'high')], catalog_provider='private', catalog_revision='sha')
    result = T.apply_effort({'model': 'requested', 'reasoning_effort': 'medium'},
                            provider_id='private', model='not-this',
                            base_url='https://proxy.test/v1')
    assert result['reasoning_effort'] == 'low'
    assert catalog[1] == [('private', 'requested', 'https://proxy.test/v1')]
    result = T.plan('auto', provider_id='private', model='requested')
    assert result['catalog_provider'] == 'private'
    assert result['catalog_revision'] == 'sha'


def test_catalog_cannot_inject_arbitrary_wire_paths(catalog):
    catalog[0]['openai', 'm'] = _meta([
        {'type': 'arbitrary', 'path': 'extra_body.injected', 'value': True},
        {'type': 'effort', 'values': ['turbo', 'low'], 'path': 'injected'},
    ])
    result = T.plan('high', provider_id='openai', model='m')
    assert result['params'] == {'reasoning_effort': 'low'}
    assert result['effort_options'] == ['auto', 'low']


@pytest.mark.parametrize('provider,model,options,effort,expected', [
    ('openai', 'm', [_effort('none', 'low', 'high')], 'off',
     {'reasoning_effort': 'none'}),
    ('openai', 'm', [_effort('low', 'high')], 'medium',
     {'reasoning_effort': 'low'}),
    ('openrouter', 'm', [TOGGLE], 'on', {'reasoning': {'enabled': True}}),
    ('openrouter', 'm', [TOGGLE], 'off', {'reasoning': {'enabled': False}}),
    ('openrouter', 'm', [_effort('low', 'high')], 'high',
     {'reasoning': {'effort': 'high'}}),
    ('dashscope', 'qwen-plus', [TOGGLE], 'on', {'enable_thinking': True}),
    ('dashscope', 'qwen-plus', [TOGGLE], 'off', {'enable_thinking': False}),
    ('dashscope', 'qwen3.8-max', [TOGGLE, _effort('low', 'medium', 'xhigh')],
     'max', {'enable_thinking': True, 'reasoning_effort': 'xhigh'}),
    ('dashscope', 'deepseek-v4-flash', [TOGGLE, _effort('high', 'max')],
     'high', {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high'}),
    ('dashscope', 'glm-5', [TOGGLE], 'on', {'thinking': {'type': 'enabled'}}),
    ('dashscope', 'kimi-k2.6', [TOGGLE], 'off', {'thinking': {'type': 'disabled'}}),
    ('deepseek', 'm', [TOGGLE], 'on', {'thinking': {'type': 'enabled'}}),
    ('zhipu', 'm', [TOGGLE], 'off', {'thinking': {'type': 'disabled'}}),
    ('moonshot', 'm', [TOGGLE], 'on', {'thinking': {'type': 'enabled'}}),
    ('google', 'm', [BUDGET], 'high', {}),
    ('google', 'm', [_effort('low', 'medium', 'high')], 'low',
     {'reasoning_effort': 'low'}),
])
@pytest.mark.parametrize('legacy', [False, True])
def test_openai_paths_serialize_the_model_plan(catalog, provider, model, options,
                                             effort, expected, legacy):
    catalog[0][provider, model] = _meta(options)
    llm, calls = _engine('openai', legacy, provider, model)
    try:
        llm.generate([Message(role='user', content='hello')], reasoning_effort=effort)
    finally:
        llm.client.close()
    assert len(calls) == 1
    assert _controls(calls[0]) == expected
    assert calls[0]['model'] == model
    assert catalog[1][0][:2] == (provider, model)


def _controls(body):
    return {k: v for k, v in body.items() if k in T.THINKING_PARAM_KEYS}


def _engine(protocol, legacy, provider='provider', model='m', fail_first=False):
    """Real vendor SDK serialization against an in-process HTTP mock only."""
    import anthropic
    import openai
    from ms_agent.llm.anthropic_llm import Anthropic
    from ms_agent.llm.openai_llm import OpenAI
    from ms_agent.llm.transport.anthropic_messages import AnthropicMessagesTransport
    from ms_agent.llm.transport.openai_compat import OpenAICompatTransport

    calls = []

    def send(request):
        calls.append(json.loads(request.content))
        if fail_first and len(calls) == 1:
            return httpx.Response(400, json={'error': {
                'type': 'invalid_request_error',
                'message': 'unsupported output_config.effort'}})
        if request.url.path.endswith('/responses'):
            return httpx.Response(200, json={
                'id': 'resp-1', 'object': 'response', 'created_at': 1,
                'model': model, 'output': [], 'status': 'completed',
                'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}})
        if protocol == 'anthropic':
            body = {'id': 'msg-1', 'type': 'message', 'role': 'assistant',
                    'model': model, 'content': [{'type': 'text', 'text': 'ok'}],
                    'stop_reason': 'end_turn',
                    'usage': {'input_tokens': 1, 'output_tokens': 1}}
        else:
            body = {'id': 'chat-1', 'object': 'chat.completion', 'created': 1,
                    'model': model, 'choices': [{'index': 0, 'finish_reason': 'stop',
                    'message': {'role': 'assistant', 'content': 'ok'}}],
                    'usage': {'prompt_tokens': 1, 'completion_tokens': 1,
                              'total_tokens': 2}}
        return httpx.Response(200, json=body)

    http_client = httpx.Client(transport=httpx.MockTransport(send))
    if protocol == 'anthropic':
        cls = Anthropic if legacy else AnthropicMessagesTransport
        client = anthropic.Anthropic(api_key='test', base_url='https://proxy.test',
                                     http_client=http_client)
    else:
        cls = OpenAI if legacy else OpenAICompatTransport
        client = openai.OpenAI(api_key='test', base_url='https://proxy.test/v1',
                               http_client=http_client)
    llm = cls.__new__(cls)
    llm.client = client
    llm.model = model
    llm.provider_id = provider
    llm.args = {}
    llm.config = OmegaConf.create({'llm': {'service': provider, 'model': model}})
    llm.max_continue_runs = 1
    llm._use_responses_api = False
    llm._strip_reasoning_tags = False
    llm.continue_gen_mode = None
    llm._continue_flag = 'partial'
    llm._active_stream = None
    llm._format_input_message = lambda messages: [
        {'role': message.role, 'content': message.content} for message in messages]
    return llm, calls


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('options,effort,expected', [
    ([_effort('low', 'medium', 'high', 'max')], 'medium',
     {'thinking': {'type': 'adaptive'}, 'output_config': {'effort': 'medium'}}),
    ([TOGGLE, BUDGET], 'off', {'thinking': {'type': 'disabled'}}),
    ([BUDGET], 'on', {'thinking': {'type': 'enabled', 'budget_tokens': 4096}}),
    ([], 'high', {}),
    ([_effort('low', 'high')], 'auto', {}),
])
def test_anthropic_paths_use_native_model_controls(catalog, legacy, options,
                                                   effort, expected):
    catalog[0]['anthropic', 'm'] = _meta(options, limit={'output': 10000})
    llm, calls = _engine('anthropic', legacy, 'anthropic')
    try:
        llm.generate([Message(role='user', content='hello')], reasoning_effort=effort)
    finally:
        llm.client.close()
    assert len(calls) == 1
    assert _controls(calls[0]) == expected
    if expected.get('thinking', {}).get('type') == 'enabled':
        assert 4096 < calls[0]['max_tokens'] <= 10000


@pytest.mark.parametrize('protocol', ['anthropic', 'openai'])
@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('effort', ['auto', 'high', 'off'])
def test_non_reasoning_model_never_gets_automatic_controls(catalog, protocol,
                                                          legacy, effort):
    catalog[0]['provider', 'm'] = {'reasoning': False}
    llm, calls = _engine(protocol, legacy)
    try:
        llm.generate([Message(role='user', content='hello')], reasoning_effort=effort)
    finally:
        llm.client.close()
    assert _controls(calls[0]) == {}


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('raw,expected', [
    ({'thinking_budget': 2048},
     {'thinking': {'type': 'enabled', 'budget_tokens': 2048}}),
    ({'extra_body': {'thinking_budget': 2048}},
     {'thinking': {'type': 'enabled', 'budget_tokens': 2048}}),
    ({'enable_thinking': False}, {'thinking': {'type': 'disabled'}}),
    ({'extra_body': {'enable_thinking': False, 'thinking_budget': 2048}},
     {'thinking': {'type': 'disabled'}}),
    ({'thinking_type': 'adaptive', 'output_config': {'effort': 'low'}},
     {'thinking': {'type': 'adaptive'}, 'output_config': {'effort': 'low'}}),
    ({'thinking': {'type': 'disabled'}, 'thinking_budget': 2048},
     {'thinking': {'type': 'disabled'}}),
    ({'extra_body': {'thinking': {'type': 'disabled'}}, 'thinking_budget': 2048},
     {'thinking': {'type': 'disabled'}}),
    ({'output_config': {'effort': 'max'}}, {'output_config': {'effort': 'max'}}),
    ({'extra_body': {'output_config': {'effort': 'max'}}},
     {'output_config': {'effort': 'max'}}),
])
def test_anthropic_raw_overrides_survive_both_signature_filters(catalog, legacy,
                                                               raw, expected):
    catalog[0]['anthropic', 'm'] = _meta([_effort('low', 'high'), BUDGET])
    original = copy.deepcopy(raw)
    llm, calls = _engine('anthropic', legacy, 'anthropic')
    try:
        llm.generate([Message(role='user', content='hello')], reasoning_effort='high',
                     **raw)
    finally:
        llm.client.close()
    assert _controls(calls[0]) == expected
    assert raw == original


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('raw,expected', [
    ({'thinking_budget': 2048}, {'thinking_budget': 2048, 'enable_thinking': True}),
    ({'thinking': {'type': 'disabled'}}, {'thinking': {'type': 'disabled'}}),
    ({'output_config': {'effort': 'max'}}, {'output_config': {'effort': 'max'}}),
    ({'extra_body': {'reasoning_effort': 'future'}}, {'reasoning_effort': 'future'}),
    ({'extra_body': {'enable_thinking': False}}, {'enable_thinking': False}),
])
def test_openai_raw_overrides_survive_both_signature_filters(catalog, legacy,
                                                            raw, expected):
    catalog[0]['dashscope', 'qwen'] = _meta([TOGGLE, _effort('low', 'high')])
    llm, calls = _engine('openai', legacy, 'dashscope', 'qwen')
    try:
        llm.generate([Message(role='user', content='hello')], reasoning_effort='high',
                     **raw)
    finally:
        llm.client.close()
    assert _controls(calls[0]) == expected


@pytest.mark.parametrize('existing,budget,max_tokens', [
    ({'max_tokens': 2048}, 2047, 2048),
    ({'max_tokens': 1025}, 1024, 1025),
    ({'extra_body': {'thinking_budget': 8192}}, 8192, 10000),
    ({'thinking': {'type': 'enabled', 'budget_tokens': 8192}}, 8192, 10000),
])
def test_anthropic_budgets_fit_current_request(catalog, existing, budget, max_tokens):
    catalog[0]['anthropic', 'm'] = _meta([BUDGET], limit={'output': 10000})
    out = T.apply_effort({'reasoning_effort': 'on', **existing},
                         provider_id='anthropic', model='m', protocol='anthropic')
    assert out['max_tokens'] == max_tokens
    assert out['thinking']['budget_tokens'] == budget
    assert budget < out['max_tokens']
    assert 'thinking_budget' not in out.get('extra_body', {})


@pytest.mark.parametrize('existing', [
    {'max_tokens': 1024},
    {'max_tokens': 4096, 'thinking_budget': 4096},
    {'max_tokens': 4096, 'thinking': {'type': 'enabled', 'budget_tokens': 4096}},
    {'thinking_budget': 8193},
    {'thinking_budget': 500},
    {'thinking_budget': -1},
    {'thinking_budget': True},
    {'max_tokens': 10001},
    {'thinking': {'type': 'enabled'}},
    {'extra_body': {'thinking': {'type': 'enabled'}}},
])
def test_invalid_explicit_budget_or_output_limit_fails_before_send(catalog, existing):
    catalog[0]['anthropic', 'm'] = _meta([BUDGET], limit={'output': 10000})
    with pytest.raises(ValueError, match='budget|max_tokens'):
        T.apply_effort({'reasoning_effort': 'on', **existing},
                       provider_id='anthropic', model='m', protocol='anthropic')


def test_budget_bounds_and_plan_match_application(catalog):
    catalog[0]['anthropic', 'm'] = _meta([BUDGET], limit={'output': 10000})
    existing = {'max_tokens': 3000}
    plan = T.plan('on', provider_id='anthropic', model='m', protocol='anthropic',
                  existing=existing)
    assert plan['budget_min'] == 1024
    assert plan['budget_max'] == 8192
    assert plan['effort_options'] == ['auto', 'on']
    assert T.apply_effort({'reasoning_effort': 'on', **existing},
                          provider_id='anthropic', model='m', protocol='anthropic') == {
                              **existing, **plan['params']}


@pytest.mark.parametrize('provider,expected', [
    ('openai', {'reasoning_effort': 'high'}),
    ('private', {'reasoning_effort': 'high'}),
    ('dashscope', {'enable_thinking': True, 'reasoning_effort': 'high'}),
])
def test_unknown_models_retain_manual_canonical_control(catalog, provider, expected):
    out = T.apply_effort({'reasoning_effort': 'high'}, provider_id=provider, model='new')
    wire = {**out, **out.get('extra_body', {})}
    wire.pop('extra_body', None)
    assert wire == expected


@pytest.mark.parametrize('error', [OSError('missing'), ValueError('corrupt')])
def test_unavailable_catalog_falls_back_for_thinking_and_vision(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(model_catalog, 'get_model', fail)
    assert T.plan('low', model='m', provider_id='openai')['params'] == {
        'reasoning_effort': 'low'}
    assert V.resolve_supports_vision({'llm': {'service': 'openai', 'model': 'm'}}) is False


@pytest.mark.parametrize('meta,expected', [
    (None, False), ({}, False), ({'modalities': {}}, False),
    ({'modalities': {'input': ['text'], 'output': ['image']}}, False),
    ({'modalities': {'input': ['text', 'image']}}, True),
    ({'modalities': {'input': ['audio', 'video']}}, False),
])
def test_vision_uses_only_exact_models_input_modalities(catalog, meta, expected):
    catalog[0]['provider', 'm'] = meta
    config = OmegaConf.create({'llm': {'service': 'provider', 'model': 'm'}})
    assert V.resolve_supports_vision(config, base_url='https://proxy.test') is expected
    assert catalog[1] == [('provider', 'm', 'https://proxy.test')]


@pytest.mark.parametrize('key,value,expected', [
    ('supports_vision', False, False), ('supports_vision', True, True),
    ('supports_vision', 'false', False), ('vision_supported', 'true', True),
    ('vision_supported', False, False),
])
def test_explicit_vision_flag_does_not_even_query_catalog(catalog, key, value, expected):
    config = OmegaConf.create({'llm': {'service': 'provider', 'model': 'm', key: value}})
    assert V.resolve_supports_vision(config) is expected
    assert catalog[1] == []


def test_vision_flag_priority_and_provider_spec_identity(catalog):
    config = {'llm': {'supports_vision': False, 'vision_supported': True}}
    assert V.resolve_supports_vision(config) is False
    catalog[0]['provider', 'm'] = {'modalities': {'input': ['image']}}
    spec = SimpleNamespace(name='provider', capabilities=SimpleNamespace(vision=False))
    assert V.resolve_supports_vision(None, spec, 'm') is True


@pytest.mark.parametrize('stream', [False, True])
def test_native_anthropic_refusal_cleans_effort_and_budget(stream):
    calls = []
    T.MODELS_REFUSING_THINKING.clear()

    def create(**kwargs):
        calls.append(kwargs)

        def result():
            if kwargs.get('output_config'):
                raise RuntimeError('400 unsupported output_config.effort')
            yield 'ok'
        return result() if stream else next(result())

    try:
        result = T.create_with_thinking_fallback(
            create, SimpleNamespace(base_url='https://proxy.test'), 'm',
            SimpleNamespace(warning=lambda *args: None),
            thinking={'type': 'adaptive'}, output_config={'effort': 'high'})
        assert list(result) == ['ok'] if stream else result == 'ok'
        assert calls[1] == {'thinking': {'type': 'disabled'}}
    finally:
        T.MODELS_REFUSING_THINKING.clear()


@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
def test_router_threads_provider_identity_to_transport(catalog, monkeypatch, protocol):
    from ms_agent.llm.router import ProviderRouter
    from ms_agent.llm.credentials import CredentialResolver
    monkeypatch.setattr(CredentialResolver, 'resolve_api_key', lambda *args: 'test')
    monkeypatch.setattr(CredentialResolver, 'resolve_base_url',
                        lambda *args: 'https://proxy.test/v1')
    catalog[0]['deepseek', 'm'] = {'modalities': {'input': ['image']}}
    config = OmegaConf.create({'llm': {'service': 'deepseek', 'model': 'm',
                                      'protocol': protocol}})
    provider = ProviderRouter().create(config)
    try:
        assert provider.transport.provider_id == 'deepseek'
        assert provider.transport._vision_supported is True
    finally:
        provider.transport.client.close()


def test_legacy_responses_request_preserves_raw_and_no_opinion(catalog):
    catalog[0]['openai', 'm'] = {'reasoning': False}
    llm, _ = _engine('openai', True, 'openai')
    llm._responses_state_mode = 'stateless'
    try:
        args = T.apply_effort({'reasoning_effort': 'high'}, provider_id='openai', model='m')
        assert 'reasoning' not in llm._build_responses_kwargs(args)
        raw = {'extra_body': {'reasoning': {'effort': 'none'}}}
        args = T.apply_effort({'reasoning_effort': 'high', **raw},
                              provider_id='openai', model='m')
        assert llm._build_responses_kwargs(args)['extra_body'] == raw['extra_body']
    finally:
        llm.client.close()


@pytest.mark.parametrize('legacy', [False, True])
def test_anthropic_real_sdk_400_retry_uses_native_disabled(catalog, legacy):
    catalog[0]['anthropic', 'm'] = _meta([_effort('low', 'high')])
    llm, calls = _engine('anthropic', legacy, 'anthropic', fail_first=True)
    T.MODELS_REFUSING_THINKING.clear()
    try:
        llm.generate([Message(role='user', content='hello')], reasoning_effort='high')
        assert len(calls) == 2
        assert _controls(calls[0]) == {
            'thinking': {'type': 'adaptive'}, 'output_config': {'effort': 'high'}}
        assert _controls(calls[1]) == {'thinking': {'type': 'disabled'}}
    finally:
        llm.client.close()
        T.MODELS_REFUSING_THINKING.clear()


@pytest.mark.parametrize('legacy', [False, True])
def test_budget_conflict_never_reaches_either_messages_client(catalog, legacy):
    catalog[0]['anthropic', 'm'] = _meta([BUDGET])
    llm, calls = _engine('anthropic', legacy, 'anthropic')
    try:
        with pytest.raises(ValueError, match='budget'):
            llm._call_llm([Message(role='user', content='hello')],
                          reasoning_effort='on', max_tokens=2048,
                          extra_body={'thinking_budget': 2048})
        assert calls == []
    finally:
        llm.client.close()


@pytest.mark.parametrize('meta,args,expected', [
    ({'reasoning': False}, {'reasoning_effort': 'high'}, {}),
    (_meta([_effort('none', 'low', 'high')]), {'reasoning_effort': 'off'},
     {'reasoning': {'effort': 'none', 'summary': 'auto'}}),
    (_meta([_effort('low', 'high')]), {'reasoning_effort': 'medium'},
     {'reasoning': {'effort': 'low', 'summary': 'auto'}}),
    (_meta([]), {'reasoning_effort': 'auto'}, {}),
    (_meta([_effort('low', 'high')]),
     {'reasoning_effort': 'high', 'reasoning': {'effort': 'low'}},
     {'reasoning': {'effort': 'low'}}),
])
def test_legacy_responses_final_serialized_body(catalog, meta, args, expected):
    catalog[0]['openai', 'm'] = meta
    llm, calls = _engine('openai', True, 'openai')
    llm._responses_client = llm.client
    llm._use_responses_api = True
    llm._responses_state_mode = 'stateless'
    try:
        llm.generate([Message(role='user', content='hello')], **args)
        assert _controls(calls[0]) == expected
    finally:
        llm.client.close()


def test_openai_effort_plus_toggle_can_explicitly_disable(catalog):
    catalog[0]['openai', 'm'] = _meta([TOGGLE, _effort('low', 'high')])
    result = T.plan('off', provider_id='openai', model='m')
    assert result['effort_options'] == ['auto', 'off', 'low', 'high']
    assert result['params'] == {'reasoning_effort': 'none'}


def test_protocol_wins_over_vendor_host_and_catalog(catalog):
    catalog[0]['deepseek', 'm'] = _meta([TOGGLE, _effort('low', 'high')])
    result = T.plan('high', provider_id='deepseek', model='m',
                    base_url='https://api.deepseek.com/anthropic',
                    protocol='anthropic')
    assert result['params'] == {
        'thinking': {'type': 'adaptive'}, 'output_config': {'effort': 'high'}}


@pytest.mark.parametrize('base_url', [
    'https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
    'https://dashscope-us.aliyuncs.com/compatible-mode/v1',
    'https://dashscope-sg.aliyuncs.com/compatible-mode/v1',
])
def test_regional_dashscope_hosts_use_same_wire_dialect(base_url):
    assert T.endpoint_family(base_url) == 'dashscope'


def test_absent_catalog_module_is_safe(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, 'ms_agent.llm.model_catalog', None)
    assert T.plan('high', provider_id='openai', model='m')['params'] == {
        'reasoning_effort': 'high'}
    assert V.resolve_supports_vision({'llm': {'service': 'openai', 'model': 'm'}}) is False


@pytest.mark.parametrize('base_url', [
    'https://api.deepseek.com.unrelated.test/v1',
    'https://not-openrouter.ai/v1',
    'https://api.minimax.attacker.test/v1',
])
def test_family_does_not_match_deceptive_hosts(base_url):
    assert T.endpoint_family(base_url) == 'unknown'


@pytest.mark.parametrize('legacy', [False, True])
def test_opus_45_effort_uses_enabled_budget_not_adaptive(catalog, legacy):
    model = 'claude-opus-4-5'
    catalog[0]['anthropic', model] = _meta([_effort('low', 'medium', 'high'), BUDGET])
    llm, calls = _engine('anthropic', legacy, 'anthropic', model)
    try:
        llm.generate([Message(role='user', content='hello')], reasoning_effort='low', max_tokens=5000)
    finally:
        llm.client.close()
    assert calls[0]['thinking'] == {'type': 'enabled', 'budget_tokens': 4096}
    assert calls[0]['output_config'] == {'effort': 'low'}


def test_generated_dashscope_budget_fits_current_output(catalog):
    catalog[0]['dashscope', 'm'] = _meta([BUDGET])
    result = T.plan('on', provider_id='dashscope', model='m', existing={'max_tokens': 2048})
    assert result['params'] == {'extra_body': {'thinking_budget': 2047}}
    raw = {'max_tokens': 10, 'extra_body': {'thinking_budget': 4}}
    assert T.apply_effort(raw, provider_id='dashscope', model='m') == raw
