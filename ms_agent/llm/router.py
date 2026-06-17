# Copyright (c) ModelScope Contributors. All rights reserved.
"""Provider routing: config -> ProviderSpec -> Transport -> LLMProvider.

``ProviderRouter.create(config)`` is the data-driven replacement for the
hard-coded ``all_services_mapping`` factory. It resolves the spec (by service
name, then by model-name keywords, else a generic OpenAI-compatible fallback),
resolves credentials, builds the matching transport, and returns an
``LLMProvider``.

``LLMProvider`` is a drop-in for the legacy LLM instances on the agent hot path:
it exposes ``.model``, ``.config`` and ``.generate(messages, tools, **kwargs)``
returning ``Message`` / ``Generator[Message]``. Typed ``LLMResponse`` output is
available via ``generate_response`` for new consumers.
"""
from __future__ import annotations

from typing import Generator, List, Optional, Union

from omegaconf import DictConfig, OmegaConf

from ms_agent.utils import get_logger

from .adapter import ResponseAdapter
from .credentials import CredentialResolver
from .retry import smart_retry
from .spec import (TRANSPORT_ANTHROPIC_MESSAGES, TRANSPORT_OPENAI_COMPAT,
                   ProviderSpec, get_registry)
from .transport.base import Transport
from .types import LLMResponse, ProviderCapabilities
from .utils import Message, Tool

logger = get_logger()


def _build_transport(spec: ProviderSpec, model: str, api_key: Optional[str],
                     base_url: str, gen_config: dict) -> Transport:
    if spec.transport == TRANSPORT_ANTHROPIC_MESSAGES:
        from .transport.anthropic_messages import AnthropicMessagesTransport
        return AnthropicMessagesTransport(
            model=model,
            api_key=api_key,
            base_url=base_url,
            generation_config=gen_config,
        )
    if spec.transport == TRANSPORT_OPENAI_COMPAT:
        from .transport.openai_compat import OpenAICompatTransport
        return OpenAICompatTransport(
            model=model,
            api_key=api_key,
            base_url=base_url,
            generation_config=gen_config,
            continue_gen_mode=spec.continue_gen_mode,
            continue_gen_stop=spec.continue_gen_stop,
            strip_reasoning_tags=spec.strip_reasoning_tags,
        )
    raise ValueError(f'Unknown transport: {spec.transport}')


class LLMProvider:
    """Drop-in LLM facade built from a ProviderSpec + Transport."""

    def __init__(self, config: DictConfig, spec: ProviderSpec,
                 transport: Transport):
        self.config = config
        self.spec = spec
        self.transport = transport
        self.model = config.llm.model

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self.spec.capabilities

    @smart_retry()
    def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Tool]] = None,
        **kwargs,
    ) -> Union[Message, Generator[Message, None, None]]:
        return self.transport.generate(messages, tools, **kwargs)

    def generate_response(
        self,
        messages: List[Message],
        tools: Optional[List[Tool]] = None,
        **kwargs,
    ) -> LLMResponse:
        """Non-streaming typed output for new consumers (e.g. WebUI)."""
        kwargs['stream'] = False
        message = self.transport.generate(messages, tools, **kwargs)
        return ResponseAdapter.to_response(message)


class ProviderRouter:

    def __init__(self):
        self._registry = get_registry()

    def create(self, config: DictConfig) -> LLMProvider:
        service = config.llm.get('service') if hasattr(config.llm,
                                                       'get') else getattr(
                                                           config.llm,
                                                           'service', None)
        model = config.llm.model

        spec = self._registry.get(service)
        if spec is None:
            spec = self._registry.resolve_by_model(model)
        if spec is None:
            logger.info(
                f'No provider spec for service={service} model={model}; '
                f'falling back to a generic OpenAI-compatible transport.')
            spec = ProviderSpec(
                name=service or 'custom',
                display_name=service or 'Custom',
                transport=TRANSPORT_OPENAI_COMPAT,
                api_key_env=['OPENAI_API_KEY'],
                base_url_env=['OPENAI_BASE_URL'],
            )

        api_key = CredentialResolver.resolve_api_key(spec, config)
        base_url = CredentialResolver.resolve_base_url(spec, config)
        if not api_key:
            raise ValueError(
                f'No API key found for provider "{spec.name}". Set one of '
                f'{spec.api_key_env} or config.llm.{spec.name}_api_key.')

        gen_config = OmegaConf.to_container(
            getattr(config, 'generation_config', DictConfig({})))
        gen_config = {**spec.default_generation_config, **(gen_config or {})}

        transport = _build_transport(spec, model, api_key, base_url,
                                     gen_config)
        return LLMProvider(config=config, spec=spec, transport=transport)
