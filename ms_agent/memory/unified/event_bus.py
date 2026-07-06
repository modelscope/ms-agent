"""InMemoryEventBus — Phase 1 event bus backed by asyncio.Queue."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Dict, List

from ms_agent.utils.logger import get_logger

from .protocols import MemoryEvent

logger = get_logger()


class InMemoryEventBus:
    """Simple publish / subscribe bus running in the current event loop."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, Dict[str, Callable]] = {}

    async def publish(self, event: MemoryEvent) -> None:
        subs = self._subscribers.get(event.event_type, {})
        for sid, cb in subs.items():
            try:
                result = cb(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.warning(
                    f"[event_bus] Subscriber {sid} error: {e}")

    async def subscribe(
        self, event_type: str,
        callback: Callable[[MemoryEvent], Any],
    ) -> str:
        sid = uuid.uuid4().hex[:8]
        self._subscribers.setdefault(event_type, {})[sid] = callback
        return sid

    async def unsubscribe(self, subscription_id: str) -> None:
        for subs in self._subscribers.values():
            subs.pop(subscription_id, None)
