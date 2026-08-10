# Copyright (c) ModelScope Contributors. All rights reserved.
"""MemoryOrchestrator write discipline: background scheduling, per-store
serialization, the delta ledger, and status reporting.

These guard the properties that keep ingestion off the turn's critical path
without corrupting the store or silently losing writes:

* ingestion is delta-only (content hashes), and a hash is recorded ONLY
  after the backend accepted the write — a failure retries by construction;
* retrieval and ingestion serialize on one per-store lock (embedded vector
  stores underneath have no locking of their own);
* ``flush_pending`` is a real barrier, so teardown cannot drop the last write;
* ``mark_ingested`` advances the ledger without ingesting (interrupted turns).
"""
import asyncio
import json
import os

import pytest

from ms_agent.llm.utils import Message
from ms_agent.memory.unified.config import MemoryConfig
from ms_agent.memory.unified.orchestrator import MemoryOrchestrator


class RecordingBackend:

    def __init__(self):
        self.batches = []
        self.closed = False
        self.active = 0
        self.max_active = 0

    async def start(self, **kwargs):
        pass

    async def on_messages(self, messages, **kwargs):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        self.batches.append(list(messages))
        return len(messages)

    async def inject(self, messages):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return messages

    async def on_pre_compress(self, messages):
        pass

    async def close(self):
        self.closed = True

    def invalidate(self):
        pass


def _orch(tmp_path, backend, **cfg_kwargs):
    orch = MemoryOrchestrator(
        MemoryConfig(
            base_dir=str(tmp_path), storage_backend='file', **cfg_kwargs))
    orch._backend = backend
    orch._started = True
    return orch


def _msgs(*contents, roles=None):
    roles = roles or ['user', 'assistant'] * len(contents)
    return [
        Message(role=r, content=c) for r, c in zip(roles, contents)
    ]


def test_schedule_add_ingests_in_background_and_flush_waits(tmp_path):

    async def main():
        backend = RecordingBackend()
        orch = _orch(tmp_path, backend)
        task = orch.schedule_add(_msgs('hello', 'hi'))
        assert task is not None and not backend.batches  # not run inline
        await orch.flush_pending()
        assert len(backend.batches) == 1
        assert orch.ingest_status['state'] == 'ok'
        assert orch.ingest_status['count'] == 2

    asyncio.run(main())


def test_system_and_tool_rows_never_reach_the_backend(tmp_path):

    async def main():
        backend = RecordingBackend()
        orch = _orch(tmp_path, backend)
        await orch.add([
            Message(role='system', content='prompt'),
            Message(role='user', content='q'),
            Message(role='tool', content='{"ok":true}', tool_call_id='1'),
            Message(role='assistant', content='a'),
        ])
        assert [m['role'] for m in backend.batches[0]] == ['user', 'assistant']

    asyncio.run(main())


def test_second_ingest_sends_only_the_delta(tmp_path):

    async def main():
        backend = RecordingBackend()
        orch = _orch(tmp_path, backend)
        history = _msgs('turn one', 'answer one')
        await orch.add(history)
        history += _msgs('turn two', 'answer two')
        await orch.add(history)
        assert [m['content'] for m in backend.batches[1]] == [
            'turn two', 'answer two'
        ]

    asyncio.run(main())


def test_ledger_survives_a_process_restart(tmp_path):

    async def main():
        history = _msgs('turn one', 'answer one')
        await _orch(tmp_path, RecordingBackend()).add(history)
        assert os.path.exists(tmp_path / 'ingest_state.json')
        with open(tmp_path / 'ingest_state.json') as fh:
            assert len(json.load(fh)['hashes']) == 2

        # A fresh orchestrator (new process) must not re-ingest old turns.
        backend = RecordingBackend()
        await _orch(tmp_path, backend).add(history)
        assert backend.batches == []

    asyncio.run(main())


def test_failed_ingest_is_retried_on_the_next_turn(tmp_path):

    async def main():

        class Failing(RecordingBackend):

            async def on_messages(self, messages, **kwargs):
                raise RuntimeError('provider down')

        orch = _orch(tmp_path, Failing())
        await orch.add(_msgs('important fact', 'noted'))
        assert orch.ingest_status['state'] == 'error'
        assert 'provider down' in orch.ingest_status['error']

        # Hashes were NOT recorded, so the same messages come back as delta.
        backend = RecordingBackend()
        orch._backend = backend
        await orch.add(_msgs('important fact', 'noted'))
        assert [m['content'] for m in backend.batches[0]] == [
            'important fact', 'noted'
        ]

    asyncio.run(main())


def test_mark_ingested_skips_interrupted_content(tmp_path):

    async def main():
        backend = RecordingBackend()
        orch = _orch(tmp_path, backend)
        interrupted = _msgs('do something', 'half-finished ans')
        orch.mark_ingested(interrupted)
        await orch.add(interrupted + _msgs('next turn', 'done'))
        assert [m['content'] for m in backend.batches[0]] == [
            'next turn', 'done'
        ]

    asyncio.run(main())


def test_ingest_and_inject_serialize_on_the_store_lock(tmp_path):

    async def main():
        backend = RecordingBackend()
        orch = _orch(tmp_path, backend)
        msgs = _msgs('q', 'a')
        orch.schedule_add(msgs)
        await orch.run(msgs)  # retrieval while the ingest task is pending
        await orch.flush_pending()
        assert backend.max_active == 1  # never overlapped

    asyncio.run(main())


def test_ingest_interval_batches_turns(tmp_path):

    async def main():
        backend = RecordingBackend()
        orch = _orch(tmp_path, backend, ingest_interval=2)
        history = _msgs('turn one', 'answer one')
        await orch.add(history)
        assert backend.batches == []  # skipped: 1 of 2
        history += _msgs('turn two', 'answer two')
        await orch.add(history)
        # The firing ingest carries everything not yet ingested.
        assert [m['content'] for m in backend.batches[0]] == [
            'turn one', 'answer one', 'turn two', 'answer two'
        ]

    asyncio.run(main())


def test_close_drains_pending_then_closes_backend(tmp_path):

    async def main():
        backend = RecordingBackend()
        orch = _orch(tmp_path, backend)
        orch.schedule_add(_msgs('q', 'a'))
        await orch.close()
        assert len(backend.batches) == 1  # drained, not dropped
        assert backend.closed

    asyncio.run(main())
