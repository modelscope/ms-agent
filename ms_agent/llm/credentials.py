# Copyright (c) ModelScope Contributors. All rights reserved.
"""Unified credential and endpoint resolution.

Resolution order (first hit wins):
  1. Provider-specific config field   (config.llm.<name>_api_key / _base_url)
  2. Generic config field             (config.llm.api_key / base_url)
  3. Environment variable chain        (spec.api_key_env / spec.base_url_env)
  4. Spec default                      (base_url only)

This replaces per-provider ``__init__`` credential handling.
"""
from __future__ import annotations

import os
import re
from omegaconf import DictConfig
from typing import Optional

from .spec import ProviderSpec


def _cfg_get(config: DictConfig, field: str) -> Optional[str]:
    llm = getattr(config, 'llm', None)
    if llm is None:
        return None
    try:
        value = llm.get(field) if hasattr(llm, 'get') else getattr(
            llm, field, None)
    except Exception:
        value = None
    return value or None


def is_missing_api_key_error(exc: BaseException) -> bool:
    """True when provider routing failed because no key is configured."""
    return isinstance(exc, ValueError) and 'No API key found' in str(exc)


def client_rejected_missing_key(exc: BaseException) -> bool:
    """True when a client cannot be built because no key is configured.

    The provider router raises ``ValueError``. The legacy ModelScope and
    OpenAI constructors reach ``openai.OpenAI`` with an empty key, which
    raises ``OpenAIError`` instead.
    """
    if is_missing_api_key_error(exc):
        return True
    return type(exc).__name__ == 'OpenAIError' and 'api_key' in str(exc).lower()


def missing_api_key_error(config) -> ValueError:
    """The error a turn raises when the live client was dropped for no key."""
    from omegaconf import OmegaConf
    service = str(OmegaConf.select(config, 'llm.service', default='') or '')
    if not service:
        return ValueError(
            'No API key found for provider. Set config.llm.api_key.')
    return ValueError(
        f'No API key found for provider "{service}". '
        f'Set config.llm.{service}_api_key.')


_PROVIDER_IN_MISSING_KEY = re.compile(r'provider "([^"]+)"')

#: Shown when a sentence parked for lack of a client is sent after a key exists.
PENDING_TURN_RESUME = '继续发送未完成的消息。'


def missing_api_key_setup_text(exc: BaseException, service: str = '') -> str:
    """One command for the provider that is missing a key.

    ``service`` is the live ``llm.service``. The exception text is only a
    fallback when that name is not on the config yet.
    """
    name = (service or '').strip()
    if not name:
        match = _PROVIDER_IN_MISSING_KEY.search(str(exc))
        name = match.group(1) if match else ''
    if not name:
        return '还没有密钥。\n\n  /model provider key <provider> <密钥>'
    return f'还没有 {name} 的密钥。\n\n  /model provider key {name} <密钥>'


class CredentialResolver:

    @staticmethod
    def resolve_api_key(spec: ProviderSpec,
                        config: DictConfig) -> Optional[str]:
        value = _cfg_get(config, f'{spec.name}_api_key')
        if value:
            return value
        value = _cfg_get(config, 'api_key')
        if value:
            return value
        for env_var in spec.api_key_env:
            value = os.environ.get(env_var)
            if value:
                return value
        return None

    @staticmethod
    def resolve_base_url(spec: ProviderSpec, config: DictConfig) -> str:
        value = _cfg_get(config, f'{spec.name}_base_url')
        if value:
            return value
        value = _cfg_get(config, 'base_url')
        if value:
            return value
        for env_var in spec.base_url_env:
            value = os.environ.get(env_var)
            if value:
                return value
        return spec.default_base_url
