"""ToolOutputPruner — truncates old tool outputs to save context tokens.

Migrated from ``ContextCompressor.prune_tool_outputs``.  Unlike the old
implementation this strategy works on dict messages and never mutates the
original SessionLog data.

When pruning actually occurs, the strategy returns compaction metadata so
that the assembler can persist the pruned view and record a compaction
event in the SessionLog.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from ms_agent.llm import multimodal, token_budget
from ms_agent.utils.logger import get_logger

logger = get_logger()


def _estimate_tokens(text: str) -> int:
    return token_budget.estimate_text_tokens(text)


def _estimate_message_tokens(msg: Dict[str, Any]) -> int:
    return token_budget.estimate_message_tokens(msg)


def _estimate_total_tokens(messages: List[Dict[str, Any]],
                           tool_tokens: int = 0) -> int:
    return token_budget.estimate_total_tokens(messages, tool_tokens)


def invalidate_usage(messages):
    """Keep billing evidence, but discard usage anchors for a changed window."""
    for msg in messages:
        msg['_usage_invalidated'] = True


def compression_threshold(config):
    context = config.get('context_limit', 128000)
    threshold = (
        context - config['reserved_buffer']
        if config.get('reserved_buffer') is not None else int(context * 0.85))
    return min(
        config.get('input_limit', context),
        config.get('compression_threshold', threshold))


def protected_indices(messages):
    """Protect instructions/media/latest user and the last atomic tool exchange."""
    protected = {
        i
        for i, m in enumerate(messages) if m.get('role') == 'system'
        or m.get('attachments') or m.get('hook_attachments')
        or multimodal.has_image_blocks(m.get('content'))
    }
    users = [i for i, m in enumerate(messages) if m.get('role') == 'user']
    if users:
        protected.add(users[-1])
    if messages:
        protected.add(len(messages) - 1)
    # An assistant tool call and all consecutive results form one atomic group.
    for i, msg in enumerate(messages):
        if not msg.get('tool_calls'):
            continue
        group = {i}
        j = i + 1
        while j < len(messages) and messages[j].get('role') == 'tool':
            group.add(j)
            j += 1
        if group & protected:
            protected.update(group)
    return protected


class ToolOutputPruner:
    """Truncate old tool outputs that fall outside the protection window.

    Configuration keys (in ``config`` dict):
    - ``prune_protect``:  token budget to protect from the end (default 40000)
    - ``context_limit``:  max context tokens (default 128000)
    - ``reserved_buffer``: buffer before triggering (default 20000)
    """

    name = 'tool_output_pruner'

    def apply(
        self,
        visible: List[Dict[str, Any]],
        all_msgs: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        protect = config.get('prune_protect', 40000)
        tokens_before = _estimate_total_tokens(visible,
                                               config.get('tool_tokens', 0))
        if tokens_before < compression_threshold(config):
            return visible, None

        protected = protected_indices(visible)
        total_tool_tokens = 0
        pruned_count = 0
        replacement = '[Output truncated to save context]'
        for idx in range(len(visible) - 1, -1, -1):
            msg = visible[idx]
            if msg.get('role') != 'tool' or not msg.get('content'):
                continue
            content = msg['content']
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            tokens = _estimate_tokens(content)
            total_tool_tokens += tokens
            if (idx not in protected and total_tool_tokens > protect
                    and tokens > _estimate_tokens(replacement)):
                visible[idx] = {**msg, 'content': replacement}
                pruned_count += 1

        if pruned_count == 0:
            return visible, None

        invalidate_usage(visible)
        tokens_after = _estimate_total_tokens(visible,
                                              config.get('tool_tokens', 0))
        logger.info(f'[tool_pruner] Pruned {pruned_count} tool outputs '
                    f'({tokens_before} -> {tokens_after} tokens)')

        return visible, {
            'pruned_count': pruned_count,
            'tokens_before': tokens_before,
            'tokens_after': tokens_after,
        }
