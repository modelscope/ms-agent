# Copyright (c) ModelScope Contributors. All rights reserved.
"""Whether to attach pixels, and what to do when the endpoint says no.

Two halves.

**Resolution** — one state, default OFF: the per-model "image understanding"
switch. Nothing else. There is deliberately no memory of models observed to
refuse images, and no write-back of the switch.

An earlier version cached refusals so a conversation would stop paying for a
request it expected to fail. It cost a TTL, four invalidation hooks, a retry
endpoint and a UI affordance, and it introduced a failure mode of its own: a
cache is a second opinion about the user's own configuration, and when the two
disagreed the user had no way to see it. The switch is the user's statement
about their model; if it is wrong they find out from the reply and change it.
The price of that simplicity is one failed round-trip per turn on a model the
user has mis-declared — bounded, self-evident, and theirs to fix.

Deliberately NOT consulted: the provider's declared ``vision`` capability.
Vision is a property of the MODEL, not of the endpoint — ModelScope serves
``Qwen3-VL-8B-Instruct`` and the text-only ``Qwen3-235B-A22B`` through one
provider entry, so a provider-level flag says yes to both.

**Recovery** — a ladder, not a single move. The old code had exactly one
response to any failure that touched images: throw the pictures away and
remember the model as blind. That conflated three unrelated problems, and the
cheapest one to fix — an image a few hundred pixels too wide — was being
"solved" by permanently disabling a healthy model.

The ladder is driven by :func:`ms_agent.llm.image_errors.classify`:

===================  ===========================================
diagnosis            moves, in order
===================  ===========================================
TOO_LARGE            re-encode smaller (stated limit, then /2) …
SHAPE_REJECTED       keep only the newest image …
MODEL_NO_VISION      drop images
UNKNOWN              drop images
NOT_IMAGE_RELATED    (none — re-raise untouched)
===================  ===========================================

Rows that end in "…" fall through to dropping images if their own moves are
exhausted. The class still matters after the fact: it decides which sentence
the turn reports (a size complaint and a refusal are different problems with
different remedies), which is all it is used for now.

Streaming is covered in both shapes: clients that issue the request eagerly
raise out of ``create`` itself, and gateways that answer 200 and then fail
inside the stream raise on the first chunk (``llm/stream_retry.py``).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from ms_agent.llm import multimodal
from ms_agent.llm.image_errors import (ImageFailure, classify, edge_ladder,
                                       status_of)
from ms_agent.utils import get_logger

logger = get_logger()

#: Machine codes for why this turn's pixels are absent. They are codes, not
#: prose: the sentence a model or a user sees is rendered from one of these at
#: the point of use, so there is exactly one place to change the wording and no
#: way for two layers to describe the same state differently.
REASON_SWITCH_OFF = 'switch_off'
REASON_ENDPOINT_REJECTED = 'endpoint_rejected'


def _degrade_code(failure: ImageFailure) -> str:
    """Failure class -> the code the user-facing surfaces render.

    Only a capability refusal is described as the endpoint refusing images. A
    payload we could not make small enough, or a batch shape the endpoint would
    not take, are different sentences with different remedies — and, unlike a
    refusal, neither is something a "try again" button can undo.
    """
    return {
        ImageFailure.TOO_LARGE: multimodal.REASON_TOO_LARGE,
        ImageFailure.SHAPE_REJECTED: multimodal.REASON_SHAPE_REJECTED,
    }.get(failure, REASON_ENDPOINT_REJECTED)


def delivery_reason(base_url: Any = '', model: str = '') -> str:
    """Machine code for why pixels are absent at FORMAT time.

    Only one thing can be true this early: the switch is off. A refusal is
    discovered later, by the endpoint, and reported through ``on_degrade``.
    (Arguments kept for the transports' call shape.)
    """
    return REASON_SWITCH_OFF


def is_image_refusal(exc: Exception, sent_images: bool) -> bool:
    """Back-compat shim: is this failure attributable to the images at all?

    Kept because external callers and tests use it. The real decision now lives
    in :func:`ms_agent.llm.image_errors.classify`, which additionally says WHICH
    kind of image problem it was — the distinction that keeps a size complaint
    from being recorded as blindness.
    """
    return classify(
        exc, sent_images=sent_images).failure is not ImageFailure.NOT_IMAGE_RELATED


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


def _materialize(result: Any) -> Tuple[Any, bool]:
    """Resolve a candidate far enough to know it works.

    ``(result, produced_output)``. For a stream that means pulling the first
    chunk here, inside the error path, and re-attaching it — a gateway that
    answers 200 and then fails mid-stream must not be mistaken for a success.
    Raises whatever the attempt raises.
    """
    if not hasattr(result, '__next__'):
        return result, True
    try:
        first = next(result)
    except StopIteration:
        return iter(()), False  # accepted, but said nothing

    def _rejoined() -> Iterator[Any]:
        yield first
        yield from result

    return _rejoined(), True


def create_with_vision_fallback(create: Callable[..., Any],
                                *,
                                base_url: Any,
                                model: str,
                                messages: Any,
                                sent_images: bool,
                                max_edge: int = 0,
                                on_degrade: Optional[Callable[[str], None]] = None,
                                logger_: Any = None,
                                **kwargs) -> Any:
    """Call ``create(messages=..., **kwargs)``, recovering along the ladder.

    ``create`` must accept ``messages`` as a keyword so each rung can hand it a
    rewritten list. ``max_edge`` is the long edge the payload was encoded at, so
    a size complaint can be answered with a real reduction.

    ``on_degrade(reason)`` is called when recovery ends with images NOT reaching
    the model. Without it the record built at format time would still read
    "delivered" for a request the endpoint went on to refuse — and that record
    is what the user's badge and notice are drawn from, so it would confidently
    show the wrong thing in precisely the case it exists for.
    """
    from ms_agent.llm.stream_retry import retry_on_first_chunk

    log = logger_ or logger
    current_edge = max_edge or multimodal.VisionOptions.max_edge

    def _degraded(reason: str) -> None:
        if on_degrade is not None:
            try:
                on_degrade(reason)
            except Exception as exc:  # noqa: BLE001 — reporting must not fail a turn
                log.warning('[vision] delivery report failed: %s', exc)

    def _moves(diag) -> List[Tuple[str, Any]]:
        """Ordered recovery attempts for a diagnosis."""
        if diag.failure is ImageFailure.TOO_LARGE:
            return [('shrink', edge)
                    for edge in edge_ladder(diag.max_edge, current_edge)
                    ] + [('strip', None)]
        if diag.failure is ImageFailure.SHAPE_REJECTED:
            return [('keep_last', 1), ('strip', None)]
        return [('strip', None)]

    def _apply(move: str, arg: Any) -> Tuple[Any, bool]:
        if move == 'shrink':
            return multimodal.shrink_images_in_messages(messages, int(arg))
        if move == 'keep_last':
            return multimodal.drop_images_in_messages(messages, int(arg))
        return strip_images_from_messages(messages)

    def _repair(exc: BaseException) -> Any:
        diag = classify(exc, sent_images=sent_images)
        if diag.failure is ImageFailure.NOT_IMAGE_RELATED:
            raise exc

        log.warning(
            '%s failed on a request carrying images (%s: %s); recovering: %s',
            model, diag.failure.value, diag.detail,
            ' -> '.join(m for m, _ in _moves(diag)))

        for move, arg in _moves(diag):
            candidate, changed = _apply(move, arg)
            if not changed:
                continue
            try:
                result, produced = _materialize(
                    create(messages=candidate, **kwargs))
            except Exception as retry_exc:  # noqa: BLE001
                log.debug('[vision] recovery move %r did not help: %s', move,
                          retry_exc)
                continue
            if move == 'strip':
                _degraded(_degrade_code(diag.failure))
            elif move == 'keep_last':
                _degraded(multimodal.REASON_SHAPE_REJECTED)
            return result

        # Nothing on the ladder worked, so the images were not the cause (or not
        # the only one). The original error describes the real problem; a
        # recovery attempt's own failure would only obscure it.
        raise exc from None

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
    llm = getattr(config, 'llm', None) if config is not None else None
    if llm is not None:
        for name in ('supports_vision', 'vision_supported'):
            value = getattr(llm, name, None)
            if value is not None:
                return _as_bool(value)
    return False


def resolve_max_edge(spec: Any, configured: int = 0) -> int:
    """Long edge to encode at: the safe default unless a provider raises it.

    ``configured`` (an explicit ``llm.vision.max_edge``) always wins — a user
    who set a number meant it.
    """
    default = multimodal.VisionOptions.max_edge
    if configured and configured != default:
        return configured
    declared = int(getattr(spec, 'max_image_edge', 0) or 0)
    return max(default, declared) if declared else default


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


# Retained for callers that imported it directly. New code should use
# ``delivery_reason`` (machine codes) instead of prose.
def disabled_reason(base_url: Any = '', model: str = '') -> str:
    return delivery_reason(base_url, model)


__all__ = [
    'REASON_SWITCH_OFF',
    'REASON_ENDPOINT_REJECTED',
    'delivery_reason',
    'disabled_reason',
    'is_image_refusal',
    'strip_images_from_messages',
    'create_with_vision_fallback',
    'resolve_supports_vision',
    'resolve_max_edge',
    'status_of',
]
