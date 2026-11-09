# Copyright (c) ModelScope Contributors. All rights reserved.
"""Per-response token usage and snapshot-based USD estimates, not provider invoices."""
from __future__ import annotations

import contextvars
import math
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

from .context_budget import _get, resolve_model_metadata

USAGE_FIELDS = ('prompt_tokens', 'completion_tokens', 'cached_tokens',
                'cache_creation_input_tokens', 'reasoning_tokens')

_usage_scope = contextvars.ContextVar('ms_agent_usage_scope', default=None)


@contextmanager
def usage_scope(sink=None, config=None, operation=None):
    """Executor propagation carries this session's journal, never credentials."""
    parent = _usage_scope.get() or {}
    token = _usage_scope.set(
        dict(
            sink=sink or parent.get('sink'),
            config=config if config is not None else parent.get('config'),
            operation=operation or parent.get('operation', 'conversation')))
    try:
        yield
    finally:
        _usage_scope.reset(token)


def _raw_usage(usage):
    if usage is None:
        return None
    if hasattr(usage, 'model_dump'):
        usage = usage.model_dump(exclude_none=True)
    elif not isinstance(usage, dict):
        usage = vars(usage)
    if '_raw' in usage:
        return deepcopy(usage['_raw'])
    # Only the usage object is retained, never a request, response body or key.
    return {
        k: (_raw_usage(v)
            if isinstance(v, dict) or hasattr(v, 'model_dump') else v)
        for k, v in usage.items() if v is not None and not k.startswith('_')
    }


def _enrich(record, metadata):
    cost = estimate_cost(metadata, record['usage'])
    reasons = []
    if not record.get('usage_available', True):
        reasons.append('usage_unavailable')
    if record.get('usage_status') == 'partial':
        reasons.append('partial_response')
    raw = record.get('raw_usage') or {}
    creation = raw.get('cache_creation') or {}
    if record['usage'].get('cache_creation_input_tokens'):
        # models.dev's single cache_write rate cannot distinguish mixed TTLs.
        if creation.get('ephemeral_1h_input_tokens') or not creation:
            reasons.append('cache_write_ttl_not_priced')
    if cost['total'] is None:
        reasons.append('price_unavailable')
    cost['known_total'] = sum(v for v in cost['breakdown'].values()
                              if v is not None)
    if reasons:
        cost['total'] = None
    cost['status'] = ('complete' if not reasons else 'partial' if record.get(
        'usage_available', True) and metadata else 'unknown')
    cost['incomplete_reasons'] = reasons
    record['cost'] = cost
    record['priced'] = True


def _publish(record):
    scope = _usage_scope.get()
    if not scope or not scope['sink']:
        return
    config = scope.get('config')
    if config is not None and not record.get('priced'):
        record['model'] = _get(_get(config, 'llm'), 'model',
                               '') or record['model']
        _enrich(record, resolve_model_metadata(config))
    record['operation'] = scope['operation']
    try:
        scope['sink'](deepcopy(record))
    except Exception as error:
        # Retain the record on the response for normal persistence too.
        record['journal_error'] = type(error).__name__
        from ms_agent.utils.logger import get_logger
        get_logger().warning(
            'Usage journal write failed (%s); response retains usage',
            type(error).__name__)


def _count(value):
    try:
        return max(0, int(value or 0))
    except (ValueError, TypeError, OverflowError):
        return 0


def normalize_usage(usage, *, protocol='openai') -> dict:
    """Normalize SDK objects or raw dicts; input ALWAYS includes cache tokens."""
    prompt = _get(usage, 'prompt_tokens_details', None) or _get(
        usage, 'input_tokens_details', {}) or {}
    completion = _get(usage, 'completion_tokens_details', None) or _get(
        usage, 'output_tokens_details', {}) or {}
    read = _count(
        _get(prompt, 'cached_tokens', None)
        or _get(usage, 'cache_read_input_tokens', None)
        or _get(usage, 'prompt_cache_hit_tokens', None)
        or _get(usage, 'cache_hit_tokens', None)
        or _get(usage, 'cache_hit', None) or _get(usage, 'cached_tokens', 0))
    write = _count(
        _get(prompt, 'cache_creation_input_tokens', None)
        or _get(usage, 'cache_creation_input_tokens', 0))
    inputs = _count(
        _get(usage, 'prompt_tokens', None
             ) if _get(usage, 'prompt_tokens', None
                       ) is not None else _get(usage, 'input_tokens', 0))
    if protocol == 'anthropic':
        inputs += read + write
    outputs = _count(
        _get(usage, 'completion_tokens', None
             ) if _get(usage, 'completion_tokens', None
                       ) is not None else _get(usage, 'output_tokens', 0))
    reasoning = _count(
        _get(completion, 'reasoning_tokens', None)
        or _get(usage, 'reasoning_tokens', 0))
    return dict(
        prompt_tokens=inputs,
        completion_tokens=outputs,
        cached_tokens=read,
        cache_creation_input_tokens=write,
        reasoning_tokens=min(outputs, reasoning))


def _price(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError):
        return None


def estimate_cost(metadata, usage) -> dict:
    """Estimate ONE response using normalized usage, never a continuation sum.

    The highest context tier strictly exceeded prices the entire request (not
    progressive brackets). Missing required prices make the total unknown;
    explicit zero is a valid price. Reasoning is a subset of completion.
    """
    usage = normalize_usage(usage)
    raw = _get(metadata, 'cost', {}) or {}
    prices = {
        k: _price(_get(raw, k))
        for k in ('input', 'output', 'cache_read', 'cache_write', 'reasoning')
    }
    tiers = []
    for entry in _get(raw, 'tiers', []) or []:
        tier = _get(entry, 'tier', {}) or {}
        if _get(tier, 'type') == 'context':
            size = _count(_get(tier, 'size'))
            tiers.append((size, entry))
    # The legacy field is a lossy projection of tiers, not an extra 200K bracket.
    over = _get(raw, 'context_over_200k')
    if not tiers and over:
        tiers.append((200000, over))
    chosen = None
    for size, entry in sorted(tiers, key=lambda item: item[0]):
        if usage['prompt_tokens'] > size:
            # Missing fields in a tier are unknown, NOT the cheaper base price.
            prices = {k: _price(_get(entry, k)) for k in prices}
            chosen = size
    read = usage['cached_tokens']
    write = usage['cache_creation_input_tokens']
    reasoning = usage['reasoning_tokens'] if prices[
        'reasoning'] is not None else 0
    counts = dict(
        input=max(0, usage['prompt_tokens'] - read - write),
        output=usage['completion_tokens'] - reasoning,
        cache_read=read,
        cache_write=write,
        reasoning=reasoning)
    costs = {
        k: (n * prices[k] / 1_000_000 if prices[k] is not None else
            (0.0 if n == 0 else None))
        for k, n in counts.items()
    }
    # Unknown base pricing remains unknown even for a zero-usage response.
    unknown = (
        any(v is None for v in costs.values()) or prices['input'] is None
        or prices['output'] is None)
    return dict(
        total=None if unknown else sum(costs.values()),
        currency='USD',
        estimated=True,
        price=prices,
        breakdown=costs,
        context_tier=chosen,
        source='https://models.dev/api.json' if metadata else None,
        provider=_get(metadata, 'catalog_provider'),
        revision=_get(metadata, 'catalog_revision'))


def response_usage(usage,
                   *,
                   protocol='openai',
                   model='',
                   response_id='',
                   record_id=None,
                   complete=True):
    """Message kwargs for a single API response (also used by static adapters)."""
    normalized = normalize_usage(usage, protocol=protocol)
    record = dict(
        record_id=record_id or uuid4().hex,
        response_id=response_id,
        model=model,
        response_model=model,
        usage=normalized,
        usage_available=usage is not None,
        protocol=protocol,
        raw_usage=_raw_usage(usage),
        usage_status=('unknown' if usage is None else
                      'complete' if complete else 'partial'),
        cost=estimate_cost(None, normalized))
    _publish(record)
    return {**normalized, 'usage_records': [record]}


def update_openai_usage(snapshot, usage):
    """Coalesce cumulative OpenAI usage, including usage-only trailer chunks."""
    if usage is None:
        return snapshot
    current = normalize_usage(usage)
    merged = {
        key: max((snapshot or {}).get(key, 0), current[key])
        for key in USAGE_FIELDS
    }
    merged['_raw'] = {
        **((snapshot or {}).get('_raw') or {}),
        **(_raw_usage(usage) or {})
    }
    return merged


def update_usage_snapshot(snapshot, usage):
    """Merge partial cumulative Anthropic usage events without adding counts."""
    for key in ('input_tokens', 'output_tokens', 'cache_read_input_tokens',
                'cache_creation_input_tokens', 'cache_creation'):
        value = _get(usage, key)
        if value is not None:
            snapshot[key] = value
    return snapshot


def set_response_usage(message,
                       usage,
                       *,
                       protocol='openai',
                       model='',
                       complete=True):
    """Set final cumulative usage once; do not add stream snapshots together."""
    identity = getattr(message, '_usage_record_id', None) or uuid4().hex
    message._usage_record_id = identity
    values = response_usage(
        usage,
        protocol=protocol,
        model=model,
        response_id=message.id,
        record_id=identity,
        complete=complete)
    for key, value in values.items():
        setattr(message, key, value)
    return message


def merge_usage(target, incoming):
    """Merge independent responses, deduplicating cumulative stream records."""
    records = {r['record_id']: r for r in target.usage_records}
    records.update({r['record_id']: r for r in incoming.usage_records})
    if records:
        target.usage_records = deepcopy(list(records.values()))
        for key in USAGE_FIELDS:
            setattr(target, key,
                    sum(r['usage'].get(key, 0) for r in records.values()))
        target.api_calls = len(records)
    else:
        for key in USAGE_FIELDS:
            setattr(target, key, getattr(target, key) + getattr(incoming, key))


def price_usage_records(message, config, *, metadata=None):
    """Enrich captured responses before persistence; never reprice restored data."""
    if getattr(message, '_usage_restored', False):
        return
    if not message.usage_records:
        # Legacy/custom engines may not expose request boundaries. Do not price
        # a continued total at one tier; leave it unknown instead.
        observed = {key: getattr(message, key, 0) for key in USAGE_FIELDS}
        values = response_usage(
            observed if any(observed.values()) else None,
            model=_get(_get(config, 'llm'), 'model', ''),
            response_id=message.id)
        message.usage_records = values['usage_records']
        if message.api_calls > 1:
            message.usage_records[0]['usage_available'] = False
    metadata = resolve_model_metadata(config) if metadata is None else metadata
    for record in message.usage_records:
        if record.get('priced'):
            continue
        record['model'] = _get(_get(config, 'llm'), 'model',
                               '') or record['model']
        _enrich(record, metadata)
        _publish(record)
