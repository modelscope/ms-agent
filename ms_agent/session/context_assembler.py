"""ContextAssembler — builds the LLM-visible message window from a SessionLog.

Replaces the old destructive ``ContextCompressor``: instead of mutating the
canonical message list, it *reads* from the append-only SessionLog and
*produces* a view through a pipeline of pluggable ``ViewStrategy`` objects.

When a strategy compacts the visible window (e.g. LLM-based summary or
tool-output pruning), the assembler **persists the compacted view** back
into the SessionLog as a new segment and advances ``last_consolidated``
(a seq value) to point at it.  This guarantees that compaction results
survive process restarts — the original messages remain intact in earlier
positions of the JSONL file.

Multiple strategies may fire in a single ``assemble()`` call.  Each one
that returns compaction metadata triggers its own persist-and-advance
cycle, so the JSONL contains a complete audit trail of every compaction
step.

Usage::

    assembler = ContextAssembler(session_log, [ToolOutputPruner(), SummaryCompactor(llm)])
    messages = assembler.assemble()   # -> List[Message]
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from ms_agent.llm.utils import Message

from .session_log import SessionLog


# ------------------------------------------------------------------
# ViewStrategy Protocol
# ------------------------------------------------------------------

@runtime_checkable
class ViewStrategy(Protocol):
    """A non-destructive strategy that transforms the visible message window.

    ``apply()`` receives:
    - *visible*: messages from ``last_consolidated`` onward (the current window)
    - *all_msgs*: the full session history (read-only context)
    - *config*: strategy-specific configuration

    Returns:
    - the (possibly shortened) visible list
    - an optional metadata dict; if non-None the assembler records a
      compaction event in the SessionLog and persists the new view.
      Expected keys (all optional):
        tokens_before, tokens_after, summary, pruned_count
    """

    name: str

    def apply(
        self,
        visible: List[Dict[str, Any]],
        all_msgs: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        ...


# ------------------------------------------------------------------
# ContextAssembler
# ------------------------------------------------------------------

class ContextAssembler:
    """Builds the LLM-visible message list from a SessionLog.

    The assembler applies each ``ViewStrategy`` in order.  If a strategy
    produces compaction metadata the event is recorded in the log,
    the compacted view is **appended** as a new segment, and
    ``last_consolidated`` is advanced to the first seq of that segment.
    The original messages are never deleted or overwritten.
    """

    def __init__(
        self,
        session_log: SessionLog,
        strategies: List[ViewStrategy] | None = None,
        config: Dict[str, Any] | None = None,
        memory_flush_callback: Optional[Callable] = None,
    ) -> None:
        self.session_log = session_log
        self.strategies: List[ViewStrategy] = strategies or []
        self.config: Dict[str, Any] = config or {}
        self._memory_flush_callback = memory_flush_callback

    def assemble(self) -> List[Message]:
        """Build the LLM-visible message list.

        1. Read all messages from the SessionLog.
        2. Slice the visible window (seq >= last_consolidated).
        3. Run each strategy; if compaction occurs:
           a. Capture the boundary (first/last seq of the old window).
           b. Flush discarded messages to long-term memory.
           c. Record a compaction event with seq-based boundaries.
           d. Persist the compacted view as new records.
           e. Advance ``last_consolidated`` to the first new seq.
           f. Refresh ``all_msgs`` and ``visible`` from the persisted state.
        4. Convert dicts to ``Message`` objects.
        """
        all_msgs = self.session_log.get_all_messages()
        lc_seq = self.session_log.last_consolidated
        visible = _slice_visible(all_msgs, lc_seq)

        for strategy in self.strategies:
            window_last_seq = (
                visible[-1].get("seq", 0) if visible else lc_seq
            )

            visible, meta = strategy.apply(visible, all_msgs, self.config)

            if meta is not None:
                boundary_before = lc_seq
                boundary_after = window_last_seq

                if self._memory_flush_callback is not None:
                    try:
                        discarded = [
                            m for m in all_msgs
                            if boundary_before <= m.get("seq", 0) <= boundary_after
                        ]
                        self._memory_flush_callback(discarded)
                    except Exception:
                        pass

                event: Dict[str, Any] = {
                    "strategy": strategy.name,
                    "boundary_before": boundary_before,
                    "boundary_after": boundary_after,
                    "tokens_before": meta.get("tokens_before", 0),
                    "tokens_after": meta.get("tokens_after", 0),
                }
                if meta.get("summary"):
                    event["summary_preview"] = meta["summary"][:200]
                if meta.get("pruned_count") is not None:
                    event["pruned_count"] = meta["pruned_count"]
                self.session_log.record_compaction(event)

                first_new_seq = None
                for msg in visible:
                    clean = {
                        k: v for k, v in msg.items()
                        if k not in ("seq", "timestamp")
                    }
                    s = self.session_log.append(
                        {**clean, "_source": "compaction"}
                    )
                    if first_new_seq is None:
                        first_new_seq = s

                if first_new_seq is not None:
                    self.session_log.last_consolidated = first_new_seq
                    lc_seq = first_new_seq

                all_msgs = self.session_log.get_all_messages()
                visible = _slice_visible(all_msgs, lc_seq)

        return _dicts_to_messages(visible)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _slice_visible(
    all_msgs: List[Dict[str, Any]], lc_seq: int
) -> List[Dict[str, Any]]:
    """Return a deep-copied visible window (seq >= *lc_seq*)."""
    for i, m in enumerate(all_msgs):
        if m.get("seq", 0) >= lc_seq:
            return [deepcopy(m) for m in all_msgs[i:]]
    return []


def _dicts_to_messages(dicts: List[Dict[str, Any]]) -> List[Message]:
    result: List[Message] = []
    for d in dicts:
        if isinstance(d, Message):
            result.append(d)
        elif isinstance(d, dict):
            result.append(Message(
                role=d.get("role", "user"),
                content=d.get("content", ""),
                tool_calls=d.get("tool_calls"),
                tool_call_id=d.get("tool_call_id"),
                name=d.get("name"),
            ))
        else:
            result.append(Message(role="user", content=str(d)))
    return result
