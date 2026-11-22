# Copyright (c) ModelScope Contributors. All rights reserved.
"""Shared local budget estimates for legacy and session-based compaction.

These are heuristics, not billing counts. A valid API usage anchor covers the
preceding request; otherwise count readable text and media, never base64 bytes.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from ms_agent.llm import multimodal
from ms_agent.llm.message_text import flatten_message_text


def field(message: Any, name: str, default=None):
    if isinstance(message, Mapping):
        return message.get(name, default)
    return getattr(message, name, default)


def estimate_text_tokens(text: str) -> int:
    return len(text) // 4 if text else 0


def estimate_message_tokens(message: Any) -> int:
    content = field(message, 'content', '')
    refs = multimodal.image_refs(field(message, 'attachments', []))
    if refs:
        # The transport rebuilds image blocks from references. An old inline
        # representation alongside them must not charge the same pixels twice.
        total = estimate_text_tokens(flatten_message_text(content))
        total += len(refs) * multimodal.IMAGE_TOKEN_ESTIMATE
    else:
        total = multimodal.estimate_content_tokens(content,
                                                   estimate_text_tokens)
    calls = field(message, 'tool_calls')
    if calls:
        total += estimate_text_tokens(json.dumps(calls))
    total += estimate_text_tokens(
        field(message, 'reasoning_content', '') or '')
    return total


def estimate_total_tokens(messages: list) -> int:
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if field(msg, 'role') != 'assistant':
            continue
        prompt = int(field(msg, 'prompt_tokens', 0) or 0)
        completion = int(field(msg, 'completion_tokens', 0) or 0)
        if prompt or completion:
            return prompt + completion + sum(
                estimate_message_tokens(m) for m in messages[i + 1:])
    return sum(estimate_message_tokens(m) for m in messages)


def summary_attempt_key(messages: list, usable: int) -> str:
    """Identify an unchanged window without retaining its large payloads."""
    keys = ('role', 'content', 'attachments', 'tool_calls',
            'reasoning_content')
    payload = [{k: field(m, k) for k in keys} for m in messages]
    return hashlib.sha256(
        json.dumps([usable, payload], sort_keys=True,
                   ensure_ascii=False).encode()).hexdigest()


def summary_text(message: Any) -> str:
    """Readable summary input with an explicit reminder that pixels are absent."""
    content = field(message, 'content', '')
    text = flatten_message_text(content)
    if (multimodal.has_image_blocks(content)
            or multimodal.image_refs(field(message, 'attachments', []))):
        text += '\n[Image attachments omitted from this text summary; do not infer their contents.]'
    return text
