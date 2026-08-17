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
    ('x-high', 'max'),
    ('none', 'off'),
    ('disabled', 'off'),
    (True, 'high'),
    (False, 'off'),
    ('turbo', None),
])
def test_effort_is_normalized_leniently(raw, expected):
    assert T.normalize_effort(raw) == expected


def test_clamp_prefers_the_next_stronger_tier():
    # DeepSeek/Zhipu/Kimi expose low/high/max: a request for medium should not
    # quietly become low.
    assert T.clamp_effort('medium', ('low', 'high', 'max')) == 'high'
    # Nothing at or above the request -> the ceiling, so "max" caps instead of
    # failing.
    assert T.clamp_effort('max', ('off', 'low', 'medium', 'high')) == 'high'
    assert T.clamp_effort('low', ('low', 'high', 'max')) == 'low'


def test_off_clamps_up_on_models_that_cannot_stop_thinking():
    """Kimi K3 always thinks and GLM-5.3 fails the request if you send the old
    disable shape. Asking for "off" there should land on the floor tier, not be
    dropped."""
    assert T.plan('off', base_url='https://api.moonshot.cn/v1')['effective'] \
        == 'low'


# --------------------------------------------------------------------------- #
# Lowering
# --------------------------------------------------------------------------- #
def test_boolean_endpoints_get_a_boolean():
    got = T.plan('max', base_url='https://api-inference.modelscope.cn/v1')
    assert got['params'] == {'extra_body': {'enable_thinking': True}}
    assert got['effective'] == 'high'  # the ladder collapses to on/off here


def test_dashscope_gets_both_knobs_because_they_do_different_jobs():
    """Probed 2026-08-17: `reasoning_effort: high` ALONE leaves qwen-plus at
    zero reasoning — only `enable_thinking` turns thinking on there — while
    `reasoning_effort` is what actually sets depth on qwen3.8-max (none 0 →
    low 78 → high 222 → xhigh 393 characters). Sending one without the other
    silently loses half the control."""
    got = T.plan('low', base_url='https://dashscope.aliyuncs.com/v1')
    assert got['params'] == {
        'extra_body': {
            'enable_thinking': True
        },
        'reasoning_effort': 'low',
    }


def test_dashscope_max_is_spelled_xhigh():
    """`max` is rejected outright — qwen3.7-plus answers 400 listing the valid
    set — while `xhigh` is accepted by every qwen3.7/3.8 probed."""
    got = T.plan('max', base_url='https://dashscope.aliyuncs.com/v1')
    assert got['params']['reasoning_effort'] == 'xhigh'
    assert got['effective'] == 'max'


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
    # medium is not a DeepSeek tier; it clamps up to high rather than down.
    assert rec.calls[0]['reasoning_effort'] == 'high'
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
