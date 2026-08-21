# Copyright (c) ModelScope Contributors. All rights reserved.
"""One way to read the text out of a message, whatever shape its content is in.

``Message.content`` is typed ``Union[str, List[Dict[str, str]]]``, so a caller
may legitimately hand the framework a provider-shaped block list. About twenty
places read a user message's content expecting a string — memory extraction,
full-text indexing, session auto-naming, summary compaction, snapshot labels,
hook prompt extraction — and none of them fails loudly on a list: they store a
Python repr, or a guard skips the message entirely. Both are silent, and the
symptom shows up weeks later as a garbled memory row or a nonsense session name.

Image attachments in this codebase ride on ``Message.attachments`` precisely so
that ``content`` stays a string and those call sites keep working untouched. This
module is the belt to that suspenders: the highest-value of those sites route
through it, so a block list arriving from anywhere degrades to "the text of it"
rather than to garbage.

Mirrors hermes-agent's ``agent/message_content.py``, which exists for the same
reason.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, List

#: Block kinds that carry no readable text. Listed rather than inferred so a new
#: modality is a deliberate edit here instead of silently stringifying its bytes.
_NON_TEXT_BLOCKS = frozenset({
    'image',
    'image_url',
    'input_image',
    'audio',
    'input_audio',
    'video',
    'input_video',
    'file',
    'document',
})

#: Keys a text-bearing block may use, in preference order. ``content`` is last:
#: it is the most generic and the most likely to hold something structured.
_TEXT_KEYS = ('text', 'input_text', 'output_text', 'summary_text', 'content')


def _field(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _block_text(block: Any) -> str:
    if block is None:
        return ''
    if isinstance(block, str):
        return block
    kind = str(_field(block, 'type') or '').strip().lower()
    if kind in _NON_TEXT_BLOCKS:
        return ''
    for key in _TEXT_KEYS:
        value = _field(block, key)
        if isinstance(value, str):
            return value
    return ''


def flatten_message_text(content: Any, *, sep: str = '\n') -> str:
    """The readable text of ``content``, for any shape it can legitimately take.

    * ``str`` -> itself (the overwhelmingly common case, returned unchanged so
      no caller's behaviour shifts);
    * ``list`` of blocks -> the text blocks joined by ``sep``; image/audio/video
      blocks contribute nothing rather than their base64;
    * anything else -> its own text field if it has one, else ``str()``.

    Never raises, and never returns None — callers use the result in prompts,
    hashes and filenames.
    """
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts: List[str] = [_block_text(block) for block in content]
        return sep.join(part for part in parts if part)
    text = _block_text(content)
    if text:
        return text
    try:
        return str(content)
    except Exception:
        return ''


def append_text(content: Any, extra: str, *, sep: str = '\n\n') -> Any:
    """``content`` with ``extra`` appended, preserving its shape.

    A string grows; a block list gains a trailing text block. Used where the
    framework augments a user turn in place (memory recall, update notices) —
    concatenating a string onto a list would raise, and replacing the list with
    a string would drop whatever non-text blocks it carried.
    """
    if not extra:
        return content
    if isinstance(content, str) or content is None:
        base = content or ''
        return f'{base}{sep}{extra}' if base else extra
    if isinstance(content, (list, tuple)):
        return [*content, {'type': 'text', 'text': extra}]
    return f'{flatten_message_text(content)}{sep}{extra}'


def prepend_text(content: Any, extra: str, *, sep: str = '\n\n') -> Any:
    """``content`` with ``extra`` in front, preserving its shape.

    A block list gets the text block FIRST, which also matches the providers'
    preference for a short label ahead of the payload.
    """
    if not extra:
        return content
    if isinstance(content, str) or content is None:
        base = content or ''
        return f'{extra}{sep}{base}' if base else extra
    if isinstance(content, (list, tuple)):
        return [{'type': 'text', 'text': extra}, *content]
    return f'{extra}{sep}{flatten_message_text(content)}'
