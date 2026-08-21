# Copyright (c) ModelScope Contributors. All rights reserved.
"""Which models can be shown an image, and what to do when we guess wrong.

Two halves:

**Resolution** — whether to attach pixels at all. Two states only, and the
default is OFF:

1. an explicit per-model setting (the "image understanding" switch in the model
   form) — the user's own statement, and the only thing that turns images ON;
2. a model observed to REFUSE images earlier in this process vetoes it, because
   a refusal is ground truth.

Deliberately NOT consulted: the provider's declared ``vision`` capability.
Vision is a property of the MODEL, not of the endpoint — ModelScope serves
``Qwen3-VL-8B-Instruct`` and the text-only ``Qwen3-235B-A22B`` through one
provider entry, so a provider-level flag says yes to both. It used to be the
middle tier here, and because nine of ten registry entries declare ``vision``
it made "nobody has said" mean "send images", i.e. the switch's OFF position
described a state the runtime never actually used. ``ProviderCapability.VISION``
still exists and is still correct about what the *protocol* accepts; it is just
not evidence about a particular model's eyesight.

Whether a model can really see is therefore the user's call. There is no
probing: a model that accepts image blocks with HTTP 200 and cannot read them
(measured: zhipu glm-5.x, MiniMax-M2.7, and ModelScope's Qwen3-235B-A22B, which
answered with an invented string) is indistinguishable at runtime from one that
can.

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

#: Callables notified the first time a model is learned to refuse images, so a
#: host (the WebUI) can TELL THE USER. Deliberately not a write-back hook: the
#: switch is the user's statement about their own model, and silently rewriting
#: it would both contradict them and hide the reason. The memo below keeps the
#: session from paying the failed round-trip twice; making it permanent is the
#: user's decision to make in the model form.
_OBSERVERS: List[Any] = []


def register_refusal_observer(fn) -> None:
    """Register ``fn(base_url, model)``, called once per newly-learned refusal.

    Idempotent per callable, so repeated setup (a WebUI reload) cannot stack
    duplicate notifications. Observer exceptions are swallowed: learning that a
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


def disabled_reason(base_url: Any = '', model: str = '') -> str:
    """Why this turn's images are text placeholders, for the model to relay.

    A model whose switch is off should be told to turn it on; a model whose
    switch is ON but whose endpoint rejected the images must NOT be, or it
    sends the user back to a box they already ticked.
    """
    if model and known_refuser(base_url, model):
        return multimodal.REASON_REJECTED
    return multimodal.REASON_DISABLED


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
    rewritten list.

    Streaming is covered in BOTH shapes: clients that issue the request eagerly
    raise out of ``create`` itself, and gateways that answer 200 before
    rejecting the image blocks raise on the first chunk (see
    ``llm/stream_retry.py``).
    """
    from ms_agent.llm.stream_retry import retry_on_first_chunk

    log = logger_ or logger
    if sent_images and known_refuser(base_url, model):
        messages, _ = strip_images_from_messages(messages)
        sent_images = False

    def _remember() -> None:
        note_refusal(base_url, model)
        log.warning(
            'images stay off for %s for the rest of this process (the '
            'image-less retry succeeded)', model)

    def _confirm(result: Any, original: BaseException) -> Any:
        """Blacklist only once the image-less attempt actually produces output.

        For a non-streaming call "returned" already means "succeeded". For a
        stream it does not: the replacement can still fail on its own first
        chunk, and treating that as proof would blacklist a model whose real
        problem was something else entirely.
        """
        if not hasattr(result, '__next__'):
            _remember()
            return result

        def _guarded():
            try:
                first = next(result)
            except StopIteration:
                _remember()  # empty, but the endpoint accepted it
                return
            except Exception:
                raise original from None  # the images were not the cause
            _remember()
            yield first
            yield from result

        return _guarded()

    def _repair(exc: BaseException) -> Any:
        if not is_image_refusal(exc, sent_images):
            raise exc
        retry_messages, changed = strip_images_from_messages(messages)
        if not changed:
            raise exc
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
        return _confirm(result, exc)

    try:
        result = create(messages=messages, **kwargs)
    except Exception as exc:
        return _repair(exc)
    return retry_on_first_chunk(result, _repair)


def resolve_supports_vision(config: Any,
                            spec: Any = None,
                            model: str = '',
                            base_url: Any = '') -> bool:
    """Whether to attach pixels for this model. See the module docstring.

    ``config.llm.supports_vision`` is the explicit per-model switch and the only
    thing that turns images on; unset means OFF. ``spec`` is accepted and ignored
    (kept so existing callers need no edit): a provider's declared ``vision``
    capability describes the protocol, not the model behind it.
    """
    if model and known_refuser(base_url, model):
        return False  # observed truth beats the switch

    llm = getattr(config, 'llm', None) if config is not None else None
    if llm is not None:
        for name in ('supports_vision', 'vision_supported'):
            value = getattr(llm, name, None)
            if value is not None:
                return _as_bool(value)
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
