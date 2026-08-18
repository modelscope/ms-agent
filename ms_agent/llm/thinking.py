# Copyright (c) ModelScope Contributors. All rights reserved.
"""One semantic knob for "how hard should the model think", plus the fallback
for models that refuse to be asked at all.

Every vendor spells thinking differently and none of them spells it the same way
for long. Per-model real tiers, from each vendor's own docs and cross-checked
against opencode's model catalog (both agree line for line), 2026-08-18:

=================  ==================================  ====================  ========
model / endpoint   modern field                        DISTINCT tiers        default
=================  ==================================  ====================  ========
xAI grok-4.5       ``reasoning_effort``                low/medium/high       high
xAI grok-4.6       ``reasoning_effort``                + xhigh               high
DeepSeek v4-*      ``reasoning_effort`` /              high/max              ON, high
                   ``thinking: {type}``                (+low; med/xhigh→high)
Zhipu glm-5.2      ``reasoning_effort``                high/max              ``max``
Zhipu glm-5.3      ``reasoning_effort``                low/high/max          ``max``
Zhipu glm-5/5.1    ``thinking: {type}`` only           — (no effort field)   ON
Moonshot kimi-k3   ``reasoning_effort``                low/high/max          ``max``
Moonshot kimi-k2.x ``thinking: {type}`` only           — (no effort field)   varies
MiniMax M3         ``thinking: {type}``                adaptive/disabled     ON via
                   (+ ``reasoning_split`` for the      (NOT a depth knob)    OpenAI,
                   output format, not the depth)                             OFF via
                                                                             Anthropic
DashScope          ``enable_thinking`` AND, on         low/medium/xhigh      per model
 qwen3.8-max       ``reasoning_effort``; the two       (high/max→xhigh,
                   CANNOT travel with                  minimal→low)
                   ``thinking_budget``
DashScope other    ``enable_thinking`` only            — (no effort field)   per model
ModelScope         ``enable_thinking`` (gateway) /     — (no effort field)   per model
                   ``chat_template_kwargs``
OpenRouter         ``reasoning: {effort|max_tokens}``  per model, published  inferred
                                                       in ``/api/v1/models``
Anthropic          ``output_config.effort`` +          low…max               high
                   ``thinking: {type: adaptive}``
=================  ==================================  ====================  ========

Four things follow, and they are the whole design:

1. ``reasoning_effort`` is the de-facto standard. It is the name callers use
   here, so anyone who knows one vendor already knows this one — and it survives
   the OpenAI SDK's signature filter, unlike an invented name.

2. Defaults are per-MODEL and they move. On DashScope alone, qwen3.5 and later
   default thinking ON while qwen-plus/turbo/flash and qwen3-max default it OFF;
   ``kimi-k2.6`` defaults OFF on Alibaba's deployment and ON on Moonshot's, same
   name; MiniMax M3 defaults it ON through the OpenAI-compatible API and OFF
   through the Anthropic-compatible one, same model. Any table of defaults we
   wrote would be wrong within a release. So we do not write one: ``auto`` sends
   NOTHING and inherits whatever the vendor tuned, and the lowering table below
   is consulted ONLY when a caller asked for a specific tier. A bug in it can
   then only affect someone who explicitly configured thinking, who will see it
   immediately — rather than silently changing every request.

3. **"Accepted" is not "distinct", and a wire enum is not a capability list.**
   Two traps, both of which this module fell into once. OpenRouter's rejection
   message lists its whole GATEWAY vocabulary, identically for every model, then
   maps unsupported-but-valid tiers to the nearest one the model has — sending
   ``max`` to grok-4.5 returns 200, not an error. And DeepSeek's ``/v1`` enum
   went from five values to seven between 2026-07-27 and 2026-08-17 (``minimal``
   flipped from a hard 400 to accepted, and the declaration order changed), so a
   vocabulary derived from probing has a measured shelf life of about three
   weeks. The table below therefore records only what an endpoint REJECTS, and
   leaves each vendor's documented aliasing to the vendor.

4. **The tier is a request, not a promise.** Measured in billed reasoning tokens
   (3 samples per cell, 2026-08-18), the effect ranges from crisp to absent:
   glm-5.2 moves monotonically and treats ``minimal`` as off (0 tokens, 3/3);
   glm-5.1 does not move at all (it has no effort field); grok-4.5 through
   OpenRouter shows no trend across six tiers; qwen3.8-max is non-monotonic.
   So this module translates the knob faithfully and does not pretend to know
   what the model will do with it.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

#: Wire keys that carry a thinking request, in any vendor's spelling. Used both
#: to strip a request back down and to recognise a refusal.
THINKING_PARAM_KEYS = ('enable_thinking', 'thinking_budget', 'thinking',
                       'reasoning_effort', 'reasoning')

#: The canonical knob callers set, in ``generation_config``.
EFFORT_KEY = 'reasoning_effort'

#: Canonical ladder, weakest to strongest. ``auto`` is not a rung — it means
#: "no opinion", which is the default and is never sent anywhere.
#:
#: These are not our invention: every endpoint that VALIDATES the field reports
#: the same seven values (probed 2026-08-17 by sending a bogus one and reading
#: the error) — GLM-5.2 "none、minimal、low、medium、high、xhigh、max",
#: OpenRouter "max|xhigh|high|medium|low|minimal|none", DeepSeek the same list,
#: DashScope the same minus ``max``. Matching their vocabulary exactly means a
#: value the user types usually reaches the model untouched, instead of being
#: clamped onto a smaller set we made up.
EFFORT_TIERS = ('off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')

#: Ranks for clamping a requested tier onto what an endpoint accepts. Gaps leave
#: room for rungs a vendor may add later without renumbering.
EFFORT_RANKS = {
    'off': 0,
    'minimal': 10,
    'low': 20,
    'medium': 30,
    'high': 40,
    'xhigh': 60,
    'max': 70,
}

_EFFORT_ALIASES = {
    'none': 'off',
    'disabled': 'off',
    'disable': 'off',
    'false': 'off',
    'no': 'off',
    'min': 'minimal',
    'med': 'medium',
    'extrahigh': 'xhigh',
    'maximum': 'max',
    'true': 'high',
    'on': 'high',
    'enabled': 'high',
}

#: ``(base_url, model)`` pairs observed to refuse the thinking parameters.
MODELS_REFUSING_THINKING: set = set()

#: ``(base_url, model)`` pairs that refuse to STOP thinking. The opposite
#: complaint, and it needs the opposite repair — OpenRouter answers
#: "Reasoning is mandatory for this endpoint and cannot be disabled" for
#: x-ai/grok-4.5, and healing that by forcing thinking off (the other set's
#: repair) both misses the point and poisons every later request for the model.
MODELS_REQUIRING_THINKING: set = set()


# --------------------------------------------------------------------------- #
# Endpoint families
# --------------------------------------------------------------------------- #
# Keyed on the endpoint HOST, not the model name. Hosts are stable — a vendor
# ships new model names every few weeks but keeps the same API surface, and two
# earlier attempts at a model-name table were both wrong within days.

#: host substring -> family name.
_HOST_FAMILIES = (
    ('dashscope.aliyuncs.com', 'dashscope'),
    ('maas.aliyuncs.com', 'dashscope'),  # ATokenPlan et al. speak DashScope
    ('api-inference.modelscope.cn', 'modelscope'),
    ('api.deepseek.com', 'deepseek'),
    ('open.bigmodel.cn', 'zhipu'),
    ('bigmodel.cn', 'zhipu'),
    ('z.ai', 'zhipu'),
    ('api.moonshot.cn', 'moonshot'),  # CN
    ('api.moonshot.ai', 'moonshot'),  # international, per Moonshot's docs
    ('api.kimi.com', 'moonshot'),
    ('api.minimax', 'minimax'),
    ('openrouter.ai', 'openrouter'),
    ('api.openai.com', 'openai'),
)


def endpoint_family(base_url: str, protocol: str = '') -> str:
    """Which dialect of "thinking" this endpoint speaks.

    ``anthropic`` wins over the host: a vendor's Anthropic-compatible gateway
    (DeepSeek serves one at ``api.deepseek.com/anthropic``) takes Messages-API
    shapes, not its own OpenAI ones.
    """
    if (protocol or '').lower() == 'anthropic':
        return 'anthropic'
    host = (urlparse(base_url or '').hostname or str(base_url or '')).lower()
    for needle, family in _HOST_FAMILIES:
        if needle in host:
            return family
    return 'unknown'


#: Tiers each family actually accepts, weakest to strongest. A request outside
#: the set is clamped (see ``clamp_effort``).
# What each family ACCEPTS without erroring — deliberately NOT "which tiers are
# distinct behaviours there". Those are two different questions and only the
# first one is ours: every vendor documents its own collapse (DashScope maps
# `high`/`max` onto `xhigh` and `minimal` onto `low`; Zhipu maps `low`/`medium`
# onto `high` and `xhigh` onto `max`; DeepSeek publishes a five-row table) and
# applies it per MODEL, which a host-keyed table cannot express and should not
# try to. So we only subtract values an endpoint is measured to REJECT, and let
# the vendor alias the rest.
_FAMILY_TIERS = {
    # `max` is the single measured rejection on this host: qwen3.7-plus answers
    # 400 for it while accepting none/minimal/low/medium/high/xhigh, and
    # qwen3.8-max accepts all seven (each value probed individually,
    # 2026-08-18). Excluding it protects the qwen3.7 family and costs the one
    # model that does take it nothing, because DashScope documents `max` as an
    # alias of `xhigh` — exactly where the downward clamp lands. The canonical
    # set for qwen3.8-max, the only Qwen with a real effort field, is
    # low / medium / xhigh.
    'dashscope': ('off', 'minimal', 'low', 'medium', 'high', 'xhigh'),
    # No effort field at all: the switch is a boolean, so every "how hard"
    # collapses onto "on". Corroborated for MiniMax M3 and the ModelScope-hosted
    # Qwen3.5 family by opencode's model catalog, which lists them as `toggle`.
    'modelscope': ('off', 'high'),
    'minimax': ('off', 'high'),
    'anthropic': ('off', 'high'),
    # Everyone else accepts the whole vocabulary. Endpoints that do not validate
    # it (glm-5.1, glm-5, every Kimi, MiniMax, ModelScope) ignore an unknown
    # value rather than failing, so passing a tier through costs nothing.
    'deepseek': EFFORT_TIERS,
    'zhipu': EFFORT_TIERS,
    'moonshot': EFFORT_TIERS,
    'openrouter': EFFORT_TIERS,
    'openai': EFFORT_TIERS,
    'unknown': EFFORT_TIERS,
}

#: Extra raw keys a family understands, surfaced to users as an example of what
#: they may add by hand. We never send these ourselves — their defaults are
#: vendor-tuned and would be one more thing to keep in sync.
FAMILY_EXTRA_HINTS = {
    'dashscope': 'thinking_budget (1-32768)',
    'modelscope': 'chat_template_kwargs',
    'openrouter': 'reasoning.max_tokens',
    'anthropic': 'thinking_budget',
}

#: Raw keys that cannot travel with our lowered ``reasoning_effort``. DashScope
#: rejects the pair outright ("'reasoning_effort' and 'thinking_budget' cannot
#: be set simultaneously") — and ``thinking_budget`` is precisely what we invite
#: people to add by hand above, so the two suggestions would collide.
_EFFORT_CONFLICTS = ('thinking_budget', )


def normalize_effort(raw: Any) -> Optional[str]:
    """Free-form input -> a canonical tier, ``'auto'``, or ``None`` if garbage.

    Booleans are accepted because that is what the old ``enable_thinking``
    spelling used, and some config files carry it through as a YAML bool.
    """
    if raw is None:
        return 'auto'
    if isinstance(raw, bool):
        return 'high' if raw else 'off'
    if not isinstance(raw, str):
        return None
    key = raw.strip().lower().replace('-', '').replace('_', '').replace(' ', '')
    if key in ('', 'auto', 'default', 'inherit'):
        return 'auto'
    key = _EFFORT_ALIASES.get(key, key)
    return key if key in EFFORT_TIERS else None


def clamp_effort(tier: str, supported: Tuple[str, ...]) -> str:
    """Nearest tier the endpoint accepts, preferring the next WEAKER one.

    Direction matters, and the intuitive choice is the wrong one. An effort tier
    is a quality FLOOR the caller is willing to pay for, not a ceiling — so
    landing above the request spends money they did not ask for. A published
    post-mortem of the opposite choice (zlxlabs/llm-compat#11, merged
    2026-08-05) describes exactly that: a request for the middle rung clamped
    UP into a support set's interior gap, jumped three tiers, was billed at the
    top tier, and said nothing louder than a log line.

    ``off`` is not treated as the bottom of the ladder: it is a different
    request, so a thinking tier never collapses into it. On an endpoint that
    only has a switch, the weakest thinking tier is "on"; on one that cannot
    stop thinking at all (Kimi K3 per Moonshot's FAQ), ``off`` lands on the
    weakest tier — which is also the remedy Zhipu prescribes for GLM-5.3
    ("change disabled to enabled and set reasoning_effort to low").
    """
    if tier in supported:
        return tier
    thinking = [t for t in supported if t != 'off']
    if not thinking:  # switch-only, and we were not asked to switch off
        return supported[0]
    ranked = sorted(thinking, key=lambda t: EFFORT_RANKS[t])
    want = EFFORT_RANKS[tier]
    weaker = [t for t in ranked if EFFORT_RANKS[t] <= want]
    return weaker[-1] if weaker else ranked[0]


def _merge_extra_body(params: Dict[str, Any], extra: Dict[str, Any]) -> None:
    body = dict(params.get('extra_body') or {})
    body.update(extra)
    params['extra_body'] = body


def lower_effort(tier: str, family: str) -> Dict[str, Any]:
    """The wire parameters that express ``tier`` on ``family``.

    ``tier`` must already be clamped to what the family supports.
    """
    params: Dict[str, Any] = {}
    if family == 'dashscope':
        # BOTH knobs, because they cover disjoint sets of models on this host.
        # `enable_thinking` is the only lever for the many models that take no
        # effort field (every Qwen except qwen3.8-max) and it is what turns
        # thinking on for the ones that default it off (qwen-plus: 0 characters
        # of reasoning from `reasoning_effort: high` alone, 543 with the flag —
        # because qwen-plus does not support the effort field at all). Alibaba's
        # own CLI and opencode both send the flag here for the same reason.
        # Models that understand only one of the two ignore the other.
        #
        # Known imprecision, deliberate: DashScope also hosts GLM, DeepSeek and
        # Kimi, whose switch dialect on this host is `thinking.enabled` /
        # `thinking: {type}` rather than `enable_thinking`. Getting that right
        # needs per-model branching on a host-keyed table; the flag is ignored
        # rather than rejected there, so the cost is a no-op field, not an error.
        _merge_extra_body(params, {'enable_thinking': tier != 'off'})
        if tier != 'off':
            params[EFFORT_KEY] = tier
    elif family in ('modelscope', 'anthropic'):
        # Boolean switch. On the Anthropic transport this is read back out and
        # turned into the Messages-API `thinking` block.
        _merge_extra_body(params, {'enable_thinking': tier != 'off'})
    elif family == 'minimax':
        # `adaptive` rather than `enabled`: M3 decides per request whether the
        # reasoning is worth it, which is what "on" should mean for an agent.
        _merge_extra_body(
            params,
            {'thinking': {
                'type': 'disabled' if tier == 'off' else 'adaptive'
            }})
    elif family in ('deepseek', 'zhipu'):
        if tier == 'off':
            # NOT `reasoning_effort: none`, even though the newer models accept
            # it: glm-5.1 and glm-5 do not validate the field and simply IGNORE
            # it (probed 2026-08-17 — 896 and 986 characters of reasoning with
            # `none` set). The `thinking` object is the only spelling every
            # generation honours. If a model rejects it outright (GLM-5.3 no
            # longer allows thinking to be disabled), the mandatory-thinking
            # repair below strips the request rather than failing the turn.
            _merge_extra_body(params, {'thinking': {'type': 'disabled'}})
        else:
            params[EFFORT_KEY] = tier
    elif family == 'moonshot':
        # Kimi is the other way round: it honours `none` on both k3 and k2.6
        # (0 characters of reasoning), so the effort field alone covers the
        # whole range and no second shape is needed.
        params[EFFORT_KEY] = 'none' if tier == 'off' else tier
    elif family == 'openrouter':
        # OpenRouter's own unified object; `enabled: false` is how it says off.
        _merge_extra_body(
            params, {'reasoning': {
                'enabled': False
            } if tier == 'off' else {
                'effort': tier
            }})
    else:  # openai, unknown
        params[EFFORT_KEY] = 'none' if tier == 'off' else tier
    return params


def output_format_params(family: str) -> Dict[str, Any]:
    """Params about WHERE the reasoning is delivered, not how much of it to do.

    Separate from the effort ladder on purpose: this asks nothing about how hard
    to think, so it applies even under ``auto``, where we deliberately say
    nothing about depth.

    MiniMax is the only family that needs it. Its OpenAI-compatible endpoint
    inlines the reasoning into the answer as ``<think>…</think>`` (its docs call
    that the native format) and offers ``reasoning_split`` to deliver it in
    ``reasoning_content`` instead — which its docs "strongly recommend", and
    which is the only shape it reads back: probed 2026-08-18, replaying a
    separate ``reasoning_content`` in NATIVE mode behaves exactly like
    discarding the thinking, because the field is not part of that format.
    Verified on M3, M2.7 and M2.5: no error, reasoning moves out of ``content``.

    Host-gated by construction — third-party hosts of the same weights reject
    the parameter outright (NVIDIA NIM: "Unsupported parameter(s):
    'reasoning_split'"), and they are a different family here.
    """
    if family == 'minimax':
        return {'extra_body': {'reasoning_split': True}}
    return {}


def auto_params(family: str) -> Dict[str, Any]:
    """What ``auto`` sends. Almost always nothing — see the module docstring.

    Two endpoints get an explicit ``true`` anyway:

    * ``anthropic`` — our Messages transport has no way to say "no opinion": it
      always writes a ``thinking`` block, and absent means ``disabled``. Claude
      would then never think.
    * ``dashscope`` — its older commercial hybrids (qwen-plus, qwen-turbo,
      qwen-flash, qwen3-max) default thinking OFF, and those are exactly the
      cheap models people leave selected. Newer qwen3.5+ default it on, where
      the flag is a redundant no-op (probed: 258 vs 276 characters of reasoning
      with and without it).
    """
    if family in ('anthropic', 'dashscope'):
        return {'extra_body': {'enable_thinking': True}}
    return {}


def _drop_conflicts(params: Dict[str, Any],
                    existing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Yield to whatever the caller wrote by hand.

    Two degrees of yielding, because the raw keys mean different things:

    * A **switch** key (``enable_thinking``, ``thinking``, ``reasoning``) means
      the caller is driving thinking themselves, so we contribute NOTHING —
      adding a tier next to their ``enable_thinking: false`` would ask for a
      depth and a shutdown in the same request.
    * ``thinking_budget`` is only a depth, so the switch may still go out; but
      our effort must not, because DashScope rejects that exact pair
      ("'reasoning_effort' and 'thinking_budget' cannot be set simultaneously")
      — and ``thinking_budget`` is precisely what the settings hint invites
      people to add by hand, so the two suggestions would collide.
    """
    if not params or not isinstance(existing, dict):
        return params
    extra = existing.get('extra_body')
    present = set(existing) | (set(extra) if isinstance(extra, dict) else set())
    switches = set(THINKING_PARAM_KEYS) - {EFFORT_KEY} - set(_EFFORT_CONFLICTS)
    if present & switches:
        return {}
    if present.isdisjoint(_EFFORT_CONFLICTS):
        return params
    return {k: v for k, v in params.items() if k != EFFORT_KEY}


def plan(effort: Any,
         *,
         base_url: str = '',
         protocol: str = '',
         existing: Optional[Dict[str, Any]] = None) -> dict:
    """Resolve a canonical effort into a wire plan, without sending anything.

    Returns ``{'family', 'requested', 'effective', 'params', 'extra_hint'}``.
    ``effective`` is the clamped tier, or ``'auto'``. ``existing`` is the
    request (or stored params) the plan will be merged into, so conflicting raw
    keys are honoured here rather than discovered on the wire. Shared by the
    transports and by the WebUI, so what the settings page shows is what
    actually ships.
    """
    family = endpoint_family(base_url, protocol)
    requested = normalize_effort(effort)
    if requested is None:
        requested = 'auto'
    if requested == 'auto':
        effective, wire = 'auto', auto_params(family)
    else:
        effective = clamp_effort(
            requested, _FAMILY_TIERS.get(family, _FAMILY_TIERS['unknown']))
        wire = lower_effort(effective, family)
    # Where the reasoning is delivered is a separate question from how much of
    # it to do, so it survives `auto` and rides along with every tier.
    for key, value in output_format_params(family).items():
        if key == 'extra_body':
            _merge_extra_body(wire, value)
        else:
            wire.setdefault(key, value)
    return {
        'family': family,
        'requested': requested,
        'effective': effective,
        'params': _drop_conflicts(wire, existing),
        'extra_hint': FAMILY_EXTRA_HINTS.get(family, ''),
    }


def apply_effort(kwargs: Dict[str, Any], *, base_url: str,
                 protocol: str = '') -> Dict[str, Any]:
    """Replace the canonical knob in ``kwargs`` with this endpoint's wire shape.

    Runs even when no knob was set, because "unset" IS ``auto`` and on two
    endpoints auto has something to say (see :func:`auto_params`) — an absent
    key must not mean a different thing from an explicit ``auto``.

    The canonical key is always removed, so a value like ``auto`` or ``off``
    never reaches a vendor that would reject it. Anything the caller set by hand
    wins: raw wire keys already present are left exactly as they are, because
    the raw form is the escape hatch and a user who reached for it means it.
    """
    effort = kwargs.get(EFFORT_KEY, 'auto')
    resolved = plan(effort,
                    base_url=base_url,
                    protocol=protocol,
                    existing={k: v
                              for k, v in kwargs.items() if k != EFFORT_KEY})
    if EFFORT_KEY not in kwargs and not resolved['params']:
        return kwargs  # nothing to say and nothing to strip
    out = dict(kwargs)
    out.pop(EFFORT_KEY, None)
    existing_extra = out.get('extra_body') or {}
    for key, value in resolved['params'].items():
        if key == 'extra_body':
            for sub_key, sub_value in value.items():
                if sub_key not in existing_extra:
                    _merge_extra_body(out, {sub_key: sub_value})
        elif key not in out:
            out[key] = value
    return out


# --------------------------------------------------------------------------- #
# Refusal fallback
# --------------------------------------------------------------------------- #


def model_key(client: Any, model: str) -> tuple:
    return (str(getattr(client, 'base_url', '')), model)


def _is_bad_request(exc: Exception) -> bool:
    status = getattr(exc, 'status_code', None)
    if status is not None and status != 400:
        return False
    return status == 400 or '400' in str(exc)


#: Phrases an endpoint uses to say thinking is not optional here.
_MANDATORY_MARKERS = ('mandatory', 'cannot be disabled', 'can not be disabled',
                      'must be enabled', 'cannot be turned off')


def is_thinking_refusal(exc: Exception) -> bool:
    """A 400 that names the thinking parameters — not any other bad request."""
    if not _is_bad_request(exc):
        return False
    text = str(exc).lower()
    return any(k in text for k in THINKING_PARAM_KEYS)


def is_thinking_mandatory(exc: Exception) -> bool:
    """A 400 complaining that thinking may not be switched OFF.

    Checked before :func:`is_thinking_refusal`, which it would otherwise match
    (the message names ``reasoning``) and be repaired backwards.
    """
    if not _is_bad_request(exc):
        return False
    text = str(exc).lower()
    if not any(k in text for k in THINKING_PARAM_KEYS):
        return False
    return any(marker in text for marker in _MANDATORY_MARKERS)


def asks_to_disable(kwargs: Dict[str, Any]) -> bool:
    """Whether this request is telling the model NOT to think.

    Every family spells "off" differently (see :func:`lower_effort`), and a
    model that merely refuses to be switched off must still be allowed to
    receive a positive tier — so the memo has to know which kind of request it
    is looking at rather than blanking them all.
    """
    extra = kwargs.get('extra_body')
    extra = extra if isinstance(extra, dict) else {}
    if extra.get('enable_thinking') is False or kwargs.get(
            'enable_thinking') is False:
        return True
    for source in (extra, kwargs):
        thinking = source.get('thinking')
        if isinstance(thinking, dict) and thinking.get('type') == 'disabled':
            return True
        reasoning = source.get('reasoning')
        if isinstance(reasoning, dict) and reasoning.get('enabled') is False:
            return True
    return kwargs.get(EFFORT_KEY) in ('none', 'off')


def strip_thinking(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """``kwargs`` with every thinking parameter REMOVED, saying nothing at all.

    The repair for an endpoint that insists on thinking: stop asking it to
    stop. Returns the SAME object when there was nothing to strip.
    """
    extra = kwargs.get('extra_body')
    in_extra = isinstance(extra, dict) and any(k in extra
                                               for k in THINKING_PARAM_KEYS)
    if not in_extra and not any(k in kwargs for k in THINKING_PARAM_KEYS):
        return kwargs
    cleaned = {k: v for k, v in kwargs.items() if k not in THINKING_PARAM_KEYS}
    if in_extra:
        pruned = {
            k: v
            for k, v in extra.items() if k not in THINKING_PARAM_KEYS
        }
        if pruned:
            cleaned['extra_body'] = pruned
        else:
            cleaned.pop('extra_body', None)
    return cleaned


def without_thinking(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """``kwargs`` with thinking turned OFF explicitly, not merely removed.

    Dropping the flag is not enough: some models default it ON and then refuse
    the call ("parameter.enable_thinking must be set to false for non-stream
    call" — qwen3-8b). So every other thinking spelling goes away and
    ``enable_thinking`` is pinned to False, inside ``extra_body`` when that is
    where it came from.

    Returns the SAME object when the request carried no thinking parameter at
    all, so callers can tell "we never asked for thinking" (a 400 that is
    somebody else's problem) from "we just turned it off" (worth a retry).
    """
    extra = kwargs.get('extra_body')
    in_extra = isinstance(extra, dict) and any(k in extra
                                               for k in THINKING_PARAM_KEYS)
    in_top = any(k in kwargs for k in THINKING_PARAM_KEYS)
    if not in_extra and not in_top:
        return kwargs
    cleaned = dict(kwargs)
    for key in THINKING_PARAM_KEYS:
        cleaned.pop(key, None)
    if in_extra:
        new_extra = {
            k: v
            for k, v in extra.items() if k not in THINKING_PARAM_KEYS
        }
        new_extra['enable_thinking'] = False
        cleaned['extra_body'] = new_extra
    else:
        cleaned['enable_thinking'] = False
    return cleaned


def create_with_thinking_fallback(create, client, model: str, logger,
                                  **kwargs) -> Any:
    """Call ``create(**kwargs)``, retrying once with thinking off on a refusal.

    ``create`` must be the completions factory itself; it is called with the
    (possibly cleaned) kwargs. Streaming is covered because the OpenAI client
    performs the request — and raises — before it returns an iterator.
    """
    key = model_key(client, model)
    if key in MODELS_REFUSING_THINKING:
        kwargs = without_thinking(kwargs)
    elif key in MODELS_REQUIRING_THINKING and asks_to_disable(kwargs):
        # Only the "off" request is doomed here; a positive tier still goes out
        # normally, so this model is not blacklisted the way a refuser is.
        kwargs = strip_thinking(kwargs)
    try:
        return create(**kwargs)
    except Exception as e:
        # Order matters: "reasoning is mandatory" also names a thinking
        # parameter, so refusal would claim it and repair it backwards.
        if is_thinking_mandatory(e):
            retry_kwargs = strip_thinking(kwargs)
            if retry_kwargs is kwargs:
                raise
            MODELS_REQUIRING_THINKING.add(key)
            logger.warning(
                f'{model} does not allow thinking to be switched off; '
                f'retrying without any thinking parameter (it stays that way '
                f'for this model): {e}')
            return create(**retry_kwargs)
        if not is_thinking_refusal(e):
            raise
        retry_kwargs = without_thinking(kwargs)
        if retry_kwargs is kwargs:  # we asked for no thinking; not our 400
            raise
        MODELS_REFUSING_THINKING.add(key)
        logger.warning(
            f'{model} rejected the thinking parameters; retrying with '
            f'thinking off (it stays off for this model): {e}')
        return create(**retry_kwargs)
