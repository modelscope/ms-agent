"""Debounced, in-memory facts extraction with ordered incremental updates."""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List

from ms_agent.utils.logger import get_logger
from .config import MemoryConfig
from .extraction.llm_merge import LLMMergeExtractor, apply_fact_updates
from .storage.facts_storage import FactsStorage

logger = get_logger()


@dataclass
class _PendingUpdate:
    thread_id: str
    messages: List[Dict[str, Any]]
    has_correction: bool = False
    has_reinforcement: bool = False


def _merge_updates(first, second):
    messages = []
    for message in first.messages + second.messages:
        if message not in messages:
            messages.append(deepcopy(message))
    return _PendingUpdate(first.thread_id, messages, first.has_correction
                          or second.has_correction, first.has_reinforcement
                          or second.has_reinforcement)


class MemoryUpdateQueue:
    """Debounced queue — failures remain pending until an explicit retry."""

    def __init__(
        self,
        config: MemoryConfig,
        extractor: LLMMergeExtractor,
        facts_storage: FactsStorage,
    ):
        self.debounce_seconds = config.debounce_seconds
        self._extractor = extractor
        self._facts = facts_storage
        self._pending: Dict[str, _PendingUpdate] = {}
        self._timers: Dict[str, asyncio.TimerHandle] = {}
        self._tasks: Dict[asyncio.Task, str] = {}
        self._errors: Dict[str, BaseException] = {}
        self._lock = asyncio.Lock()
        self._flush_lock = asyncio.Lock()
        self._running = True

    async def add(
        self,
        thread_id: str,
        messages: List[Dict[str, Any]],
        correction: bool = False,
        reinforcement: bool = False,
    ) -> None:
        async with self._lock:
            self._enqueue(thread_id, messages, correction, reinforcement)
            loop = asyncio.get_running_loop()
            self._timers[thread_id] = loop.call_later(self.debounce_seconds,
                                                      self._start_flush,
                                                      thread_id)

    async def add_nowait(
        self,
        thread_id: str,
        messages: List[Dict[str, Any]],
    ) -> None:
        """Merge pending evidence and wait for the immediate write."""
        async with self._lock:
            self._enqueue(thread_id, messages)
            task = self._start_flush(thread_id)
        await task

    async def shutdown(self) -> None:
        async with self._lock:
            self._running = False
            for tid in list(self._timers):
                self._cancel_timer(tid)
            active = dict(self._tasks)

        async def drain():
            results = await asyncio.gather(*active, return_exceptions=True)
            failed = {
                active[task]
                for task, result in zip(active, results)
                if isinstance(result, BaseException)
            }
            async with self._lock:
                # Do not immediately retry a write that failed during this drain.
                tasks = [
                    self._start_flush(tid) for tid in self._pending
                    if tid not in failed
                ]
            await asyncio.gather(*tasks, return_exceptions=True)
            if self._pending:
                error = next(iter(self._errors.values()), None)
                raise RuntimeError(
                    'Memory updates remain pending after shutdown') from error

        task = asyncio.create_task(drain())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    pass
                except Exception:
                    break
            if not task.cancelled():
                task.exception()
            raise

    def _enqueue(self,
                 thread_id,
                 messages,
                 correction=False,
                 reinforcement=False):
        if not self._running:
            raise RuntimeError('Memory update queue is shut down')
        update = _PendingUpdate(thread_id, messages, correction, reinforcement)
        previous = self._pending.get(thread_id, _PendingUpdate(thread_id, []))
        self._pending[thread_id] = _merge_updates(previous, update)
        self._cancel_timer(thread_id)

    def _start_flush(self, thread_id):
        task = asyncio.create_task(self._flush(thread_id))
        self._tasks[task] = thread_id
        task.add_done_callback(self._flush_done)
        return task

    def _flush_done(self, task):
        thread_id = self._tasks.pop(task)
        if task.cancelled():
            logger.warning(
                f'[update_queue] Flush cancelled for {thread_id}; retained pending'
            )
        elif task.exception() is not None:
            logger.error(
                f'[update_queue] Flush failed for {thread_id}: {task.exception()}'
            )

    async def _flush(self, thread_id: str) -> None:
        # Serialize the read/extract/apply cycle, including across thread IDs.
        async with self._flush_lock:
            async with self._lock:
                pending = self._pending.pop(thread_id, None)
                self._cancel_timer(thread_id)
            if pending is None:
                return
            try:
                existing = await self._facts.list_all()
                existing_json = json.dumps([e.to_dict() for e in existing],
                                           ensure_ascii=False)
                entries = await self._extractor.extract(
                    deepcopy(pending.messages), existing_facts=existing_json)
                await apply_fact_updates(self._facts, entries)
                self._errors.pop(thread_id, None)
                logger.info(f'[update_queue] Applied facts for {thread_id}')
            except (Exception, asyncio.CancelledError) as error:
                async with self._lock:
                    newer = self._pending.get(thread_id,
                                              _PendingUpdate(thread_id, []))
                    self._pending[thread_id] = _merge_updates(pending, newer)
                    self._errors[thread_id] = error
                    self._cancel_timer(thread_id)
                raise

    def _cancel_timer(self, thread_id: str) -> None:
        timer = self._timers.pop(thread_id, None)
        if timer is not None:
            timer.cancel()
