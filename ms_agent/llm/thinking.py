# Copyright (c) ModelScope Contributors. All rights reserved.
"""One semantic knob for "how hard should the model think", plus the fallback
for models that refuse to be asked at all.

Every vendor spells thinking differently and none of them spells it the same way
for long. Probed against the official docs on 2026-08-17:

===============  ==================================  ==================  =========
endpoint         modern field                        tiers               default
===============  ==================================  ==================  =========
OpenAI           ``reasoning_effort``                none…xhigh          ``none``
DeepSeek         ``reasoning_effort`` /              low/high/max        ON, high
                 ``thinking: {type}``                (medium→high)
Zhipu GLM 5.2+   ``reasoning_effort``                low/high/max        ``max``
Moonshot Kimi 3  ``reasoning_effort``                low/high/max        ``max``
MiniMax M3       ``thinking: {type}``                adaptive/disabled   ON via
                                                                         OpenAI,
                                                                         OFF via
                                                                         Anthropic
DashScope        ``enable_thinking`` AND             none…xhigh          per model
                 ``reasoning_effort``; plus          (no ``max``)
                 ``thinking_budget``, which the
                 effort field CANNOT travel with
ModelScope       ``enable_thinking`` (gateway) /     on/off              per model
                 ``chat_template_kwargs``
OpenRouter       ``reasoning: {effort|max_tokens}``  low/medium/high     inferred
Anthropic        ``output_config.effort`` +          low…max             high
                 ``thinking: {type: adaptive}``
===============  ==================================  ==================  =========

Three things follow from that table, and they are the whole design:

1. ``reasoning_effort`` is the de-facto standard. It is the name callers use
   here, so anyone who knows one vendor already knows this one — and it survives
   the OpenAI SDK's signature filter, unlike an invented name.

2. The on/off switch is being retired. GLM-5.3 and Kimi K3 cannot stop thinking
   at all (GLM-5.3 *fails* the request if you send the old
   ``thinking: {type: disabled}``), and Anthropic deprecated
   ``enabled + budget_tokens`` in favour of an effort level. So "off" is modelled
   as the weakest rung of the ladder, the way OpenAI models it with ``none``.

3. Defaults are per-MODEL and they move. On DashScope alone, qwen3.5 and later
   default thinking ON while qwen-plus/turbo/flash and qwen3-max default it OFF;
   MiniMax M3 defaults it ON through the OpenAI-compatible API and OFF through
   the Anthropic-compatible one — same model. Any table of defaults we wrote
   would be wrong within a release. So we do not write one: ``auto`` sends
   NOTHING and inherits whatever the vendor tuned, and the lowering table below
   is consulted ONLY when a caller asked for a specific tier. A bug in it can
   then only affect someone who explicitly configured thinking, who will see it
   immediately — rather than silently changing every request.
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
    ('api.moonshot.cn', 'moonshot'),
    ('platform.kimi.ai', 'moonshot'),
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
_FAMILY_TIERS = {
    # DashScope takes the ladder but REJECTS the top rung: qwen3.7-plus answers
    # 400 for `max` while accepting `xhigh`, so `max` clamps down to it. The
    # ladder is real there — qwen3.8-max reasoning is strictly monotonic in it
    # (none 0, minimal 54, low 78, medium 152, high 222, xhigh 393 characters).
    'dashscope': ('off', 'minimal', 'low', 'medium', 'high', 'xhigh'),
    # No effort field at all: the switch is a boolean, so every "how hard"
    # collapses onto "on".
    'modelscope': ('off', 'high'),
    'minimax': ('off', 'high'),
    'anthropic': ('off', 'high'),
    # Everyone else takes the whole vocabulary. Endpoints that do not validate
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
    """Nearest tier the endpoint accepts, preferring the next STRONGER one.

    Asking for more than a model offers should cap at its ceiling rather than
    fail; asking for less than it offers (``off`` on Kimi K3, which always
    thinks) should land on its floor rather than be silently dropped.
    """
    if tier in supported:
        return tier
    want = EFFORT_RANKS[tier]
    ranked = sorted(supported, key=lambda t: EFFORT_RANKS[t])
    for candidate in ranked:
        if EFFORT_RANKS[candidate] >= want:
            return candidate
    return ranked[-1]


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
        # BOTH knobs, because they do different jobs and only one of them is
        # universal. `enable_thinking` is what actually turns thinking on for
        # the models that default it off (qwen-plus: 0 characters of reasoning
        # with `reasoning_effort: high` alone, 543 with the flag), while
        # `reasoning_effort` is what sets the depth on the models that honour
        # it (qwen3.8-max, and DeepSeek/GLM/Kimi served on this host). Models
        # that only understand one of the two ignore the other.
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
        return {
            'family': family,
            'requested': 'auto',
            'effective': 'auto',
            'params': _drop_conflicts(auto_params(family), existing),
            'extra_hint': FAMILY_EXTRA_HINTS.get(family, ''),
        }
    effective = clamp_effort(requested, _FAMILY_TIERS.get(family,
                                                          _FAMILY_TIERS['unknown']))
    return {
        'family': family,
        'requested': requested,
        'effective': effective,
        'params': _drop_conflicts(lower_effort(effective, family), existing),
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
