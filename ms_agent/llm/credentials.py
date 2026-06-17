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
from typing import Optional

from omegaconf import DictConfig

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
