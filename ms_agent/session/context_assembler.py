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

import asyncio
import hashlib
import inspect
import json
import threading
from copy import deepcopy
from typing import (Any, Callable, Dict, List, Optional, Protocol, Tuple,
                    runtime_checkable)

from ms_agent.llm.io import run_in_llm_executor
from ms_agent.llm.utils import Message
from .session_log import SessionLog
from .strategies.tool_pruner import (_estimate_message_tokens,
                                     _estimate_tokens, _estimate_total_tokens,
                                     invalidate_usage)


class ContextBudgetExceeded(ValueError):
    """The protected/latest input cannot fit; retrying unchanged cannot help."""

    # Reuse the SDK's existing permanent-request-error retry policy.
    status_code = 400


def check_context_budget(messages, config, tools=None):
    import json

    limit = config.get('input_limit')
    tool_tokens = config.get('tool_tokens', 0)
    if tools:
        tool_tokens = max(
            tool_tokens,
            _estimate_tokens(json.dumps(tools, ensure_ascii=False)))
    tokens = _estimate_total_tokens(messages, tool_tokens)
    if limit is not None and tokens > limit:
        raise ContextBudgetExceeded(
            f'Context budget exceeded: estimated input {tokens} > {limit} tokens '
            f'(context={config.get("context_limit")}, '
            f'output reserve={config.get("output_reserve")}). '
            'Shorten the latest message/attachments or choose a larger context. '
            'Original session records were retained.')


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

        Ordinary flush errors are recorded for retry without blocking a valid
        window. Async flush callbacks require ``assemble_async()``.
        """
        all_msgs, lc_seq, visible = self._prepare_window()
        for strategy in self.strategies:
            window_last_seq = visible[-1].get('seq', 0) if visible else lc_seq
            visible, meta = strategy.apply(visible, all_msgs, self.config)
            usage_records = self._take_usage(strategy)
            if meta is not None:
                if inspect.iscoroutinefunction(self._memory_flush_callback):
                    raise TypeError(
                        'Async memory flush requires assemble_async()')
                flushed = self._flush_memory(all_msgs, lc_seq, window_last_seq)
                if inspect.isawaitable(flushed):
                    # Close only the unstarted coroutine we just obtained, never
                    # a model iterator being consumed in another thread.
                    if inspect.iscoroutine(flushed):
                        flushed.close()
                    raise TypeError(
                        'Async memory flush requires assemble_async()')
            all_msgs, lc_seq, visible = self._commit(strategy, visible, meta,
                                                     usage_records, all_msgs,
                                                     lc_seq, window_last_seq)

        check_context_budget(visible, self.config)
        return _dicts_to_messages(visible)

    async def assemble_async(self) -> List[Message]:
        """Assemble without blocking the event loop on strategy/model I/O.

        Only ``strategy.apply`` runs in the model executor. Flush is an awaited
        barrier; log commits run on the caller's thread after a valid summary
        and an attempted flush (ordinary memory failures remain retryable).
        On cancellation, interrupt and drain the worker before re-raising, so
        neither late results nor usage can leak into a subsequent assembly.
        Like the synchronous API, each assembler has a single session owner.
        """
        all_msgs, lc_seq, visible = self._prepare_window()
        for strategy in self.strategies:
            window_last_seq = visible[-1].get('seq', 0) if visible else lc_seq
            visible, meta = await self._apply_async(strategy, visible,
                                                    all_msgs)
            usage_records = self._take_usage(strategy)
            if meta is not None:
                flushed = self._flush_memory(
                    all_msgs, lc_seq, window_last_seq, async_mode=True)
                if inspect.isawaitable(flushed):
                    await flushed
            all_msgs, lc_seq, visible = self._commit(strategy, visible, meta,
                                                     usage_records, all_msgs,
                                                     lc_seq, window_last_seq)

        check_context_budget(visible, self.config)
        return _dicts_to_messages(visible)

    async def _apply_async(self, strategy, visible, all_msgs):
        llm = getattr(strategy, 'llm', None)
        abandoned = threading.Event()
        config = deepcopy(self.config)

        def apply():
            # Cancellation may arrive while queued in the bounded executor.
            if not abandoned.is_set():
                return strategy.apply(visible, all_msgs, config)

        worker = asyncio.create_task(run_in_llm_executor(apply))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            abandoned.set()
            interrupt = getattr(llm, 'interrupt', None)
            if callable(interrupt):
                try:
                    interrupt()
                except Exception:
                    pass  # Preserve cancellation even if transport abort fails.
            # Python cannot kill a running thread. Keep ownership until apply
            # unwinds (transport interrupt, or its configured request timeout).
            # Repeated Stop requests must not detach the worker during cleanup.
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except (asyncio.CancelledError, Exception):
                    pass
            if not worker.cancelled():
                worker.exception(
                )  # Retrieve a late failure, never its result.
            self._take_usage(strategy)
            raise

    def _prepare_window(self):
        # SessionLog caches its list: never hand that mutable cache to a worker
        # or flush callback, including after a prior strategy's commit.
        all_msgs = deepcopy(self.session_log.get_all_messages())
        lc_seq = self.session_log.last_consolidated
        visible = _slice_visible(all_msgs, lc_seq)
        model = self.config.get('model')
        if model and any(
            (m.get('usage_records') or [{}])[-1].get('model') not in (None, '',
                                                                      model)
                for m in visible):
            invalidate_usage(visible)
        return all_msgs, lc_seq, visible

    @staticmethod
    def _take_usage(strategy):
        records = getattr(strategy, '_usage_records', [])
        if records:
            strategy._usage_records = []
        return records

    def _flush_memory(self,
                      all_msgs,
                      boundary_before,
                      boundary_after,
                      async_mode=False):
        self._memory_outcome = {'status': 'skipped'}
        if self._memory_flush_callback is None:
            return
        prior = self.session_log.get_memory_flushes()
        completed = {
            seq
            for job in prior if job['status'] in ('updated', 'unchanged')
            for seq in job['source_seqs']
        }
        pending = {
            seq
            for job in prior if job['status'] in ('pending', 'failed')
            for seq in job['source_seqs']
        }
        rows = {}
        wanted = set(pending)
        for message in all_msgs:
            if message.get('role') == 'system' or message.get(
                    'context_summary'):
                continue
            seq = message.get('_origin_seq', message['seq'])
            rows.setdefault(seq, message)
            if boundary_before <= message['seq'] <= boundary_after:
                wanted.add(seq)
        sources = sorted((wanted - completed) & rows.keys())
        if not sources:
            self._memory_outcome = {'status': 'unchanged'}
            return
        job = {
            'id':
            hashlib.sha256(json.dumps(sources).encode()).hexdigest()[:24],
            'source_seqs': sources,
            'status': 'pending'
        }
        self.session_log.record_memory_flush(job)

        def finish(status, error=None):
            outcome = {**job, 'status': status}
            if error is not None:
                # Do not persist provider response bodies or credentials.
                outcome['error_type'] = type(error).__name__
            self.session_log.record_memory_flush(outcome)
            self._memory_outcome = {
                k: v
                for k, v in outcome.items() if k != 'source_seqs'
            }

        try:
            result = self._memory_flush_callback(
                [deepcopy(rows[s]) for s in sources])
        except Exception as error:
            finish('failed', error)
            return
        if inspect.isawaitable(result):
            if not async_mode:
                if inspect.iscoroutine(result):
                    result.close()
                raise TypeError('Async memory flush requires assemble_async()')

            async def wait():
                try:
                    status = await result
                except asyncio.CancelledError as error:
                    finish('failed', error)
                    raise
                except Exception as error:
                    finish('failed', error)
                else:
                    finish(
                        status if status in ('updated', 'unchanged',
                                             'skipped') else 'unchanged')

            return wait()
        finish(
            result if result in ('updated', 'unchanged',
                                 'skipped') else 'unchanged')

    def _commit(self, strategy, visible, meta, usage_records, all_msgs, lc_seq,
                window_last_seq):
        """Commit a valid window independently of ordinary extraction failures."""
        budget = {
            k: self.config[k]
            for k in ('context_limit', 'model_context_limit', 'input_limit',
                      'output_reserve', 'compression_threshold',
                      'compression_ratio') if k in self.config
        }
        if meta is None:
            if usage_records:
                self.session_log.record_compaction({
                    'strategy':
                    strategy.name,
                    'status':
                    'retained',
                    'budget':
                    budget,
                    'usage_records':
                    usage_records
                })
            return all_msgs, lc_seq, visible

        event: Dict[str, Any] = {
            'strategy': strategy.name,
            'operation_id': self.config.get('operation_id'),
            'trigger': self.config.get('trigger', 'auto'),
            'boundary_before': lc_seq,
            'boundary_after': window_last_seq,
            'tokens_before': meta.get('tokens_before', 0),
            'tokens_after': meta.get('tokens_after', 0),
            'budget': budget,
            'usage_records': usage_records,
        }
        if meta.get('summary'):
            event['summary_preview'] = meta['summary'][:200]
        if meta.get('pruned_count') is not None:
            event['pruned_count'] = meta['pruned_count']
        event['memory'] = getattr(self, '_memory_outcome',
                                  {'status': 'skipped'})
        window = []
        for msg in visible:
            clean = {
                k: v
                for k, v in msg.items()
                if k not in ('seq', 'timestamp', 'usage_records',
                             'prompt_tokens', 'completion_tokens',
                             'cached_tokens', 'cache_creation_input_tokens',
                             'reasoning_tokens', 'tokens', 'api_calls')
            }
            if 'seq' in msg and not msg.get('context_summary'):
                clean['_origin_seq'] = msg.get('_origin_seq', msg['seq'])
            window.append(clean)
        self.session_log.commit_compaction(window, event)
        return self._prepare_window()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _slice_visible(all_msgs: List[Dict[str, Any]],
                   lc_seq: int) -> List[Dict[str, Any]]:
    """Return a deep-copied visible window (seq >= *lc_seq*)."""
    for i, m in enumerate(all_msgs):
        if m.get('seq', 0) >= lc_seq:
            return [deepcopy(m) for m in all_msgs[i:]]
    return []


# Legacy placeholder: pre-fix logs filled a tool-call-only assistant turn with
# this synthetic string to keep the message non-empty. It is framework filler,
# never model output. New logs no longer write it, but existing session logs on
# disk still carry it — it must be stripped on restore so it never re-enters the
# model context (a fake assistant utterance the model would otherwise imitate).
_LEGACY_TOOLCALL_PLACEHOLDER = 'Let me do a tool calling.'


def _dicts_to_messages(dicts: List[Dict[str, Any]]) -> List[Message]:
    result: List[Message] = []
    for d in dicts:
        if isinstance(d, Message):
            result.append(d)
        elif isinstance(d, dict):
            content = d.get('content', '')
            # Strip the legacy placeholder from OLD logs — but only when the row
            # actually carries tool_calls (the only case it was ever injected),
            # so a genuine reply equal to the literal is left untouched. The
            # blank tool-call turn then serializes to the canonical empty form
            # (OpenAI: content null; Anthropic: tool_use with no text block).
            if content == _LEGACY_TOOLCALL_PLACEHOLDER and d.get('tool_calls'):
                content = ''
            result.append(
                Message(
                    role=d.get('role', 'user'),
                    content=content,
                    tool_calls=d.get('tool_calls'),
                    tool_call_id=d.get('tool_call_id'),
                    name=d.get('name'),
                    # Carry reasoning + its signature back into the assembled
                    # context. OpenAI-compat transports filter these out (not in
                    # their input_msg allowlist), so only the Anthropic transport
                    # replays them — required for its thinking-mode tool follow-ups.
                    reasoning_content=d.get('reasoning_content', '') or '',
                    reasoning_signature=d.get('reasoning_signature', '') or '',
                    # Image refs attached to a user turn. This runs on EVERY
                    # round (the live context is reassembled from the log), so
                    # omitting them here would make images visible on the turn
                    # they were sent and invisible from the next round on.
                    attachments=d.get('attachments') or [],
                    hook_attachments=d.get('hook_attachments') or [],
                    id=d.get('id', ''),
                    _responses_output_items=deepcopy(
                        d.get('_responses_output_items') or []),
                    prompt_tokens=d.get('prompt_tokens', 0),
                    completion_tokens=d.get('completion_tokens', 0),
                    cached_tokens=d.get('cached_tokens', 0),
                    cache_creation_input_tokens=d.get(
                        'cache_creation_input_tokens', 0),
                    reasoning_tokens=d.get('reasoning_tokens', 0),
                    usage_records=deepcopy(d.get('usage_records') or []),
                ))
            if result[-1].hook_attachments:
                from ms_agent.hooks.context import HookAttachment
                result[-1].hook_attachments = [
                    HookAttachment(**a) if isinstance(a, dict) else a
                    for a in result[-1].hook_attachments
                ]
            result[-1]._usage_restored = True
            result[-1]._usage_invalidated = bool(d.get('_usage_invalidated'))
            result[-1].context_summary = bool(d.get('context_summary'))
        else:
            result.append(Message(role='user', content=str(d)))
    return result
