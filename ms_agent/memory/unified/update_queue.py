"""MemoryUpdateQueue — Phase 2 debounced async queue for facts extraction.

Same-thread_id updates are merged (messages replaced, flags OR'd).
After *debounce_seconds* of inactivity the queue triggers
``LLMMergeExtractor`` → ``FactsStorage.apply_merge``.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ms_agent.utils.logger import get_logger

from .config import MemoryConfig
from .extraction.llm_merge import LLMMergeExtractor
from .protocols import MemoryEntry
from .storage.facts_storage import FactsStorage

logger = get_logger()


@dataclass
class _PendingUpdate:
    thread_id: str
    messages: List[Dict[str, Any]]
    has_correction: bool = False
    has_reinforcement: bool = False


class MemoryUpdateQueue:
    """Debounced queue — merges rapid-fire updates and flushes via LLM."""

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
        self._lock = asyncio.Lock()
        self._running = True

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def add(
        self,
        thread_id: str,
        messages: List[Dict[str, Any]],
        correction: bool = False,
        reinforcement: bool = False,
    ) -> None:
        """Enqueue an update.  Same *thread_id* merges with pending."""
        async with self._lock:
            if thread_id in self._pending:
                p = self._pending[thread_id]
                p.messages = messages  # latest wins
                p.has_correction = p.has_correction or correction
                p.has_reinforcement = p.has_reinforcement or reinforcement
            else:
                self._pending[thread_id] = _PendingUpdate(
                    thread_id=thread_id,
                    messages=messages,
                    has_correction=correction,
                    has_reinforcement=reinforcement,
                )
            # reset debounce timer
            self._cancel_timer(thread_id)
            loop = asyncio.get_running_loop()
            self._timers[thread_id] = loop.call_later(
                self.debounce_seconds,
                lambda tid=thread_id: asyncio.ensure_future(
                    self._flush(tid)),
            )

    async def add_nowait(
        self,
        thread_id: str,
        messages: List[Dict[str, Any]],
    ) -> None:
        """Force immediate flush (used before compression)."""
        async with self._lock:
            self._pending[thread_id] = _PendingUpdate(
                thread_id=thread_id, messages=messages)
            self._cancel_timer(thread_id)
        await self._flush(thread_id)

    async def shutdown(self) -> None:
        self._running = False
        async with self._lock:
            for tid in list(self._pending.keys()):
                self._cancel_timer(tid)
                await self._flush(tid)

    # ------------------------------------------------------------------
    # Internal flush
    # ------------------------------------------------------------------

    async def _flush(self, thread_id: str) -> None:
        async with self._lock:
            pending = self._pending.pop(thread_id, None)
            self._cancel_timer(thread_id)
        if not pending:
            return

        logger.info(f"[update_queue] Flushing facts for {thread_id}")
        existing = await self._facts.list_all()
        existing_json = json.dumps(
            [e.to_dict() for e in existing], ensure_ascii=False)

        entries = await self._extractor.extract(
            pending.messages, existing_facts=existing_json)
        if not entries:
            return

        facts_to_remove: List[str] = []
        for e in entries:
            ids = e.metadata.get("factsToRemove", [])
            if isinstance(ids, list):
                facts_to_remove.extend(ids)

        await self._facts.apply_merge(entries, facts_to_remove)
        logger.info(
            f"[update_queue] Applied {len(entries)} new facts, "
            f"removed {len(facts_to_remove)}")

    def _cancel_timer(self, thread_id: str) -> None:
        timer = self._timers.pop(thread_id, None)
        if timer is not None:
            timer.cancel()
