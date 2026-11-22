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

from ms_agent.llm import multimodal
from ms_agent.utils.logger import get_logger

logger = get_logger()


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    # Conservative for CJK and other non-ASCII text, rather than /4 everywhere.
    non_ascii = sum(ord(c) > 127 for c in text)
    return (len(text) - non_ascii + 3) // 4 + non_ascii


def _estimate_message_tokens(msg: Dict[str, Any]) -> int:
    """Heuristic token count from message body (no API usage fields).

    Structured content is walked block-by-block, and an image block is charged a
    flat per-image cost instead of having its payload measured as text. The
    providers bill images by pixel dimensions (Anthropic ``⌈w/28⌉ × ⌈h/28⌉``;
    DashScope returns the real figure as ``prompt_tokens_details.image_tokens``),
    which has nothing to do with how long the base64 happens to be.

    Measured on DashScope with a 900x320 PNG: 282 real image tokens versus 7,293
    from counting base64 characters — a 26x over-count on a 22 KB image. A 2 MiB
    PNG estimates at ~699k tokens against a ~108k usable budget, which does not
    merely mis-trigger compaction once: the offending message is the last visible
    one, so the compactor re-appends it, the estimate never drops, and every
    subsequent round pays for another summary LLM call.
    """
    total = 4 + len(msg.get('attachments')
                    or []) * multimodal.IMAGE_TOKEN_ESTIMATE
    content = msg.get('content', '')
    if content:
        total += multimodal.estimate_content_tokens(content, _estimate_tokens)
    tool_calls = msg.get('tool_calls')
    if tool_calls:
        total += _estimate_tokens(json.dumps(tool_calls))
    rc = msg.get('reasoning_content', '')
    if rc:
        total += _estimate_tokens(rc)
    return total


def _estimate_total_tokens(messages: List[Dict[str, Any]],
                           tool_tokens: int = 0) -> int:
    """Estimate total tokens, preferring real API usage data when available.

    ``prompt_tokens`` on an assistant message already accounts for all
    preceding context in that API call, so we use it as a base and only
    add a heuristic for messages appended *after* that turn.
    """
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get('role') != 'assistant' or msg.get('_usage_invalidated'):
            continue
        records = msg.get('usage_records') or []
        # A continued answer's summed input is billing usage, not context size.
        usage = records[-1]['usage'] if records else msg
        pt = int(usage.get('prompt_tokens', 0) or 0)
        ct = int(usage.get('completion_tokens', 0) or 0)
        if pt or ct:
            base = pt + ct
            tail = sum(_estimate_message_tokens(m) for m in messages[i + 1:])
            # A replaced system prompt (or changed media) before this anchor
            # can exceed the previous call even without any appended messages.
            return max(
                base + tail, tool_tokens
                + sum(_estimate_message_tokens(m) for m in messages))

    return tool_tokens + sum(_estimate_message_tokens(m) for m in messages)


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
