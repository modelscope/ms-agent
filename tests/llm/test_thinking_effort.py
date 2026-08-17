# Copyright (c) ModelScope Contributors. All rights reserved.
"""One knob (`reasoning_effort`) lowered onto each endpoint's own spelling.

The tiers and wire shapes asserted here come from the vendors' own docs, checked
2026-08-17; the module docstring of ``ms_agent/llm/thinking.py`` has the table.
"""
import pytest

from ms_agent.llm import thinking as T


# --------------------------------------------------------------------------- #
# Which dialect an endpoint speaks
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    'base_url,expected',
    [
        ('https://dashscope.aliyuncs.com/compatible-mode/v1', 'dashscope'),
        # ATokenPlan and friends are Aliyun MaaS endpoints speaking DashScope.
        ('https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
         'dashscope'),
        ('https://api-inference.modelscope.cn/v1', 'modelscope'),
        ('https://api.deepseek.com', 'deepseek'),
        ('https://open.bigmodel.cn/api/paas/v4', 'zhipu'),
        ('https://api.moonshot.cn/v1', 'moonshot'),
        ('https://api.minimaxi.com/v1', 'minimax'),
        ('https://openrouter.ai/api/v1', 'openrouter'),
        ('https://api.openai.com/v1', 'openai'),
        ('https://vllm.internal.corp:8000/v1', 'unknown'),
    ],
)
def test_family_comes_from_the_host(base_url, expected):
    assert T.endpoint_family(base_url) == expected


def test_anthropic_protocol_beats_the_host():
    """DeepSeek serves an Anthropic-compatible gateway on its own domain. The
    body shape follows the protocol, not the vendor."""
    assert T.endpoint_family('https://api.deepseek.com/anthropic',
                             'anthropic') == 'anthropic'


# --------------------------------------------------------------------------- #
# Canonical input
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize('raw,expected', [
    (None, 'auto'),
    ('', 'auto'),
    ('auto', 'auto'),
    ('  HIGH ', 'high'),
    ('x-high', 'xhigh'),
    ('none', 'off'),
    ('disabled', 'off'),
    (True, 'high'),
    (False, 'off'),
    ('turbo', None),
])
def test_effort_is_normalized_leniently(raw, expected):
    assert T.normalize_effort(raw) == expected


def test_clamp_prefers_the_next_weaker_tier():
    """An effort tier is a quality FLOOR, not a ceiling, so a clamp must never
    land above the request — see zlxlabs/llm-compat#11, where clamping UP into a
    support set's interior gap jumped three tiers and billed at the top one."""
    assert T.clamp_effort('medium', ('low', 'high', 'max')) == 'low'
    assert T.clamp_effort('max', ('off', 'low', 'medium', 'high')) == 'high'
    assert T.clamp_effort('low', ('low', 'high', 'max')) == 'low'


def test_a_thinking_tier_never_collapses_into_off():
    """`off` is a different request, not the bottom rung. Clamping downward
    must not turn "think a little" into "do not think"."""
    assert T.clamp_effort('minimal', ('off', 'high')) == 'high'
    assert T.clamp_effort('low', ('off', 'high')) == 'high'
    # ...and asking to switch off where that is impossible lands on the weakest
    # thinking tier, which is also the remedy Zhipu prescribes for GLM-5.3.
    assert T.clamp_effort('off', ('low', 'high', 'max')) == 'low'


def test_kimi_can_be_switched_off_after_all():
    """The docs say Kimi K3 always thinks; the endpoint disagrees. Probed
    2026-08-17, `reasoning_effort: none` yields ZERO characters of reasoning on
    both k3 and k2.6, so "off" goes out as a real value rather than being
    clamped up to the floor tier."""
    got = T.plan('off', base_url='https://api.moonshot.cn/v1')
    assert got['effective'] == 'off'
    assert got['params'] == {'reasoning_effort': 'none'}


# --------------------------------------------------------------------------- #
# Lowering
# --------------------------------------------------------------------------- #
def test_boolean_endpoints_get_a_boolean():
    got = T.plan('max', base_url='https://api-inference.modelscope.cn/v1')
    assert got['params'] == {'extra_body': {'enable_thinking': True}}
    assert got['effective'] == 'high'  # the ladder collapses to on/off here


def test_dashscope_gets_both_knobs_because_they_do_different_jobs():
    """They cover disjoint sets of models on this host. `reasoning_effort: high`
    ALONE leaves qwen-plus at zero reasoning — it does not support the effort
    field, so only `enable_thinking` reaches it (probed 2026-08-17: 0 characters
    vs 543 with the flag) — while qwen3.8-max is the one Qwen model that does
    take an effort tier. Sending one without the other loses half the models."""
    got = T.plan('low', base_url='https://dashscope.aliyuncs.com/v1')
    assert got['params'] == {
        'extra_body': {
            'enable_thinking': True
        },
        'reasoning_effort': 'low',
    }


def test_dashscope_drops_only_the_value_it_measurably_rejects():
    """`max` is the one 400 on this host (qwen3.7-plus rejects it, qwen3.8-max
    accepts all seven — each value probed individually 2026-08-18), and it is
    documented as an alias of `xhigh`, which is where the downward clamp lands.
    Every other rung reaches the endpoint untouched."""
    got = T.plan('max', base_url='https://dashscope.aliyuncs.com/v1')
    assert got['effective'] == 'xhigh'
    assert got['params']['reasoning_effort'] == 'xhigh'
    for rung in ('minimal', 'low', 'medium', 'high', 'xhigh'):
        sent = T.plan(rung, base_url='https://dashscope.aliyuncs.com/v1')
        assert sent['effective'] == rung
        assert sent['params']['reasoning_effort'] == rung


def test_dashscope_off_stays_a_plain_boolean():
    """The models that refuse every effort value (qwen-vl-*) still accept
    `enable_thinking: false`, so "off" must not go out as an effort tier."""
    got = T.plan('off', base_url='https://dashscope.aliyuncs.com/v1')
    assert got['params'] == {'extra_body': {'enable_thinking': False}}


def test_a_hand_written_thinking_budget_suppresses_our_effort():
    """DashScope 400s on the pair ("'reasoning_effort' and 'thinking_budget'
    cannot be set simultaneously") — and thinking_budget is exactly what the
    settings hint invites people to add, so the two suggestions would collide.
    The hand-written key wins; only our effort is dropped, not the switch."""
    out = T.apply_effort(
        {
            'reasoning_effort': 'high',
            'extra_body': {
                'thinking_budget': 2048
            }
        },
        base_url='https://dashscope.aliyuncs.com/v1')
    assert out == {
        'extra_body': {
            'thinking_budget': 2048,
            'enable_thinking': True
        }
    }
    # The preview the settings page renders has to agree with that.
    shown = T.plan('high',
                   base_url='https://dashscope.aliyuncs.com/v1',
                   existing={'extra_body': {
                       'thinking_budget': 2048
                   }})
    assert 'reasoning_effort' not in shown['params']


def test_ladder_endpoints_get_a_tier():
    got = T.plan('max', base_url='https://open.bigmodel.cn/api/paas/v4')
    assert got['params'] == {'reasoning_effort': 'max'}


def test_deepseek_off_uses_the_thinking_object_not_an_effort():
    """DeepSeek's reasoning_effort has no "none" rung — low/high/max only — so
    the only way to switch thinking off is the `thinking` object."""
    got = T.plan('off', base_url='https://api.deepseek.com')
    assert got['params'] == {'extra_body': {'thinking': {'type': 'disabled'}}}


def test_openai_off_is_the_none_tier():
    got = T.plan('off', base_url='https://api.openai.com/v1')
    assert got['params'] == {'reasoning_effort': 'none'}


def test_minimax_on_means_adaptive():
    got = T.plan('high', base_url='https://api.minimaxi.com/v1')
    assert got['params'] == {
        'extra_body': {
            'thinking': {
                'type': 'adaptive'
            }
        }
    }


def test_openrouter_uses_its_own_unified_object():
    assert T.plan('low', base_url='https://openrouter.ai/api/v1')['params'] \
        == {'extra_body': {'reasoning': {'effort': 'low'}}}
    assert T.plan('off', base_url='https://openrouter.ai/api/v1')['params'] \
        == {'extra_body': {'reasoning': {'enabled': False}}}


# --------------------------------------------------------------------------- #
# `auto` — the default, and the whole point
# --------------------------------------------------------------------------- #
def test_auto_sends_nothing_almost_everywhere():
    """Vendor defaults are per-model and they move (DashScope alone has qwen3.5+
    defaulting ON and qwen-plus defaulting OFF). Sending nothing inherits
    whatever they tuned, which is the only thing that stays correct for free."""
    for base_url in ('https://api-inference.modelscope.cn/v1',
                     'https://api.deepseek.com',
                     'https://open.bigmodel.cn/api/paas/v4',
                     'https://api.openai.com/v1',
                     'https://vllm.internal.corp:8000/v1'):
        assert T.plan('auto', base_url=base_url)['params'] == {}


def test_auto_is_explicit_only_where_silence_would_mean_off():
    # Anthropic: our Messages transport always writes a `thinking` block and
    # absent means disabled, so Claude would never think.
    assert T.plan(None, base_url='', protocol='anthropic')['params'] == {
        'extra_body': {
            'enable_thinking': True
        }
    }
    # DashScope: qwen-plus/turbo/flash and qwen3-max default thinking OFF.
    assert T.plan(None, base_url='https://dashscope.aliyuncs.com/v1')[
        'params'] == {
            'extra_body': {
                'enable_thinking': True
            }
        }


# --------------------------------------------------------------------------- #
# apply_effort: what actually reaches the client
# --------------------------------------------------------------------------- #
def test_the_canonical_key_never_reaches_the_wire():
    """`auto` and `off` are ours, not any vendor's. Leaving the key in place
    would send `reasoning_effort: "auto"` to an endpoint that validates it."""
    out = T.apply_effort({'reasoning_effort': 'auto', 'temperature': 0.3},
                         base_url='https://api-inference.modelscope.cn/v1')
    assert out == {'temperature': 0.3}


def test_a_hand_written_wire_value_wins_over_the_knob():
    """extra_body is the escape hatch; someone who reached for it meant it."""
    out = T.apply_effort(
        {
            'reasoning_effort': 'high',
            'extra_body': {
                'enable_thinking': False
            }
        },
        base_url='https://dashscope.aliyuncs.com/v1')
    assert out == {'extra_body': {'enable_thinking': False}}


def test_unrelated_extra_body_keys_survive_lowering():
    out = T.apply_effort(
        {
            'reasoning_effort': 'high',
            'extra_body': {
                'thinking_budget': 2048
            }
        },
        base_url='https://dashscope.aliyuncs.com/v1')
    assert out == {
        'extra_body': {
            'thinking_budget': 2048,
            'enable_thinking': True
        }
    }


def test_requests_without_the_knob_are_untouched_where_auto_is_silent():
    kwargs = {'temperature': 0.3, 'extra_body': {'enable_thinking': True}}
    assert T.apply_effort(kwargs, base_url='https://x/v1') is kwargs


def test_an_absent_knob_means_auto_not_nothing():
    """Unset has to behave exactly like an explicit `auto`, or the two endpoints
    where auto speaks up would depend on whether a caller bothered to write the
    key."""
    out = T.apply_effort({'temperature': 0.3},
                         base_url='https://dashscope.aliyuncs.com/v1')
    assert out == {
        'temperature': 0.3,
        'extra_body': {
            'enable_thinking': True
        }
    }
    # ...and it still yields to a hand-written wire value.
    kwargs = {'extra_body': {'enable_thinking': False}}
    assert T.apply_effort(
        kwargs, base_url='https://dashscope.aliyuncs.com/v1') == kwargs


def test_a_reasoning_effort_refusal_is_recognized():
    """The fallback used to look only for qwen-style names, so a 400 on the
    modern field would not have been healed."""
    assert T.is_thinking_refusal(
        RuntimeError('Error code: 400 - unknown parameter reasoning_effort'))


# --------------------------------------------------------------------------- #
# Through the real transports
# --------------------------------------------------------------------------- #
class _Recorder:

    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return 'completion'


def _fake_client(recorder, base_url):
    ns = type('NS', (), {})
    client = ns()
    client.chat = ns()
    client.chat.completions = recorder
    client.base_url = base_url
    return client


def test_transport_lowers_the_knob_onto_the_endpoint():
    from ms_agent.llm.transport import openai_compat as TC

    rec = _Recorder()
    tr = TC.OpenAICompatTransport.__new__(TC.OpenAICompatTransport)
    tr.client = _fake_client(rec, 'https://api.deepseek.com')
    tr.model = 'deepseek-v4-pro'
    tr.args = {}
    tr._format_input_message = lambda m: m

    tr._call_llm([], None, reasoning_effort='medium')
    # DeepSeek reports the full vocabulary when handed a bogus value, `medium`
    # included, so the tier reaches it untouched.
    assert rec.calls[0]['reasoning_effort'] == 'medium'
    assert 'extra_body' not in rec.calls[0]


def test_the_knob_is_not_an_anthropic_parameter():
    """Why the Anthropic transport has to lower BEFORE its signature filter:
    `reasoning_effort` is not a Messages API argument, so filtering first would
    silently drop the knob instead of turning it into a `thinking` block."""
    import inspect

    anthropic = pytest.importorskip('anthropic')
    params = inspect.signature(
        anthropic.Anthropic(api_key='x').messages.create).parameters
    assert 'reasoning_effort' not in params
    assert 'extra_body' in params  # ...but the shape we lower into survives


def test_a_refused_tier_falls_all_the_way_back():
    """qwen-vl-max rejects every effort value (DashScope converts the tier into
    a thinking_budget, which that model has no room for). The fallback has to
    strip the tier as well as the switch, or the retry repeats the 400."""
    from ms_agent.llm.transport import openai_compat as TC

    class _Refuser(_Recorder):

        def create(self, **kwargs):
            self.calls.append(kwargs)
            asked = (kwargs.get('reasoning_effort')
                     or (kwargs.get('extra_body') or {}).get('enable_thinking'))
            if asked:
                raise RuntimeError(
                    'Error code: 400 - The thinking_budget parameter must be a '
                    'positive integer and not greater than 0')
            return 'completion'

    rec = _Refuser()
    tr = TC.OpenAICompatTransport.__new__(TC.OpenAICompatTransport)
    tr.client = _fake_client(rec, 'https://dashscope.aliyuncs.com/v1')
    tr.model = 'qwen-vl-max'
    tr.args = {}
    tr._format_input_message = lambda m: m

    T.MODELS_REFUSING_THINKING.clear()
    try:
        out = tr._call_llm([], None, reasoning_effort='high')
    finally:
        T.MODELS_REFUSING_THINKING.clear()

    assert out == 'completion'
    assert rec.calls[0]['reasoning_effort'] == 'high'
    assert 'reasoning_effort' not in rec.calls[1]
    assert rec.calls[1]['extra_body'] == {'enable_thinking': False}


# --------------------------------------------------------------------------- #
# Bugs the unit tests missed and a live matrix caught
# --------------------------------------------------------------------------- #
def test_lowering_twice_would_destroy_the_tier():
    """Documents WHY each transport lowers exactly once.

    The canonical key and DashScope's wire key are both `reasoning_effort`, so
    the operation is not idempotent: a second pass reads the `enable_thinking`
    the first pass added as "the caller is driving thinking by hand" and stands
    down — deleting the tier we ourselves just set. Two call sites were doing
    this, which silently reduced every DashScope request back to a bare switch.
    """
    base = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    once = T.apply_effort({'reasoning_effort': 'low'}, base_url=base)
    assert once['reasoning_effort'] == 'low'
    assert 'reasoning_effort' not in T.apply_effort(once, base_url=base)


def test_generate_sends_the_tier_all_the_way_to_the_client():
    """The end-to-end shape, through `generate()` and its signature filter —
    the level the double-lowering bug lived at and a `_call_llm` test could not
    see."""
    from ms_agent.llm.transport import openai_compat as TC

    class _SigRecorder(_Recorder):
        """`generate()` filters kwargs against create()'s SIGNATURE, so a stub
        taking bare **kwargs would drop every argument — including `stream` —
        and quietly test nothing."""

        def create(self,
                   *,
                   model=None,
                   messages=None,
                   tools=None,
                   stream=None,
                   max_tokens=None,
                   extra_body=None,
                   reasoning_effort=None,
                   **kw):
            self.calls.append({
                'extra_body': extra_body,
                'reasoning_effort': reasoning_effort,
                'stream': stream,
            })
            return 'completion'

    rec = _SigRecorder()
    tr = TC.OpenAICompatTransport.__new__(TC.OpenAICompatTransport)
    tr.client = _fake_client(
        rec, 'https://dashscope.aliyuncs.com/compatible-mode/v1')
    tr.model = 'qwen3.8-max'
    tr.args = {'reasoning_effort': 'max'}
    tr.max_continue_runs = 1
    tr._strip_reasoning_tags = False
    tr._format_input_message = lambda m: m
    tr.format_tools = lambda t: None

    # Only what reached the client matters here; the stub cannot satisfy the
    # response-shaping that follows.
    try:
        tr.generate([])
    except Exception:
        pass
    assert rec.calls[0]['reasoning_effort'] == 'xhigh'
    assert rec.calls[0]['extra_body'] == {'enable_thinking': True}


def test_mandatory_thinking_is_repaired_forwards_not_backwards():
    """OpenRouter answers "Reasoning is mandatory for this endpoint and cannot
    be disabled" for x-ai/grok-4.5. That names a thinking parameter, so the
    refusal path used to claim it and "repair" it by forcing thinking OFF —
    the exact opposite — and then remembered the model, degrading every later
    request in the session."""
    from ms_agent.llm.transport import openai_compat as TC

    class _Mandatory(_Recorder):

        def create(self, **kwargs):
            self.calls.append(kwargs)
            reasoning = (kwargs.get('extra_body') or {}).get('reasoning') or {}
            if reasoning.get('enabled') is False:
                raise RuntimeError(
                    'Error code: 400 - Reasoning is mandatory for this '
                    'endpoint and cannot be disabled.')
            return 'completion'

    rec = _Mandatory()
    tr = TC.OpenAICompatTransport.__new__(TC.OpenAICompatTransport)
    tr.client = _fake_client(rec, 'https://openrouter.ai/api/v1')
    tr.model = 'x-ai/grok-4.5'
    tr.args = {}
    tr._format_input_message = lambda m: m

    T.MODELS_REFUSING_THINKING.clear()
    T.MODELS_REQUIRING_THINKING.clear()
    try:
        assert tr._call_llm([], None, reasoning_effort='off') == 'completion'
        # Repaired by saying nothing, not by forcing the switch the other way.
        assert 'extra_body' not in rec.calls[1]
        assert 'reasoning_effort' not in rec.calls[1]
        # ...and the model is not blacklisted, so a later tier still works.
        assert T.model_key(tr.client, tr.model) not in T.MODELS_REFUSING_THINKING
        tr._call_llm([], None, reasoning_effort='high')
        assert rec.calls[2]['extra_body'] == {'reasoning': {'effort': 'high'}}
    finally:
        T.MODELS_REFUSING_THINKING.clear()
        T.MODELS_REQUIRING_THINKING.clear()


def test_openrouter_style_reasoning_field_is_read():
    """OpenRouter normalizes every upstream's reasoning into `reasoning`, not
    `reasoning_content`. Reading only the latter made every model proxied
    through it look like it never thought."""
    from ms_agent.llm.transport.openai_compat import _reasoning_of

    ns = type('NS', (), {})
    delta = ns()
    delta.reasoning = 'thought about it'
    assert _reasoning_of(delta) == 'thought about it'

    both = ns()
    both.reasoning_content = 'native'
    both.reasoning = 'proxied'
    assert _reasoning_of(both) == 'native'  # the native field wins
    assert _reasoning_of(ns()) == ''
