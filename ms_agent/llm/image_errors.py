# Copyright (c) ModelScope Contributors. All rights reserved.
"""Why a request carrying images failed, and therefore what to do about it.

The classification is organised around **recovery actions, not vendors**. Two
providers that phrase the same complaint differently are the same failure if the
fix is the same; one provider that says two different things is two failures if
the fixes differ. No provider name appears in any decision below — vendor
differences belong in :mod:`ms_agent.llm.spec` (declared limits), never here.

**Why this module exists.** The predecessor asked a single question — "was this
a 400 on a request that carried images?" — and drew the heaviest possible
conclusion from it: *this model cannot see*. Measured consequence: a poster
whose long edge exceeded ModelScope's 2048 px ceiling produced

    400 {'message': 'input size exceed limit 2048x2048, current input:(1183,2560)'}

which is a complaint about **one image**, and a perfectly healthy vision model
was recorded as blind for the rest of the process. The rule below that prevents
a repeat is not a better pattern list; it is that **only one class of failure is
allowed to write a lasting conclusion**, and size complaints are not in it.

**Ordering is part of the contract** (structural signals first, prose last):

0. we did not send images        → somebody else's problem
1. status is not 400/413/422     → somebody else's problem
2. semantic vetoes               → about safety/length/this file, not capability
3. size complaints               → shrink and retry, never remember
4. shape complaints              → change the batch and retry, never remember
5. capability statements         → drop images, and only here may we remember
6. anything else                 → drop images once, do not remember

**A stale pattern table is safe by construction.** Every unmatched message falls
through to :data:`ImageFailure.UNKNOWN`, whose recovery is one image-less retry
with no memory written. So a provider re-wording its errors costs us one extra
round-trip, never a wrong persistent belief. That property is what makes prose
matching acceptable at all, and it is asserted by the tests.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Optional, Pattern, Tuple

#: Smallest / largest long-edge we will believe from an error message. A parsed
#: value outside this range is treated as noise (some providers echo the *input*
#: dimensions in the same sentence as the limit).
_EDGE_MIN = 256
_EDGE_MAX = 8192


class ImageFailure(str, Enum):
    """What kind of failure this was, named after the fix."""

    #: Not attributable to the images. Re-raise untouched.
    NOT_IMAGE_RELATED = 'not_image_related'
    #: One or more images are too big. Re-encode smaller and retry.
    TOO_LARGE = 'too_large'
    #: The *batch* is wrong (too many images, animation, aspect ratio).
    SHAPE_REJECTED = 'shape_rejected'
    #: The model itself states it does not accept images. The only class that
    #: may be remembered.
    MODEL_NO_VISION = 'model_no_vision'
    #: Attributable to the images but unrecognised. One image-less retry.
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class ImageDiagnosis:
    """The verdict plus everything the recovery ladder needs."""

    failure: ImageFailure
    #: Long-edge ceiling parsed out of the message, when the provider stated one.
    max_edge: Optional[int] = None
    #: Whether a successful image-less retry may write the capability memo.
    #: True for exactly one failure class — see the module docstring.
    remember: bool = False
    #: Short machine-ish reason, surfaced to the UI (never to the model).
    detail: str = ''


def _compile(pairs: List[Tuple[str, str]]) -> List[Tuple[Pattern[str], str]]:
    return [(re.compile(p, re.I), why) for p, why in pairs]


#: Complaints that are *never* about media capability. Checked before anything
#: else so that stripping images can never look like the cure for them —
#: dropping media may incidentally make an over-long request fit, but that is a
#: coincidence, not a learned capability.
_VETO = _compile([
    (r'\bcontent[_\s-]?filter\b', 'content filter'),
    (r'\bmoderation\b', 'moderation'),
    (r'\bsafety\b.*\b(policy|violat)', 'safety policy'),
    (r'\bcontext[_\s-]?length\b', 'context length'),
    (r'\bmaximum context\b', 'context length'),
    (r'\btoken[s]?\s+limit\b', 'token limit'),
    (r'\breduce the length of the messages\b', 'context length'),
    # The asset itself is broken. Shrinking or dropping every image would hide
    # which file is at fault, so this is not an image-capability question.
    (r'\bcorrupt(ed)?\b', 'corrupt asset'),
    (r'\b(could not|failed to|cannot)\s+decode\b', 'undecodable asset'),
    (r'\binvalid image\b', 'invalid asset'),
    (r'\bunsupported image (format|type)\b', 'unsupported format'),
])

#: The provider is complaining about SIZE. Recovery is to re-encode smaller;
#: this says nothing about whether the model can see.
#: Provenance: `input size exceed limit 2048x2048, current input:(1183,2560)`
#: — ModelScope api-inference, Qwen3-VL-8B-Instruct, 2026-08-21.
_SIZE = _compile([
    (r'\bsize exceed\b', 'image too large'),
    (r'\bexceed(s)?\s+limit\b', 'image too large'),
    (r'\bimage\b[^.]{0,40}\bexceeds\b', 'image too large'),
    (r'\bdimensions?\b[^.]{0,40}\bexceed', 'image too large'),
    (r'\bmax(imum)?\s+allowed\s+size\b', 'image too large'),
    (r'\b(image|file)\b[^.]{0,30}\b(too large|larger than)\b', 'image too large'),
    (r'\b(width|height)\b[^.]{0,30}\b(exceed|too large|larger than)\b',
     'image too large'),
    (r'\bmega\s?pixel', 'image too large'),
])

#: The provider is complaining about the SHAPE of this batch — how many images,
#: whether they animate, their proportions. Recovery is to change the batch.
_SHAPE = _compile([
    (r'\bmultiple images?\b', 'too many images'),
    (r'\bmore than one image\b', 'too many images'),
    (r'\bimage count\b', 'too many images'),
    (r'\bat most\s+\d+\s+image', 'too many images'),
    (r'\bper image\b', 'per-image limit'),
    (r'\banimated\b', 'animation unsupported'),
    (r'\bframe rate\b', 'animation unsupported'),
    (r'\baspect ratio\b', 'aspect ratio'),
])

#: The model states it does not take images at all. **The only class that may
#: write a lasting conclusion**, so the wording here is deliberately narrow.
#: Provenance:
#:   - `The provided messages input is invalid. The error info is
#:     [Unexpected item type in content.]` — DashScope compatible-mode, a
#:     text-only qwen model, 2026-08-18. Names neither image nor vision, which
#:     is exactly why a generic keyword list is not enough on its own.
#:   - `messages.content.type 参数非法，取值范围 ['text']` — Zhipu open.bigmodel.cn,
#:     glm-5.2, 2026-08-21.
_CAPABILITY = _compile([
    (r'\btext[- ]only\b', 'model is text-only'),
    (r"\b(does not|doesn't|do not|cannot|can't|not)\s+support\b[^.]{0,40}"
     r'\b(image|multimodal|vision|media)\b', 'model does not accept images'),
    (r'\bmultimodal\b[^.]{0,40}\bnot (enabled|supported|available)\b',
     'multimodal not enabled'),
    (r'\bvision\b[^.]{0,30}\bnot (enabled|supported|available)\b',
     'vision not enabled'),
    (r'\bunexpected item type in content\b', 'endpoint rejects image blocks'),
    (r"content\.type\s*参数非法", 'endpoint rejects image blocks'),
    (r'\bonly\s+(accepts?|supports?)\b[^.]{0,20}\btext\b',
     'endpoint accepts text only'),
])

#: Provider ceilings, most explicit first. Each must capture the LIMIT, not the
#: offending input — hence the anchoring words.
_EDGE_PATTERNS = [
    re.compile(r'exceed(?:s)?\s+limit\s+(\d{3,5})\s*[x×]\s*(\d{3,5})', re.I),
    re.compile(r'max(?:imum)?\s+allowed\s+size:?\s*(\d{3,5})', re.I),
    re.compile(r'max(?:imum)?\s+(?:width|height|dimension)\s*(?:is|:|=)?\s*'
               r'(\d{3,5})', re.I),
    re.compile(r'must be\s*(?:at most|<=|≤)\s*(\d{3,5})\s*(?:px|pixels)', re.I),
]


def status_of(exc: BaseException) -> Optional[int]:
    """HTTP status carried by ``exc``, or None.

    Only structured attributes are consulted. The predecessor also accepted
    ``'400' in str(exc)``, which fired on any message that happened to contain
    those three digits anywhere — including request ids and pixel counts.
    """
    status = getattr(exc, 'status_code', None)
    if status is None:
        response = getattr(exc, 'response', None)
        status = getattr(response, 'status_code', None)
    if status is None:
        status = getattr(exc, 'http_status', None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _text_of(exc: BaseException) -> str:
    parts = [str(exc)]
    body = getattr(exc, 'body', None)
    if body is not None and not isinstance(body, (bytes, bytearray)):
        parts.append(str(body))
    return '\n'.join(parts)


def parse_max_edge(text: str) -> Optional[int]:
    """The long-edge ceiling the provider stated, or None.

    ``exceed limit 2048x2048`` yields 2048. The smaller of a WxH pair is taken:
    a provider that allows different width and height is satisfied by the
    stricter one, and squaring the difference away costs at most a little
    resolution.
    """
    for pattern in _EDGE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        values = [int(g) for g in match.groups() if g]
        if not values:
            continue
        edge = min(values)
        if _EDGE_MIN <= edge <= _EDGE_MAX:
            return edge
    return None


def _first_match(text: str,
                 table: List[Tuple[Pattern[str], str]]) -> Optional[str]:
    for pattern, why in table:
        if pattern.search(text):
            return why
    return None


def classify(exc: BaseException, *, sent_images: bool) -> ImageDiagnosis:
    """Diagnose a failed request. See the module docstring for the ordering."""
    if not sent_images:
        return ImageDiagnosis(ImageFailure.NOT_IMAGE_RELATED,
                              detail='no images in this request')

    status = status_of(exc)
    if status is not None and status not in (400, 413, 422):
        return ImageDiagnosis(ImageFailure.NOT_IMAGE_RELATED,
                              detail=f'HTTP {status}')

    text = _text_of(exc)

    veto = _first_match(text, _VETO)
    if veto:
        return ImageDiagnosis(ImageFailure.NOT_IMAGE_RELATED, detail=veto)

    if status == 413:
        # The body was too big, which says nothing about whether the model
        # accepts images. Shrinking is worth a try; remembering is not.
        return ImageDiagnosis(
            ImageFailure.TOO_LARGE,
            max_edge=parse_max_edge(text),
            detail='request body too large')

    size = _first_match(text, _SIZE)
    if size:
        return ImageDiagnosis(
            ImageFailure.TOO_LARGE, max_edge=parse_max_edge(text), detail=size)

    shape = _first_match(text, _SHAPE)
    if shape:
        return ImageDiagnosis(ImageFailure.SHAPE_REJECTED, detail=shape)

    capability = _first_match(text, _CAPABILITY)
    if capability:
        return ImageDiagnosis(
            ImageFailure.MODEL_NO_VISION, remember=True, detail=capability)

    return ImageDiagnosis(ImageFailure.UNKNOWN, detail='unrecognised')


def edge_ladder(stated: Optional[int], current: int) -> List[int]:
    """Long edges to try, in order, after a size complaint.

    A stated ceiling is tried first and is usually the end of it. Otherwise we
    halve, twice: a provider that rejected the current size will not be
    convinced by 10% less, and more than two extra round-trips costs more than
    the image is worth.
    """
    out: List[int] = []
    if stated and stated < current:
        out.append(stated)
    edge = current
    for _ in range(2):
        edge = max(_EDGE_MIN, edge // 2)
        if edge < current and edge not in out:
            out.append(edge)
        if edge <= _EDGE_MIN:
            break
    return out
