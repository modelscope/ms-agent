# Copyright (c) ModelScope Contributors. All rights reserved.
"""Unified, typed response model for the LLM provider layer.

This module introduces a provider-agnostic response representation built from
typed content blocks (text / tool-use / thinking) plus a normalized usage
object. It is consumed by new clients (e.g. the WebUI) that prefer structured
blocks over the flat, field-heavy ``Message`` dataclass.

The existing ``Message`` (``ms_agent/llm/utils.py``) remains the canonical type
on the hot path for backward compatibility; ``ResponseAdapter`` converts between
the two.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Union


@dataclass(frozen=True)
class TextBlock:
    text: str = ''
    type: str = 'text'


@dataclass(frozen=True)
class ToolUseBlock:
    id: str = ''
    name: str = ''
    # Parsed arguments. Always a dict at this layer; the adapter serializes it
    # back to a JSON string when producing a legacy ``Message.tool_calls`` entry.
    arguments: dict = field(default_factory=dict)
    type: str = 'tool_use'


@dataclass(frozen=True)
class ThinkingBlock:
    thinking: str = ''
    type: str = 'thinking'


ContentBlock = Union[TextBlock, ToolUseBlock, ThinkingBlock]


@dataclass(frozen=True)
class UsageInfo:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # Tokens that hit an existing cache (billed at a reduced rate).
    cached_tokens: int = 0
    # Tokens used to create a new explicit cache entry (billed at a higher rate).
    cache_creation_tokens: int = 0
    # Reasoning/thinking tokens (a subset of completion_tokens for thinking models).
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class LLMResponse:
    """Provider-agnostic response. Produced from a ``Message`` by the adapter."""

    content_blocks: List[ContentBlock] = field(default_factory=list)
    usage: UsageInfo = field(default_factory=UsageInfo)
    finish_reason: str = 'stop'
    id: str = ''
    model: str = ''

    @property
    def text(self) -> str:
        return ''.join(b.text for b in self.content_blocks
                       if isinstance(b, TextBlock))

    @property
    def thinking(self) -> str:
        return ''.join(b.thinking for b in self.content_blocks
                       if isinstance(b, ThinkingBlock))

    @property
    def tool_calls(self) -> List[ToolUseBlock]:
        return [b for b in self.content_blocks if isinstance(b, ToolUseBlock)]


class ProviderCapability(str, Enum):
    TOOL_CALL = 'tool_call'
    STREAMING = 'streaming'
    REASONING = 'reasoning'
    VISION = 'vision'
    PREFIX_CACHE = 'prefix_cache'
    CONTINUE_GEN = 'continue_gen'


@dataclass(frozen=True)
class ProviderCapabilities:
    """Declarative capability set for a provider.

    Lets callers (agent loop, WebUI) query what a provider/model supports
    instead of hard-coding behavior per provider.
    """

    capabilities: frozenset = frozenset()

    def supports(self, cap: ProviderCapability) -> bool:
        return cap in self.capabilities

    def to_list(self) -> List[str]:
        return sorted(c.value for c in self.capabilities)

    @staticmethod
    def from_list(caps: List[str]) -> 'ProviderCapabilities':
        return ProviderCapabilities(
            capabilities=frozenset(ProviderCapability(c) for c in caps))
