# Copyright (c) ModelScope Contributors. All rights reserved.
"""Which models can be shown an image, and what to do when we guess wrong.

Two halves:

**Resolution** — whether to attach pixels at all, decided per model, strongest
signal first:

1. an explicit per-model setting (the "image understanding" switch in the model
   form) — the user's own statement, always wins;
2. the provider's declared ``vision`` capability — a coarse default for models
   nobody has classified yet;
3. a model observed to REFUSE images earlier in this process — vetoes both of
   the above, because a refusal is ground truth.

**Self-healing** — a provider that cannot see images rejects the whole request
with a hard 400, which would otherwise make such a model unusable the moment a
user attaches a file. So the request is retried once with the images replaced by
text, and the model is remembered so a session pays that round-trip at most once.

The refusal detector deliberately does **no keyword matching**. Measured against
DashScope (2026-08), a text-only model given an ``image_url`` block answers::

    <400> InternalError.Algo.InvalidParameter: The provided messages input is
    invalid. The error info is [Unexpected item type in content.]

— which names neither "image" nor "multimodal" nor "vision". Any keyword list
built from a vendor's current phrasing is a guess that goes stale. What we *do*
know for certain is whether the request we just sent carried image blocks; that
fact plus a 400 is the attribution. Mirrors ``llm/thinking.py``, which exists
because a hand-maintained model blocklist was wrong twice before it.
"""
from __future__ import annotations

from typing import Any, List, Optional, Set, Tuple

from ms_agent.llm import multimodal
from ms_agent.utils import get_logger

logger = get_logger()

#: ``(base_url, model)`` pairs observed to reject image content.
MODELS_REFUSING_IMAGES: Set[Tuple[str, str]] = set()

#: Callables notified the first time a model is learned to refuse images.
#: A host (the WebUI) registers one so the discovery can be written back to
#: wherever the user configured the model — otherwise the knowledge dies with
#: the process and every restart pays the same rejected request again, while the
#: "image understanding" switch keeps claiming the model supports it.
_OBSERVERS: List[Any] = []


def register_refusal_observer(fn) -> None:
    """Register ``fn(base_url, model)``, called once per newly-learned refusal.

    Idempotent per callable, so repeated setup (a WebUI reload) cannot stack
    duplicate write-backs. Observer exceptions are swallowed: learning that a
    model refuses images must never be able to fail the turn that discovered it.
    """
    if fn not in _OBSERVERS:
        _OBSERVERS.append(fn)


def model_key(base_url: Any, model: str) -> Tuple[str, str]:
    return (str(base_url or ''), str(model or ''))


def note_refusal(base_url: Any, model: str) -> None:
    key = model_key(base_url, model)
    first_time = key not in MODELS_REFUSING_IMAGES
    MODELS_REFUSING_IMAGES.add(key)
    if not first_time:
        return
    for observer in list(_OBSERVERS):
        try:
            observer(key[0], key[1])
        except Exception as exc:  # never fail the turn over bookkeeping
            logger.warning('[vision] refusal observer failed: %s', exc)


def known_refuser(base_url: Any, model: str) -> bool:
    return model_key(base_url, model) in MODELS_REFUSING_IMAGES


def _status_of(exc: Exception) -> Optional[int]:
    status = getattr(exc, 'status_code', None)
    if status is None:
        response = getattr(exc, 'response', None)
        status = getattr(response, 'status_code', None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def is_image_refusal(exc: Exception, sent_images: bool) -> bool:
    """True when a 400 is attributable to the images in THIS request.

    ``sent_images`` is the whole detector: we know what we put on the wire, and
    guessing the vendor's wording does not work (see the module docstring).

    This is deliberately a WIDE net — it says "worth one retry", not "definitely
    the images". Measured across seven providers, a 400 on an image-carrying
    request also covers model-not-found ("Model id ... has no provider
    supported" on ModelScope), auth failures and content filters. The
    discrimination therefore happens in ``create_with_vision_fallback``, which
    only blacklists the model when the image-less retry actually SUCCEEDS; a 400
    that persists without images is re-raised untouched and teaches us nothing.

    So the cost of a false positive is exactly one extra round-trip, and it can
    never mask the real error or wrongly disable images on a capable model.
    """
    if not sent_images:
        return False  # a 400 with no images in it is somebody else's problem
    status = _status_of(exc)
    if status is not None:
        return status == 400
    # Some SDK wrappers lose the status; fall back to the textual marker.
    return '400' in str(exc)


def strip_images_from_messages(messages: Any) -> Tuple[Any, bool]:
    """``(messages, changed)`` with every image block folded back into text.

    Operates on the already-formatted provider payload, so it works for both the
    OpenAI ``image_url`` shape and the Anthropic ``image``/``source`` shape.
    """
    if not isinstance(messages, list):
        return messages, False
    changed = False
    out = []
    for message in messages:
        if not isinstance(message, dict):
            out.append(message)
            continue
        content = message.get('content')
        if multimodal.has_image_blocks(content):
            message = {
                **message, 'content': multimodal.strip_image_blocks(content)
            }
            changed = True
        out.append(message)
    return out, changed


def create_with_vision_fallback(create,
                                *,
                                base_url: Any,
                                model: str,
                                messages: Any,
                                sent_images: bool,
                                logger_=None,
                                **kwargs) -> Any:
    """Call ``create(messages=..., **kwargs)``, retrying once without images.

    ``create`` must accept ``messages`` as a keyword so the retry can hand it a
    rewritten list. Streaming is covered: the client performs the request — and
    raises — before it returns an iterator.
    """
    log = logger_ or logger
    if sent_images and known_refuser(base_url, model):
        messages, _ = strip_images_from_messages(messages)
        sent_images = False
    try:
        return create(messages=messages, **kwargs)
    except Exception as exc:
        if not is_image_refusal(exc, sent_images):
            raise
        retry_messages, changed = strip_images_from_messages(messages)
        if not changed:
            raise
        log.warning(
            '%s returned 400 on a request carrying images; retrying once with '
            'the images replaced by text: %s', model, exc)
        try:
            result = create(messages=retry_messages, **kwargs)
        except Exception:
            # Removing the images did NOT help, so they were not the cause —
            # this was a model-not-found / auth / content-filter 400 that merely
            # happened to ride on a turn with an attachment. Re-raise the
            # ORIGINAL error (it describes the real problem) and, crucially, do
            # not blacklist the model: marking a vision-capable model as
            # image-refusing here would silently stop sending it images for the
            # rest of the process. Measured on ModelScope, whose "Model id ...
            # has no provider supported" is exactly this shape.
            raise exc from None
        # The image-less retry succeeded, so the images were the problem. THIS
        # is the only sound moment to remember it — the status code alone cannot
        # tell an image refusal from any other 400.
        note_refusal(base_url, model)
        log.warning(
            'images stay off for %s for the rest of this process (the '
            'image-less retry succeeded)', model)
        return result


def resolve_supports_vision(config: Any,
                            spec: Any = None,
                            model: str = '',
                            base_url: Any = '') -> bool:
    """Whether to attach pixels for this model. See the module docstring.

    ``config.llm.supports_vision`` is the explicit per-model switch. It is
    read as a TRI-STATE: absent/None means "nobody has said", which falls
    through to the provider capability and then to runtime learning. That is
    better than a hard default in either direction — a hard ``False`` would make
    a capable model silently ignore attachments until someone ticks a box, and a
    hard ``True`` would make every text-only model burn a 400 on first use.
    """
    if model and known_refuser(base_url, model):
        return False  # observed truth beats every declaration

    llm = getattr(config, 'llm', None) if config is not None else None
    explicit = None
    if llm is not None:
        for name in ('supports_vision', 'vision_supported'):
            value = getattr(llm, name, None)
            if value is not None:
                explicit = value
                break
    if explicit is not None:
        return _as_bool(explicit)

    if spec is not None:
        caps = getattr(spec, 'capabilities', None)
        if caps is not None:
            try:
                from ms_agent.llm.types import ProviderCapability
                return bool(caps.supports(ProviderCapability.VISION))
            except Exception:
                pass
    return False


def _as_bool(value: Any) -> bool:
    """Tolerate a YAML/JSON boolean written as a string.

    ``supports_vision: "false"`` is a common enough mistake that treating it as
    truthy (which bare ``bool()`` does) would silently enable images on a model
    the user just tried to turn them off for.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on', 'y')
    return bool(value)
