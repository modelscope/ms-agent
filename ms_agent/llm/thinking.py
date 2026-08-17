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
DashScope        ``enable_thinking``,                on/off              per model
                 ``thinking_budget`` (1..32768)
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
EFFORT_TIERS = ('off', 'low', 'medium', 'high', 'max')

#: Ranks for clamping a requested tier onto what an endpoint accepts. Gaps leave
#: room for future rungs (a ``minimal: 15``) without renumbering.
EFFORT_RANKS = {'off': 0, 'low': 20, 'medium': 30, 'high': 40, 'max': 70}

_EFFORT_ALIASES = {
    'none': 'off',
    'disabled': 'off',
    'disable': 'off',
    'false': 'off',
    'no': 'off',
    'med': 'medium',
    'xhigh': 'max',
    'extrahigh': 'max',
    'maximum': 'max',
    'true': 'high',
    'on': 'high',
    'enabled': 'high',
}

#: ``(base_url, model)`` pairs observed to refuse the thinking parameters.
MODELS_REFUSING_THINKING: set = set()


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
    # On/off only: the flag is a boolean, so every "how hard" collapses to "on".
    'dashscope': ('off', 'high'),
    'modelscope': ('off', 'high'),
    'minimax': ('off', 'high'),
    'anthropic': ('off', 'high'),
    # Real ladders. deepseek/zhipu can be switched off, just not through the
    # effort field (their tiers are low/high/max) — see lower_effort.
    'deepseek': ('off', 'low', 'high', 'max'),
    'zhipu': ('off', 'low', 'high', 'max'),
    # Kimi K3 always thinks, so "off" is deliberately absent and clamps up to
    # the floor tier rather than sending a switch the model does not have.
    'moonshot': ('low', 'high', 'max'),
    'openrouter': ('off', 'low', 'medium', 'high'),
    'openai': ('off', 'low', 'medium', 'high', 'max'),
    'unknown': ('off', 'low', 'medium', 'high', 'max'),
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
    if family in ('dashscope', 'modelscope', 'anthropic'):
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
            # Their `reasoning_effort` has no "none" rung; the shape that turns
            # thinking off is the `thinking` object.
            _merge_extra_body(params, {'thinking': {'type': 'disabled'}})
        else:
            params[EFFORT_KEY] = tier
    elif family == 'moonshot':
        params[EFFORT_KEY] = tier  # 'off' was clamped up to 'low' already
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


def plan(effort: Any, *, base_url: str = '', protocol: str = '') -> dict:
    """Resolve a canonical effort into a wire plan, without sending anything.

    Returns ``{'family', 'requested', 'effective', 'params', 'extra_hint'}``.
    ``effective`` is the clamped tier, or ``'auto'``. Shared by the transports
    and by the WebUI, so what the settings page shows is what actually ships.
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
            'params': auto_params(family),
            'extra_hint': FAMILY_EXTRA_HINTS.get(family, ''),
        }
    effective = clamp_effort(requested, _FAMILY_TIERS.get(family,
                                                          _FAMILY_TIERS['unknown']))
    return {
        'family': family,
        'requested': requested,
        'effective': effective,
        'params': lower_effort(effective, family),
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
    resolved = plan(effort, base_url=base_url, protocol=protocol)
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


def is_thinking_refusal(exc: Exception) -> bool:
    """A 400 that names the thinking parameters — not any other bad request."""
    status = getattr(exc, 'status_code', None)
    if status is not None and status != 400:
        return False
    text = str(exc).lower()
    if status != 400 and '400' not in text:
        return False
    return any(k in text for k in THINKING_PARAM_KEYS)


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
    try:
        return create(**kwargs)
    except Exception as e:
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
