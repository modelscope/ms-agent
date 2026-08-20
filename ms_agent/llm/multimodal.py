# Copyright (c) ModelScope Contributors. All rights reserved.
"""Image attachments: internal references in, provider-native blocks out.

A user turn carries images on ``Message.attachments`` as REFERENCES::

    {'type': 'image', 'path': 'user_files/a.png',
     'media_type': 'image/png', 'label': 'Image 1: a.png'}

Nothing upstream of the wire ever holds the bytes. This module is the single
place that resolves a reference to actual pixels, and it does so at the last
possible moment — inside a transport's ``_format_input_message``. That timing is
the whole point:

* **The right encoding is provider- and model-specific.** Anthropic auto-downsamples
  above 1568 px (2576 px on its high-resolution tier) and takes GIF; DashScope's
  vision docs list only JPEG/PNG/WebP and cap the base64 string at 10 MB. Baking
  bytes into the SessionLog would freeze one provider's answer forever.
* **A session can change models mid-conversation.** With references, switching to a
  text-only model degrades the same log to text placeholders, and switching back
  makes the images visible again. With inlined base64 neither direction works.
* **Re-encoding is cheap and cacheable**, while re-writing a log is not.

Ordering follows Anthropic's guidance (image-then-text reads best) and each image
is introduced by its own ``Image N: <filename>`` text block, which is what lets a
follow-up question say "the second image" and land on the right one.
"""
from __future__ import annotations

import base64
import io
import mimetypes
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ms_agent.utils import get_logger

logger = get_logger()

#: Media types every supported provider accepts. GIF is deliberately absent:
#: Anthropic and OpenAI take it, DashScope's vision documentation does not list
#: it, so it is transcoded (first frame) to PNG for a single cross-provider
#: answer — which also resolves "animations are unsupported, first frame is used".
SUPPORTED_MEDIA_TYPES = frozenset({'image/png', 'image/jpeg', 'image/webp'})

#: Transcoded to PNG rather than rejected.
TRANSCODE_MEDIA_TYPES = frozenset(
    {'image/gif', 'image/bmp', 'image/tiff', 'image/heic', 'image/heif'})

#: Flat per-image token cost for the LOCAL context estimator. Not a billing
#: figure — the providers charge by patch count off the pixel dimensions
#: (Anthropic ``⌈w/28⌉ × ⌈h/28⌉``; DashScope reports the real number back as
#: ``prompt_tokens_details.image_tokens``). This exists so the estimator stops
#: measuring base64 character count, which over-counts by ~26x even for a 22 KB
#: image (measured: 282 real vs 7,293 estimated).
IMAGE_TOKEN_ESTIMATE = 800


@dataclass(frozen=True)
class VisionOptions:
    """Resolved ``llm.vision`` config plus the root relative paths resolve against."""

    #: False => never send pixels; every image degrades to a text placeholder.
    enabled: bool = True
    #: Long-edge cap. 2560 sits inside all three vendors' safe range while
    #: cutting a 4K upload ~4x. Deliberately NOT 1568: Anthropic downsamples
    #: rather than rejecting, so forcing its standard-tier limit would throw
    #: away resolution its high-resolution tier (2576 px) can use.
    max_edge: int = 2560
    #: Hard ceiling on the base64 STRING length (DashScope's limit is expressed
    #: that way). 8 MB leaves 2 MB of headroom under its 10 MB.
    max_bytes: int = 8 * 1024 * 1024
    #: OpenAI-family ``detail``; 'low' is an explicit cost lever.
    detail: str = 'auto'
    #: Transcode GIF/BMP/TIFF/HEIC to PNG instead of skipping them.
    transcode: bool = True
    #: Keep only the most recent N images in context (0 = unlimited).
    max_images: int = 0
    #: Directory workspace-relative ``path`` values resolve against.
    workspace_root: str = ''

    @classmethod
    def from_config(cls,
                    config: Any,
                    workspace_root: str = '') -> 'VisionOptions':
        """Build from an agent ``config`` (``llm.vision`` block, all optional)."""
        vision = None
        llm = getattr(config, 'llm', None)
        if llm is not None:
            vision = getattr(llm, 'vision', None)
        root = workspace_root or str(getattr(config, 'output_dir', '') or '')

        def pick(name: str, default):
            if vision is None:
                return default
            value = getattr(vision, name, None)
            return default if value is None else value

        return cls(
            enabled=bool(pick('enabled', True)),
            max_edge=int(pick('max_edge', cls.max_edge)),
            max_bytes=int(pick('max_bytes', cls.max_bytes)),
            detail=str(pick('detail', cls.detail)),
            transcode=bool(pick('transcode', True)),
            max_images=int(pick('max_images', 0)),
            workspace_root=root,
        )


@dataclass(frozen=True)
class ImageRef:
    """One normalized image attachment reference."""

    path: str
    media_type: str
    label: str = ''

    @property
    def filename(self) -> str:
        return os.path.basename(self.path) or self.path


def _guess_media_type(path: str, declared: str = '') -> str:
    if declared and declared.startswith('image/'):
        return declared.lower()
    guessed = mimetypes.guess_type(path)[0] or ''
    return guessed.lower() if guessed.startswith('image/') else ''


def image_refs(attachments: Optional[Sequence[Dict[str, Any]]],
               opts: Optional[VisionOptions] = None) -> List[ImageRef]:
    """The image attachments of a message, in order, as normalized refs.

    Non-image entries and entries whose type this build cannot render are
    dropped; ``max_images`` keeps the most RECENT ones (a later image is more
    likely what the current question is about).
    """
    if not attachments:
        return []
    opts = opts or VisionOptions()
    refs: List[ImageRef] = []
    for index, item in enumerate(attachments):
        if not isinstance(item, dict) or item.get('type') != 'image':
            continue
        path = str(item.get('path') or '')
        if not path:
            continue
        media_type = _guess_media_type(path, str(item.get('media_type') or ''))
        if not media_type:
            logger.warning(
                '[vision] attachment %s has no recognizable image type; skipped',
                path)
            continue
        label = str(item.get('label') or '')
        refs.append(ImageRef(path=path, media_type=media_type, label=label))
    if opts.max_images and len(refs) > opts.max_images:
        dropped = len(refs) - opts.max_images
        logger.info(
            '[vision] %d image(s) dropped from context (max_images=%d); '
            'the most recent %d are kept', dropped, opts.max_images,
            opts.max_images)
        refs = refs[-opts.max_images:]
    return refs


def _resolve_path(path: str, root: str) -> str:
    if os.path.isabs(path):
        return os.path.normpath(path)
    if root:
        return os.path.normpath(os.path.join(root, path))
    return os.path.normpath(path)


def _encode(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def _pil():
    try:
        from PIL import Image  # noqa: F401
        return Image
    except ImportError:  # pragma: no cover - pillow is a base dependency
        return None


#: Progressive JPEG quality ladder used only when a resize alone cannot get the
#: encoded size under budget. Mirrors opencode's approach.
_JPEG_QUALITIES = (85, 75, 60, 45)


def _shrink(raw: bytes, media_type: str,
            opts: VisionOptions) -> Tuple[str, str]:
    """Return ``(base64, media_type)`` within ``opts`` limits.

    Proactive rather than send-and-retry: Anthropic silently downsamples instead
    of rejecting, so a reactive strategy would never fire there and we would
    upload full-resolution images for nothing.
    """
    Image = _pil()
    encoded = _encode(raw)
    needs_transcode = media_type not in SUPPORTED_MEDIA_TYPES
    if Image is None:
        if needs_transcode:
            raise ValueError(
                f'{media_type} needs transcoding but Pillow is unavailable')
        return encoded, media_type

    with Image.open(io.BytesIO(raw)) as img:
        # Animated source: the vendors only look at the first frame anyway.
        try:
            img.seek(0)
        except (EOFError, ValueError):
            pass
        width, height = img.size
        oversize = max(width, height) > opts.max_edge
        if not needs_transcode and not oversize and len(
                encoded) <= opts.max_bytes:
            return encoded, media_type

        has_alpha = img.mode in ('RGBA', 'LA') or (img.mode == 'P' and
                                                   'transparency' in img.info)
        frame = img.convert('RGBA' if has_alpha else 'RGB')
        if oversize:
            scale = opts.max_edge / float(max(width, height))
            frame = frame.resize(
                (max(1, round(width * scale)), max(1, round(height * scale))),
                Image.LANCZOS)

        # PNG first when it is likely to both fit and matter: transparency must
        # not be flattened, and the images users attach to a chat are mostly
        # screenshots/diagrams/text, where JPEG ringing is exactly what makes
        # small type unreadable — the one thing the model is being asked to
        # read. For a large photo PNG would be huge and pointless, so only try
        # it under ~2 MP; the JPEG ladder below is the fallback either way.
        pixels = frame.size[0] * frame.size[1]
        prefer_png = has_alpha or pixels <= 2_000_000
        candidates: List[Tuple[str, str]] = []
        if prefer_png:
            buf = io.BytesIO()
            frame.save(buf, format='PNG', optimize=True)
            candidates.append((_encode(buf.getvalue()), 'image/png'))
        for quality in _JPEG_QUALITIES:
            buf = io.BytesIO()
            frame.convert('RGB').save(
                buf, format='JPEG', quality=quality, optimize=True)
            candidates.append((_encode(buf.getvalue()), 'image/jpeg'))
        if not prefer_png:
            # Lossless last resort for a big image the ladder could not fit.
            buf = io.BytesIO()
            frame.save(buf, format='PNG', optimize=True)
            candidates.append((_encode(buf.getvalue()), 'image/png'))

        for encoded_candidate, candidate_type in candidates:
            if len(encoded_candidate) <= opts.max_bytes:
                return encoded_candidate, candidate_type

        # Still too big at the lowest quality: halve the edge and recurse once
        # per step until it fits or the image is degenerate.
        edge = max(frame.size)
        while edge > 64:
            edge = int(edge * 0.6)
            scale = edge / float(max(frame.size))
            small = frame.convert('RGB').resize(
                (max(1, round(frame.size[0] * scale)),
                 max(1, round(frame.size[1] * scale))), Image.LANCZOS)
            buf = io.BytesIO()
            small.save(buf, format='JPEG', quality=60, optimize=True)
            encoded_candidate = _encode(buf.getvalue())
            if len(encoded_candidate) <= opts.max_bytes:
                return encoded_candidate, 'image/jpeg'
        raise ValueError(
            f'cannot bring image under {opts.max_bytes} base64 bytes')


@lru_cache(maxsize=64)
def _load_cached(abs_path: str, mtime: float, size: int, media_type: str,
                 max_edge: int, max_bytes: int,
                 transcode: bool) -> Tuple[str, str]:
    """``(base64, media_type)``, memoized on the file identity + encode params.

    The whole history is re-sent every round, so without this the same image is
    re-read and re-encoded on every single request of a conversation.
    """
    with open(abs_path, 'rb') as handle:
        raw = handle.read()
    if media_type in TRANSCODE_MEDIA_TYPES and not transcode:
        raise ValueError(f'{media_type} is not accepted and transcode is off')
    opts = VisionOptions(
        max_edge=max_edge, max_bytes=max_bytes, transcode=transcode)
    return _shrink(raw, media_type, opts)


def load_image(ref: ImageRef,
               opts: VisionOptions) -> Optional[Tuple[str, str]]:
    """``(base64, media_type)`` for one ref, or None when it cannot be sent.

    Never raises: a missing file or an un-encodable image must degrade to a text
    placeholder, not kill the turn.
    """
    abs_path = _resolve_path(ref.path, opts.workspace_root)
    try:
        stat = os.stat(abs_path)
    except OSError as exc:
        logger.warning('[vision] cannot read %s: %s', abs_path, exc)
        return None
    try:
        return _load_cached(abs_path, stat.st_mtime, stat.st_size,
                            ref.media_type, opts.max_edge, opts.max_bytes,
                            opts.transcode)
    except Exception as exc:  # encode/transcode failure
        logger.warning('[vision] cannot encode %s: %s', abs_path, exc)
        return None


def placeholder_for(ref: ImageRef, reason: str = '') -> str:
    """The text a model sees in place of an image it cannot be shown.

    Written for the model to be able to explain itself: a user who asks "what's
    in this picture" must get an answer that says why it cannot see it and what
    to do, not a silent non-answer.
    """
    head = ref.label or f'Image: {ref.filename}'
    body = (f'[{head} — not shown as an image. {reason} '
            f'The file is in the workspace at "{ref.path}".]')
    return body


#: Reason strings, kept here so the wording is identical across transports.
#: Both spell out that any earlier image descriptions in the conversation came
#: from a model that could see the pictures. Without that sentence, a model
#: switched in mid-session sees "not shown" placeholders NEXT TO confident
#: assistant answers about the same images, resolves the contradiction as "so I
#: did see them after all", and claims present-tense sight (measured on
#: qwen3.7-max: it answered 能看到 and repeated its predecessor's reading).
#: The shared middle sentence: what to do about earlier descriptions.
_HISTORY_NOTE = (
    'Earlier replies in this conversation that describe it were written while '
    'a vision-capable model was active: treat them as reliable history, but do '
    'not claim to see the image yourself.')

#: The switch is off (the default). The remedy is to turn it on.
REASON_DISABLED = (
    'Image understanding is not enabled for the current model, so you cannot '
    f'see this image now. {_HISTORY_NOTE} Tell the user they can turn on '
    '"image understanding" for this model in Settings → Models, or switch to a '
    'model that supports it.')

#: The switch is ON but the endpoint rejected the image. Telling this user to
#: "enable image understanding" would point at a box they already ticked, so
#: this wording names the real situation and offers the remedy that is left.
REASON_REJECTED = (
    'This model rejected image input, so you cannot see this image even though '
    f'image understanding is enabled for it. {_HISTORY_NOTE} Tell the user this '
    'model cannot accept images and that they should switch to one that can.')

REASON_UNREADABLE = ('The file could not be read or decoded as an image.')


def _label_block(ref: ImageRef, index: int) -> Dict[str, str]:
    """The ``Image N: <filename>`` introducer.

    Anthropic's own guidance: label each image with a short text block so it can
    be referred to by name in this turn and in later ones. The ordinal carries
    "the second image"; the filename carries "the chart one".
    """
    return {
        'type': 'text',
        'text': ref.label or f'Image {index}: {ref.filename}',
    }


def _degrade(text: str, refs: Sequence[ImageRef], reason: str) -> str:
    """Fold every image into the text turn as placeholders."""
    notes = [placeholder_for(ref, reason) for ref in refs]
    joined = '\n'.join(notes)
    return f'{joined}\n\n{text}' if text else joined


def openai_content(text: Any,
                   attachments: Optional[Sequence[Dict[str, Any]]],
                   opts: VisionOptions,
                   vision_supported: bool = True,
                   disabled_reason: str = REASON_DISABLED) -> Any:
    """Content for an OpenAI-compatible (Chat Completions) user message.

    Returns a plain string when there is nothing to attach — keeping the
    overwhelmingly common text-only request byte-identical to before, which also
    means prefix caching is unaffected.

    ``disabled_reason`` lets the caller say WHY the pixels are absent: the
    default blames the switch, and a transport that knows the endpoint rejected
    this model's images passes :data:`REASON_REJECTED` instead, so the model
    never tells a user to enable something they already enabled.
    """
    refs = image_refs(attachments, opts)
    if not refs:
        return text
    if not (opts.enabled and vision_supported):
        return _degrade(
            text if isinstance(text, str) else '', refs, disabled_reason)

    blocks: List[Dict[str, Any]] = []
    unreadable: List[ImageRef] = []
    for index, ref in enumerate(refs, start=1):
        loaded = load_image(ref, opts)
        if loaded is None:
            unreadable.append(ref)
            continue
        encoded, media_type = loaded
        blocks.append(_label_block(ref, index))
        image_url: Dict[str, Any] = {
            'url': f'data:{media_type};base64,{encoded}'
        }
        if opts.detail and opts.detail != 'auto':
            image_url['detail'] = opts.detail
        blocks.append({'type': 'image_url', 'image_url': image_url})

    if not blocks:  # every image failed to load
        return _degrade(
            text if isinstance(text, str) else '', unreadable,
            REASON_UNREADABLE)

    tail = text if isinstance(text, str) else ''
    if unreadable:
        tail = _degrade(tail, unreadable, REASON_UNREADABLE)
    if tail:
        blocks.append({'type': 'text', 'text': tail})
    return blocks


def anthropic_content(text: Any,
                      attachments: Optional[Sequence[Dict[str, Any]]],
                      opts: VisionOptions,
                      vision_supported: bool = True,
                      disabled_reason: str = REASON_DISABLED) -> Any:
    """Content blocks for an Anthropic Messages user message.

    Same contract as :func:`openai_content`; only the block shape differs
    (``{'type':'image','source':{'type':'base64',...}}``).
    """
    refs = image_refs(attachments, opts)
    if not refs:
        return text
    if not (opts.enabled and vision_supported):
        return _degrade(
            text if isinstance(text, str) else '', refs, disabled_reason)

    blocks: List[Dict[str, Any]] = []
    unreadable: List[ImageRef] = []
    for index, ref in enumerate(refs, start=1):
        loaded = load_image(ref, opts)
        if loaded is None:
            unreadable.append(ref)
            continue
        encoded, media_type = loaded
        blocks.append(_label_block(ref, index))
        blocks.append({
            'type': 'image',
            'source': {
                'type': 'base64',
                'media_type': media_type,
                'data': encoded,
            },
        })

    if not blocks:
        return _degrade(
            text if isinstance(text, str) else '', unreadable,
            REASON_UNREADABLE)

    tail = text if isinstance(text, str) else ''
    if unreadable:
        tail = _degrade(tail, unreadable, REASON_UNREADABLE)
    if tail:
        blocks.append({'type': 'text', 'text': tail})
    return blocks


def has_image_blocks(content: Any) -> bool:
    """True when already-built content carries a provider-native image block.

    Used by the refusal fallback to know whether THIS request actually shipped
    pixels — the only reliable signal, since a provider's rejection text may not
    mention images at all (measured on DashScope: "Unexpected item type in
    content", no mention of image/multimodal/vision).
    """
    if not isinstance(content, list):
        return False
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get('type') in ('image_url', 'image', 'input_image'):
            return True
    return False


#: What the model is told in place of an image the endpoint just refused.
#: Deliberately as informative as the proactive placeholder: the user asked
#: about a picture, so a bare "not available" makes the model reply "please
#: upload the image" — which is both wrong (it WAS uploaded) and unactionable.
#: Measured before this text existed, qwen3.7-max answered exactly that.
REASON_REFUSED = (
    'not visible: this model rejected image input. The file was uploaded and is '
    'in the workspace under the name shown above. Any earlier replies that '
    'describe this image came from a model that could see it. Tell the user '
    'this model cannot view images, and that they can enable "image '
    'understanding" for it in Settings → Models or switch to a model that '
    'supports vision.')


def strip_image_blocks(content: Any) -> Any:
    """``content`` with image blocks replaced by an explanatory text marker.

    The retry after a refusal must still say WHAT was dropped and WHY, or the
    model answers a question about an image it was never told about. The
    preceding ``Image N: <filename>`` label block survives, so the marker only
    has to supply the reason and the remedy.
    """
    if not isinstance(content, list):
        return content
    texts: List[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get('type') == 'text':
            value = str(item.get('text') or '')
            if value:
                texts.append(value)
        elif item.get('type') in ('image_url', 'image', 'input_image'):
            texts.append(f'[{REASON_REFUSED}]')
    return '\n'.join(texts)


def estimate_content_tokens(content: Any, text_estimator) -> int:
    """Token estimate for possibly-multimodal content.

    ``text_estimator`` scores a string. Image blocks get a flat
    :data:`IMAGE_TOKEN_ESTIMATE` each instead of having their base64 measured as
    text — the bug this exists to prevent inflates a single 2 MiB PNG to
    ~699k tokens against a ~108k budget, which re-fires compaction every round.
    """
    if content is None:
        return 0
    if isinstance(content, str):
        return text_estimator(content)
    if not isinstance(content, list):
        return text_estimator(str(content))
    total = 0
    for item in content:
        if not isinstance(item, dict):
            total += text_estimator(str(item))
            continue
        kind = item.get('type')
        if kind in ('image_url', 'image', 'input_image'):
            total += IMAGE_TOKEN_ESTIMATE
        elif kind == 'text':
            total += text_estimator(str(item.get('text') or ''))
        else:
            # Unknown block: measure its text-ish payload, never its raw bytes.
            total += text_estimator(str(item.get('text') or ''))
    return total


#: Introduces images hoisted out of a tool result into their own user turn.
#:
#: Why hoist at all: the Chat Completions SCHEMA restricts a ``role: "tool"``
#: message to text. OpenAI's own generated types say
#: ``Union[str, Iterable[ChatCompletionContentPartTextParam]]`` for a tool
#: message, versus the wider union (text | image_url | input_audio | file) for a
#: user message. The Responses API is different — its ``function_call_output``
#: does allow image content — which is why AI-SDK-based clients report "OpenAI
#: supports media in tool results"; they are on that API, we are on this one.
#:
#: Measured (2026-08) against five OpenAI-compatible providers — DashScope,
#: ModelScope, OpenRouter, Kimi, MiniMax — inline image parts in a tool message
#: were accepted and read correctly by all five, i.e. they are more permissive
#: than the schema. Hoisting is kept anyway because it is valid under BOTH the
#: schema and every provider tested, whereas inline is valid only under the
#: latter; real OpenAI (the one endpoint whose schema forbids it) was not
#: testable here. Same reasoning as any other spec-vs-practice split: prefer the
#: form that cannot be wrong.
#:
#: The Anthropic transport does NOT hoist — that protocol allows image blocks
#: inside ``tool_result``, so there the image stays attached to the call that
#: produced it. Mirrors opencode's SYNTHETIC_ATTACHMENT_PROMPT.
TOOL_MEDIA_PROMPT = 'Images returned by the tool call above:'


def openai_tool_media_message(
        attachments: Sequence[Dict[str, Any]],
        opts: VisionOptions,
        vision_supported: bool = True) -> Optional[Dict[str, Any]]:
    """A synthetic user message carrying a tool result's images, or None.

    Returns None when there is nothing to show — no images, images disabled, or
    none of them could be loaded — so the caller appends nothing and the tool's
    own text stands on its own.
    """
    refs = image_refs(attachments, opts)
    if not refs or not (opts.enabled and vision_supported):
        return None
    content = openai_content(
        TOOL_MEDIA_PROMPT, attachments, opts, vision_supported=True)
    if not isinstance(content, list):
        return None  # every image failed to load; the tool text already says so
    return {'role': 'user', 'content': content}


def anthropic_tool_result_blocks(
        attachments: Sequence[Dict[str, Any]],
        opts: VisionOptions,
        vision_supported: bool = True) -> List[Dict[str, Any]]:
    """Image blocks to nest INSIDE an Anthropic ``tool_result``.

    Anthropic allows image blocks in tool_result content, so the image can stay
    attached to the call that produced it — strictly better than hoisting, since
    the association survives without relying on message order.
    """
    refs = image_refs(attachments, opts)
    if not refs or not (opts.enabled and vision_supported):
        return []
    blocks: List[Dict[str, Any]] = []
    for index, ref in enumerate(refs, start=1):
        loaded = load_image(ref, opts)
        if loaded is None:
            continue
        encoded, media_type = loaded
        blocks.append(_label_block(ref, index))
        blocks.append({
            'type': 'image',
            'source': {
                'type': 'base64',
                'media_type': media_type,
                'data': encoded,
            },
        })
    return blocks
