"""Process-local pub/sub for pushing "something changed" notices to the UI.

A single-process broadcast hub: management endpoints publish a change notice
after a successful write, and every connected browser (subscribed via
GET /api/events) receives it and refreshes the affected lists. This is what
lets a change made by an EXTERNAL caller (a script hitting the REST API) reach
an already-open page, which the in-tab event bus on the frontend cannot do.

Single-process only: subscribers live in one event loop's memory. A multi-worker
deployment would need a cross-process channel (e.g. Redis pub/sub) behind the
same `publish`/`subscribe` surface.
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

# Per-subscriber buffer. Change notices are tiny and rare; this only bounds a
# subscriber that has stopped reading (a wedged connection) so it cannot grow
# without limit. On overflow the oldest notice is dropped for the LATEST, since
# every notice triggers the same "refresh" and the freshest one wins.
_QUEUE_MAXSIZE = 128


class EventBus:
    """Fan out change notices to every live subscriber, in-process."""

    def __init__(self, max_queue: int = _QUEUE_MAXSIZE) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._max = max_queue

    def publish(self, event: dict[str, Any]) -> None:
        """Deliver `event` to every subscriber. Never raises or blocks: a full
        buffer drops its oldest notice so the newest still lands."""
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        """Yield notices until the consumer stops iterating (client disconnect
        cancels the generator, and the `finally` unregisters the queue)."""
        q: asyncio.Queue = asyncio.Queue(maxsize=self._max)
        self._subscribers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


event_bus = EventBus()
