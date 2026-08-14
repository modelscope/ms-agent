# Copyright (c) ModelScope Contributors. All rights reserved.
"""Fallback for models that refuse the "thinking" parameters.

Whether a model supports thinking is a per-MODEL fact with no naming rule to
derive it from, and a provider that does not support it may REJECT the whole
request rather than ignore the flag (DashScope answers 400
``InternalError.Algo.InvalidParameter: The thinking_budget parameter must be a
positive integer and not greater than 0``). Probing one provider's 122 chat
models turned up refusals from ``qwen-vl-*``, ``qwen3.5-ocr``, ``qwen3-8b``,
``qwen3-livetranslate-flash``, ``qwen3.5-omni-flash`` and ``deepseek-v3.1`` —
vision, OCR, omni, open-weight and non-Qwen alike, i.e. not predictable from the
name, and a moving target as vendors ship models.

So the client does not try to predict it: it asks for thinking, and if the model
refuses, turns it off and retries once, remembering the model so a session pays
the extra round-trip at most once. Shared by every OpenAI-compatible caller
(``llm/openai_llm.py`` and the provider router's ``transport/openai_compat.py``)
— a blocklist maintained by hand was wrong twice before this existed.
"""
from __future__ import annotations

from typing import Any, Dict

THINKING_PARAM_KEYS = ('enable_thinking', 'thinking_budget', 'thinking')

#: ``(base_url, model)`` pairs observed to refuse the thinking parameters.
MODELS_REFUSING_THINKING: set = set()


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
    call" — qwen3-8b). So the budget keys go away and ``enable_thinking`` is
    pinned to False, inside ``extra_body`` when that is where it came from.

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
