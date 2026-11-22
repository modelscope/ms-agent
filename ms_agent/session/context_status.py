# Copyright (c) ModelScope Contributors. All rights reserved.
"""Read-only context accounting shared by SDK interfaces."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .strategies.tool_pruner import (_estimate_message_tokens,
                                     _estimate_tokens, _estimate_total_tokens)


def context_snapshot(messages,
                     budget,
                     *,
                     tools=None,
                     model='',
                     provider='',
                     catalog_revision=None,
                     signature='',
                     window_start=0,
                     tail_seq=-1):
    """Estimates are additive; provider-reported residuals stay unattributed.

    Output reservation is a limit, not consumed input. No provider tokenizer
    or unsupported skill/memory attribution is claimed by this API.
    """
    rows = [m.to_dict() if hasattr(m, 'to_dict') else m for m in messages]
    tool_tokens = (
        _estimate_tokens(json.dumps(tools, ensure_ascii=False))
        if tools else budget.get('tool_tokens', 0))
    buckets = {
        'system':
        sum(
            _estimate_message_tokens(m) for m in rows
            if m.get('role') == 'system'),
        'tools':
        tool_tokens,
        'messages':
        sum(
            _estimate_message_tokens(m) for m in rows
            if m.get('role') != 'system'),
    }
    # Runtime flags aren't dataclass fields and must not disappear in to_dict.
    for source, row in zip(messages, rows):
        if getattr(source, '_usage_invalidated', False):
            row['_usage_invalidated'] = True
    total = _estimate_total_tokens(rows, tool_tokens)
    residual = total - sum(buckets.values())
    if residual:
        buckets['unattributed'] = residual
    context = budget.get('context_limit', 0)
    return dict(
        estimated=True,
        input_tokens=total,
        buckets=buckets,
        context_limit=context,
        input_limit=budget.get('input_limit'),
        output_reserve=budget.get('output_reserve', 0),
        compression_threshold=budget.get('compression_threshold'),
        ratio=total / context if context else None,
        model=model,
        provider=provider,
        catalog_revision=catalog_revision,
        signature=signature,
        window_start=window_start,
        tail_seq=tail_seq,
        measured_at=datetime.now(timezone.utc).isoformat())
