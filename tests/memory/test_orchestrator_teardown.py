# Copyright (c) ModelScope Contributors. All rights reserved.
"""Interrupt / teardown hazards around the ingest ledger and the store lock.

All four guard the same property from different sides: a memory that the
conversation produced is either written or still owed — never quietly dropped,
and never written into a store whose owner has let go of it.

* an interrupt must not advance the ledger past a write that is still running
  (the write then finds an empty delta, or fails and is denied its retry);
* the per-store lock must survive a process that runs more than one event loop;
* retrieval takes that lock too, so it cannot read a store mid-write;
* a closed orchestrator must not be reopened by a straggling ingest.
"""
import asyncio

import pytest

from ms_agent.llm.utils import Message
from ms_agent.memory.unified.config import MemoryConfig
from ms_agent.memory.unified.orchestrator import (MemoryOrchestrator,
                                                  _store_lock)


class SlowBackend:
    """Records what it was actually asked to write, slowly enough to overlap."""

    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self.batches = []
        self.searches = []
        self.starts = 0
        self.closes = 0
        self.wrote_after_close = False

    async def start(self, **kwargs):
        self.starts += 1

    async def on_messages(self, messages, **kwargs):
        await asyncio.sleep(self.delay)
        if self.closes:
            self.wrote_after_close = True
        self.batches.append([m['content'] for m in messages])
        return len(messages)

    async def inject(self, messages):
        return messages

    async def search(self, query, limit=10):
        # Recorded on ENTRY: the question is whether retrieval reaches the
        # store while a write holds it, not when it finishes.
        self.searches.append(query)
        await asyncio.sleep(self.delay)
        return []

    async def on_pre_compress(self, messages):
        pass

    async def close(self):
        self.closes += 1

    def invalidate(self):
        pass


def _orch(tmp_path, backend, **cfg):
    orch = MemoryOrchestrator(
        MemoryConfig(base_dir=str(tmp_path), storage_backend='file', **cfg))
    orch._backend = backend
    orch._started = True
    return orch


def _round(user, assistant):
    return [
        Message(role='user', content=user),
        Message(role='assistant', content=assistant)
    ]


def test_interrupt_does_not_swallow_an_ingest_in_flight(tmp_path):
    """The reported data loss.

    A round is being written in the background (extraction takes seconds) when
    the user hits stop. The interrupt advanced the ledger over that round too,
    so the write found an empty delta — the memory was neither stored nor still
    owed. Reproduced here by handing ``mark_ingested`` the WHOLE history, which
    is what the interrupt path used to pass: whatever a caller hands over, a
    write already in flight owns its own messages until it finishes.
    """
    backend = SlowBackend()
    orch = _orch(tmp_path, backend)
    history = _round('u1', 'a1')

    async def main():
        lock = _store_lock(str(tmp_path))
        await lock.acquire()  # the scheduled ingest cannot reach its delta yet
        try:
            task = orch.schedule_add(history)
            await asyncio.sleep(0)
            orch.mark_ingested(history + _round('u2', 'half an answ'))
        finally:
            lock.release()
        await task

    asyncio.run(main())
    assert backend.batches == [['u1', 'a1']]  # the round still got written


def test_interrupt_marks_only_its_own_round(tmp_path):
    """`mark_ingested` is fed one round, not the whole history: an earlier
    round that was never ingested (a failed write, an interval skip) must stay
    owed, not be written off by an unrelated interrupt."""
    backend = SlowBackend(delay=0)
    orch = _orch(tmp_path, backend)
    earlier = _round('u1', 'a1')

    async def main():
        orch.mark_ingested(_round('u2', 'half an answ'))
        await orch.add(earlier)

    asyncio.run(main())
    assert backend.batches == [['u1', 'a1']]


def test_interrupt_still_seals_its_own_partial_round(tmp_path):
    """...while the partial answer itself never reaches the store."""
    backend = SlowBackend(delay=0)
    orch = _orch(tmp_path, backend)
    partial = _round('u1', 'half an answ')

    async def main():
        orch.mark_ingested(partial)
        await orch.add(partial)

    asyncio.run(main())
    assert backend.batches == []


def test_store_lock_survives_a_second_event_loop(tmp_path):
    """asyncio.Lock binds to the loop that first waits on it and refuses every
    other one afterwards. The lock is per (loop, store) so a process that runs
    several loops — the inline `asyncio.run` ingest path, a test suite — does
    not wedge on a lock belonging to a loop that is already closed."""

    async def contend():
        lock = _store_lock(str(tmp_path))
        await lock.acquire()
        waiter = asyncio.create_task(_take(lock))
        await asyncio.sleep(0)  # let it queue: this is what binds the loop
        lock.release()
        await waiter

    async def _take(lock):
        async with lock:
            pass

    asyncio.run(contend())
    asyncio.run(contend())  # RuntimeError: bound to a different event loop


def test_search_waits_for_a_write_to_finish(tmp_path):
    """Retrieval used to be the one store access outside the lock."""
    backend = SlowBackend(delay=0.05)
    orch = _orch(tmp_path, backend)

    async def main():
        lock = _store_lock(str(tmp_path))
        await lock.acquire()
        task = asyncio.create_task(orch.search('who am i'))
        await asyncio.sleep(0.02)
        held = list(backend.searches)  # must not have run yet
        lock.release()
        await task
        return held, backend.searches

    during, after = asyncio.run(main())
    assert during == [] and after == ['who am i']


def test_a_closed_orchestrator_never_reopens_the_store(tmp_path):
    """`close()` releases an embedded store's file lock, so anything that
    reopens it afterwards takes that lock behind the owner's back."""
    backend = SlowBackend(delay=0)
    orch = _orch(tmp_path, backend)

    async def main():
        await orch.close()
        await orch.add(_round('u1', 'a1'))
        await orch.run(_round('u2', 'a2'))
        return await orch.search('anything')

    found = asyncio.run(main())
    assert backend.starts == 0 and backend.closes == 1
    assert backend.batches == [] and found == []


def test_close_still_drains_what_was_already_scheduled(tmp_path):
    """Retiring must not cost the writes close() promised to persist — the
    order is drain, then retire."""
    backend = SlowBackend(delay=0.02)
    orch = _orch(tmp_path, backend)

    async def main():
        orch.schedule_add(_round('u1', 'a1'))
        await orch.close()

    asyncio.run(main())
    assert backend.batches == [['u1', 'a1']]
    assert backend.wrote_after_close is False


def test_reconfigure_keeps_the_instance_usable(tmp_path):
    """The teardown a config change performs is not a retirement: every agent
    sharing this instance must keep working, now on the new configuration."""
    backend = SlowBackend(delay=0)
    orch = _orch(tmp_path, backend)

    async def main():
        await orch.reconfigure(
            MemoryConfig(
                base_dir=str(tmp_path),
                storage_backend='file',
                memory_path='OTHER.md'))
        assert orch._closed is False
        # A fresh backend is built on demand from the new config.
        orch._backend, orch._started = backend, True
        await orch.add(_round('u1', 'a1'))

    asyncio.run(main())
    assert backend.closes == 1  # old backend released
    assert backend.batches == [['u1', 'a1']]  # instance still writes
