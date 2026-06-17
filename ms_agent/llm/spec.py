# Copyright (c) ModelScope Contributors. All rights reserved.
"""Data-driven provider registry.

A ``ProviderSpec`` is a single declarative record that fully describes a
provider: which transport (wire protocol) to use, where to find credentials,
how to recognize its models, what it can do, and any model-level quirks
(continue-generation mode, prefix caching). Adding a new OpenAI-compatible
provider is just one ``ProviderSpec`` entry -- no new class.

This replaces the hard-coded ``all_services_mapping`` (4 entries) and the thin
``ModelScope``/``DashScope``/``DeepSeek`` subclasses, whose only real
differences (base_url, api_key, continue-gen flag) become spec data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .types import ProviderCapabilities

# Transport identifiers (see ``ms_agent/llm/transport``).
TRANSPORT_OPENAI_COMPAT = 'openai_compat'
TRANSPORT_ANTHROPIC_MESSAGES = 'anthropic_messages'


@dataclass(frozen=True)
class ProviderSpec:
    """All metadata needed to instantiate a provider."""

    name: str
    display_name: str
    transport: str
    # Environment variable lookup chain for the API key.
    api_key_env: List[str] = field(default_factory=list)
    default_base_url: str = ''
    # Environment variable lookup chain for the base url.
    base_url_env: List[str] = field(default_factory=list)
    # Substrings used to resolve a provider from a bare model name.
    keywords: List[str] = field(default_factory=list)
    # Alternative service names that resolve to this spec (e.g. 'glm' -> zhipu).
    aliases: List[str] = field(default_factory=list)
    capabilities: ProviderCapabilities = field(
        default_factory=ProviderCapabilities)
    # Continue-generation mode for OpenAI-compatible providers:
    #   'partial' (DashScope/Bailian) | 'prefix' (DeepSeek beta) | None
    continue_gen_mode: Optional[str] = None
    # Extra stop sequences appended during prefix-mode continuation.
    continue_gen_stop: List[str] = field(default_factory=list)
    # Some providers (e.g. MiniMax M-series) emit chain-of-thought inline as a
    # leading <think>...</think> block in `content` instead of a separate
    # reasoning field. When True, that block is moved to reasoning_content.
    strip_reasoning_tags: bool = False
    # Generation-config defaults merged under the user's config.
    default_generation_config: Dict = field(default_factory=dict)


class ProviderRegistry:
    """Registry of provider specs. Built-ins plus runtime registration."""

    def __init__(self) -> None:
        self._specs: Dict[str, ProviderSpec] = {}
        self._aliases: Dict[str, str] = {}
        self._register_builtins()

    def register(self, spec: ProviderSpec) -> None:
        self._specs[spec.name] = spec
        for alias in spec.aliases:
            self._aliases[alias.lower()] = spec.name

    def get(self, name: Optional[str]) -> Optional[ProviderSpec]:
        if not name:
            return None
        key = name.lower()
        if key in self._specs:
            return self._specs[key]
        if key in self._aliases:
            return self._specs[self._aliases[key]]
        return None

    def resolve_by_model(self, model_name: str) -> Optional[ProviderSpec]:
        """Resolve a provider from a bare model name via keyword match."""
        if not model_name:
            return None
        model_lower = model_name.lower()
        for spec in self._specs.values():
            for kw in spec.keywords:
                if kw and kw.lower() in model_lower:
                    return spec
        return None

    def list_providers(self) -> List[ProviderSpec]:
        return list(self._specs.values())

    def _register_builtins(self) -> None:
        openai_caps = ProviderCapabilities.from_list(
            ['tool_call', 'streaming', 'vision', 'continue_gen'])
        openai_cache_caps = ProviderCapabilities.from_list(
            ['tool_call', 'streaming', 'vision', 'prefix_cache',
             'continue_gen'])
        anthropic_caps = ProviderCapabilities.from_list(
            ['tool_call', 'streaming', 'reasoning', 'vision', 'prefix_cache'])
        reasoning_caps = ProviderCapabilities.from_list(
            ['tool_call', 'streaming', 'reasoning', 'continue_gen'])

        builtins = [
            ProviderSpec(
                name='openai',
                display_name='OpenAI',
                transport=TRANSPORT_OPENAI_COMPAT,
                api_key_env=['OPENAI_API_KEY'],
                default_base_url='https://api.openai.com/v1',
                base_url_env=['OPENAI_BASE_URL'],
                keywords=['gpt-', 'o1-', 'o3-', 'o4-', 'chatgpt'],
                capabilities=openai_caps,
            ),
            ProviderSpec(
                name='anthropic',
                display_name='Anthropic',
                transport=TRANSPORT_ANTHROPIC_MESSAGES,
                api_key_env=['ANTHROPIC_API_KEY'],
                default_base_url='https://api.anthropic.com',
                base_url_env=['ANTHROPIC_BASE_URL'],
                keywords=['claude-'],
                capabilities=anthropic_caps,
            ),
            ProviderSpec(
                name='google',
                display_name='Google Gemini',
                transport=TRANSPORT_OPENAI_COMPAT,
                api_key_env=['GOOGLE_API_KEY', 'GEMINI_API_KEY'],
                default_base_url=
                'https://generativelanguage.googleapis.com/v1beta/openai/',
                base_url_env=['GOOGLE_BASE_URL'],
                keywords=['gemini-', 'gemma-'],
                capabilities=openai_caps,
            ),
            ProviderSpec(
                name='modelscope',
                display_name='ModelScope',
                transport=TRANSPORT_OPENAI_COMPAT,
                api_key_env=['MODELSCOPE_API_KEY'],
                default_base_url='https://api-inference.modelscope.cn/v1',
                base_url_env=['MODELSCOPE_BASE_URL'],
                keywords=['qwen'],
                capabilities=openai_cache_caps,
            ),
            ProviderSpec(
                name='zhipu',
                display_name='Zhipu AI (GLM)',
                transport=TRANSPORT_OPENAI_COMPAT,
                api_key_env=['GLM_API_KEY', 'ZHIPU_API_KEY', 'ZHIPUAI_API_KEY'],
                default_base_url='https://open.bigmodel.cn/api/paas/v4',
                base_url_env=['GLM_BASE_URL', 'ZHIPU_BASE_URL'],
                keywords=['glm-', 'glm4', 'cogview', 'charglm'],
                aliases=['glm', 'bigmodel'],
                capabilities=openai_caps,
            ),
            ProviderSpec(
                name='kimi',
                display_name='Moonshot Kimi',
                transport=TRANSPORT_OPENAI_COMPAT,
                api_key_env=['KIMI_API_KEY', 'MOONSHOT_API_KEY'],
                default_base_url='https://api.moonshot.cn/v1',
                base_url_env=['KIMI_BASE_URL', 'MOONSHOT_BASE_URL'],
                keywords=['kimi', 'moonshot'],
                aliases=['moonshot'],
                capabilities=openai_caps,
            ),
            ProviderSpec(
                name='deepseek',
                display_name='DeepSeek',
                transport=TRANSPORT_OPENAI_COMPAT,
                api_key_env=['DEEPSEEK_API_KEY'],
                default_base_url='https://api.deepseek.com/v1',
                base_url_env=['DEEPSEEK_BASE_URL'],
                keywords=['deepseek-'],
                capabilities=reasoning_caps,
                # Prefix-mode continuation requires the beta endpoint
                # (https://api.deepseek.com/beta); set DEEPSEEK_BASE_URL there
                # to enable chat-prefix completion.
                continue_gen_mode='prefix',
                continue_gen_stop=['```'],
            ),
            ProviderSpec(
                name='dashscope',
                display_name='Alibaba DashScope',
                transport=TRANSPORT_OPENAI_COMPAT,
                api_key_env=['DASHSCOPE_API_KEY'],
                default_base_url=
                'https://dashscope.aliyuncs.com/compatible-mode/v1',
                base_url_env=['DASHSCOPE_BASE_URL'],
                keywords=[],
                capabilities=openai_cache_caps,
                continue_gen_mode='partial',
            ),
            ProviderSpec(
                name='minimax',
                display_name='MiniMax',
                transport=TRANSPORT_OPENAI_COMPAT,
                api_key_env=['MINIMAX_API_KEY'],
                default_base_url='https://api.minimaxi.com/v1',
                base_url_env=['MINIMAX_BASE_URL'],
                keywords=['minimax', 'abab'],
                capabilities=openai_caps,
                strip_reasoning_tags=True,
            ),
            ProviderSpec(
                name='openrouter',
                display_name='OpenRouter',
                transport=TRANSPORT_OPENAI_COMPAT,
                api_key_env=['OPENROUTER_API_KEY', 'OpenRouter_API_KEY'],
                default_base_url='https://openrouter.ai/api/v1',
                base_url_env=['OPENROUTER_BASE_URL', 'OpenRouter_BASE_URL'],
                keywords=[],
                capabilities=openai_caps,
            ),
        ]
        for spec in builtins:
            self.register(spec)


_registry: Optional[ProviderRegistry] = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry
