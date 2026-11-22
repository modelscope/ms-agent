# Copyright (c) ModelScope Contributors. All rights reserved.
"""Shared, offline context budgets for SDK agents and interface previews."""
from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace


def _get(obj, key, default=None):
    if isinstance(obj, Mapping) or hasattr(obj, 'get'):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _positive(value):
    try:
        return int(
            value) if not isinstance(value, bool) and int(value) > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def effective_generation_config(config):
    """Include native output overrides when budgeting the eventual request.

    The HTTP SDK merges extra_body over the generated JSON body. Keep the
    original configuration intact; other native fields belong to transports.
    """
    generation = dict(_get(config, 'generation_config', {}) or {})
    extra = _get(generation, 'extra_body', {}) or {}
    for key in ('max_tokens', 'max_completion_tokens', 'max_output_tokens'):
        if key in extra:
            generation[key] = extra[key]
    return generation


def resolve_model_metadata(config):
    """Resolve offline metadata using the router's identity and credential rules."""
    from .credentials import CredentialResolver
    from .spec import TRANSPORT_OPENAI_COMPAT, ProviderSpec, get_registry

    llm = _get(config, 'llm', {}) or {}
    service = _get(llm, 'service')
    model = _get(llm, 'model', '')
    registry = get_registry()
    spec = registry.get(service)
    if spec is None and not service:
        spec = registry.resolve_by_model(model)
    if spec is None:
        spec = ProviderSpec(
            name=service or 'custom',
            display_name=service or 'Custom',
            transport=TRANSPORT_OPENAI_COMPAT,
            api_key_env=['OPENAI_API_KEY'],
            base_url_env=['OPENAI_BASE_URL'])
    base_url = CredentialResolver.resolve_base_url(spec,
                                                   SimpleNamespace(llm=llm))
    try:
        from .model_catalog import get_model
        return get_model(spec.name, model, base_url=base_url)
    except (ImportError, OSError, ValueError, TypeError, KeyError):
        return None


def _output_token_parameter(config):
    """Parameter used when the agent supplies its bounded output default."""
    generation = effective_generation_config(config)
    if _get(generation, 'use_responses_api'):
        return 'max_output_tokens'
    if _get(generation, 'max_completion_tokens'):
        return 'max_completion_tokens'
    if _get(generation, 'max_tokens'):
        return 'max_tokens'
    llm = _get(config, 'llm', {}) or {}
    if str(_get(llm, 'protocol', '')).lower() != 'anthropic':
        metadata = resolve_model_metadata(config)
        if _get(metadata, 'catalog_provider') == 'openai':
            # OpenAI reasoning models reject deprecated max_tokens. Other
            # compatible providers still generally use the legacy parameter.
            return 'max_completion_tokens'
    return 'max_tokens'


def resolve_context_budget(config, *, metadata=None) -> dict:
    """Return the effective context, input and compression budgets in tokens.

    ``metadata`` can be a raw models.dev model entry. ``input_limit`` is the
    hard input ceiling after reserving this request's output; compression starts
    at ``compression_threshold`` (inclusive). Legacy compaction/session limits
    keep their precedence but can only tighten model and llm.context_limit caps.
    Disabling compaction does not disable budget resolution or hard limits.
    """
    metadata = resolve_model_metadata(config) if metadata is None else metadata
    limits = _get(metadata, 'limit', {}) or {}
    llm = _get(config, 'llm', {}) or {}
    session = _get(config, 'session_log', {}) or {}
    compaction = _get(config, 'compaction', {}) or {}
    generation = effective_generation_config(config)
    model_limit = _positive(_get(limits, 'context'))
    manual = _positive(_get(llm, 'context_limit'))
    legacy = _positive(_get(compaction, 'context_limit')) or _positive(
        _get(session, 'context_limit'))
    caps = [v for v in (model_limit, manual, legacy) if v is not None]
    context = min(caps) if caps else 128000
    model_output = _positive(_get(limits, 'output'))
    if _get(generation, 'use_responses_api'):
        output = _positive(_get(generation, 'max_output_tokens'))
    else:
        # Compatible endpoints differ when both aliases are present. Reserve
        # the larger value rather than claiming room the wire request may use.
        output = max((_positive(_get(generation, key)) or 0
                      for key in ('max_completion_tokens', 'max_tokens')),
                     default=0) or None
    if output is None:
        output = min(8192, model_output or 8192, max(1, context // 8))
    # A too-large explicit request leaves no input room, rather than quietly
    # claiming it fits by shrinking the reserve without changing the request.
    input_limit = max(
        0, min(_positive(_get(limits, 'input')) or context, context - output))
    ratio = _get(compaction, 'compression_ratio',
                 _get(session, 'compression_ratio', 0.85))
    try:
        ratio = float(ratio)
        if not 0 < ratio <= 1:
            ratio = 0.85
    except (TypeError, ValueError):
        ratio = 0.85
    reserved = _get(compaction, 'reserved_buffer',
                    _get(session, 'reserved_buffer'))
    threshold = int(context * ratio)
    if reserved is not None:
        try:
            threshold = max(0, context - max(0, int(reserved)))
        except (TypeError, ValueError):
            pass
    threshold = min(input_limit, threshold)
    return dict(
        context_limit=context,
        model_context_limit=model_limit,
        input_limit=input_limit,
        output_reserve=output,
        compression_threshold=threshold,
        compression_ratio=threshold / context)
