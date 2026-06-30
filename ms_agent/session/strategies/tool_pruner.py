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

from ms_agent.utils.logger import get_logger

logger = get_logger()


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return len(text) // 4


def _estimate_message_tokens(msg: Dict[str, Any]) -> int:
    """Heuristic token count from message body (no API usage fields)."""
    total = 0
    content = msg.get("content", "")
    if content:
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        total += _estimate_tokens(content)
    tool_calls = msg.get("tool_calls")
    if tool_calls:
        total += _estimate_tokens(json.dumps(tool_calls))
    rc = msg.get("reasoning_content", "")
    if rc:
        total += _estimate_tokens(rc)
    return total


def _estimate_total_tokens(messages: List[Dict[str, Any]]) -> int:
    """Estimate total tokens, preferring real API usage data when available.

    ``prompt_tokens`` on an assistant message already accounts for all
    preceding context in that API call, so we use it as a base and only
    add a heuristic for messages appended *after* that turn.
    """
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") != "assistant":
            continue
        pt = int(msg.get("prompt_tokens", 0) or 0)
        ct = int(msg.get("completion_tokens", 0) or 0)
        if pt or ct:
            base = pt + ct
            tail = sum(_estimate_message_tokens(m) for m in messages[i + 1:])
            return base + tail

    return sum(_estimate_message_tokens(m) for m in messages)


class ToolOutputPruner:
    """Truncate old tool outputs that fall outside the protection window.

    Configuration keys (in ``config`` dict):
    - ``prune_protect``:  token budget to protect from the end (default 40000)
    - ``context_limit``:  max context tokens (default 128000)
    - ``reserved_buffer``: buffer before triggering (default 20000)
    """

    name = "tool_output_pruner"

    def apply(
        self,
        visible: List[Dict[str, Any]],
        all_msgs: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        context_limit = config.get("context_limit", 128000)
        reserved = config.get("reserved_buffer", 20000)
        protect = config.get("prune_protect", 40000)

        tokens_before = _estimate_total_tokens(visible)
        usable = context_limit - reserved
        if tokens_before < usable:
            return visible, None

        total_tool_tokens = 0
        pruned_count = 0
        for idx in range(len(visible) - 1, -1, -1):
            msg = visible[idx]
            if msg.get("role") != "tool" or not msg.get("content"):
                continue
            content = msg["content"]
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            tokens = _estimate_tokens(content)
            total_tool_tokens += tokens
            if total_tool_tokens > protect:
                visible[idx] = {**msg, "content": "[Output truncated to save context]"}
                pruned_count += 1

        if pruned_count == 0:
            return visible, None

        tokens_after = _estimate_total_tokens(visible)
        logger.info(
            f"[tool_pruner] Pruned {pruned_count} tool outputs "
            f"({tokens_before} -> {tokens_after} tokens)"
        )

        return visible, {
            "pruned_count": pruned_count,
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
        }
