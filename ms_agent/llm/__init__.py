# Copyright (c) ModelScope Contributors. All rights reserved.
from .llm import LLM
from .utils import Message

# Data-driven provider layer (opt-in via config.llm.use_provider_router).
from .adapter import ResponseAdapter
from .credentials import CredentialResolver
from .router import LLMProvider, ProviderRouter
from .spec import ProviderRegistry, ProviderSpec, get_registry
from .types import (LLMResponse, ProviderCapabilities, ProviderCapability,
                    TextBlock, ThinkingBlock, ToolUseBlock, UsageInfo)

__all__ = [
    'LLM',
    'Message',
    'ProviderRouter',
    'LLMProvider',
    'ProviderRegistry',
    'ProviderSpec',
    'get_registry',
    'CredentialResolver',
    'ResponseAdapter',
    'LLMResponse',
    'UsageInfo',
    'TextBlock',
    'ToolUseBlock',
    'ThinkingBlock',
    'ProviderCapability',
    'ProviderCapabilities',
]
