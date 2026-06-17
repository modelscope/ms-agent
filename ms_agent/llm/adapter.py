# Copyright (c) ModelScope Contributors. All rights reserved.
"""Conversion between the legacy ``Message`` and the typed ``LLMResponse``.

Transports return ``Message`` (the proven hot-path contract). New consumers
(e.g. the WebUI) can use ``ResponseAdapter.to_response`` to get typed content
blocks. ``to_message`` is the inverse, for code that produces ``LLMResponse``
and needs to feed the legacy agent loop.
"""
from __future__ import annotations

import json
from typing import List, Optional

from .types import (LLMResponse, TextBlock, ThinkingBlock, ToolUseBlock,
                    UsageInfo)
from .utils import Message, ToolCall


def _parse_arguments(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


class ResponseAdapter:

    @staticmethod
    def to_response(message: Message) -> LLMResponse:
        """Legacy ``Message`` -> typed ``LLMResponse`` (for new consumers)."""
        blocks: List = []
        if message.reasoning_content:
            blocks.append(ThinkingBlock(thinking=message.reasoning_content))
        if message.content and isinstance(message.content, str):
            blocks.append(TextBlock(text=message.content))
        for tc in (message.tool_calls or []):
            blocks.append(
                ToolUseBlock(
                    id=tc.get('id', ''),
                    name=tc.get('tool_name', ''),
                    arguments=_parse_arguments(tc.get('arguments', {})),
                ))
        usage = UsageInfo(
            prompt_tokens=message.prompt_tokens,
            completion_tokens=message.completion_tokens,
            cached_tokens=message.cached_tokens,
            cache_creation_tokens=message.cache_creation_input_tokens,
            reasoning_tokens=message.reasoning_tokens,
        )
        return LLMResponse(
            content_blocks=blocks, usage=usage, id=message.id)

    @staticmethod
    def to_message(response: LLMResponse) -> Message:
        """Typed ``LLMResponse`` -> legacy ``Message``.

        ``tool_calls`` arguments are serialized to a JSON string to match the
        OpenAI-path contract consumed by the agent loop.
        """
        tool_calls: Optional[List[ToolCall]] = None
        if response.tool_calls:
            tool_calls = []
            for idx, tc in enumerate(response.tool_calls):
                args = tc.arguments
                if isinstance(args, dict):
                    args = json.dumps(args, ensure_ascii=False)
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        index=idx,
                        type='function',
                        tool_name=tc.name,
                        arguments=args,
                    ))
        return Message(
            role='assistant',
            content=response.text,
            reasoning_content=response.thinking,
            tool_calls=tool_calls or [],
            id=response.id,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            cached_tokens=response.usage.cached_tokens,
            cache_creation_input_tokens=response.usage.cache_creation_tokens,
            reasoning_tokens=response.usage.reasoning_tokens,
        )
