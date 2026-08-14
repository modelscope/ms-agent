# Copyright (c) ModelScope Contributors. All rights reserved.
"""Sharing and reconfiguration of memory instances.

``SharedMemoryManager`` hands one instance per store to every agent that asks
for it, which raises two questions these tests pin down:

* what happens when a later agent's config differs from the one the instance
  was built with — it must be adopted, otherwise editing a memory setting is
  indistinguishable from the setting doing nothing;
* what happens when only the agent's model differs — the instance must still
  be shared, because embedded vector stores take an exclusive file lock and a
  second instance on the same path cannot open the store at all.
"""
import asyncio

import pytest
from omegaconf import OmegaConf

from ms_agent.memory.memory_manager import SharedMemoryManager
from ms_agent.memory.unified.config import MemoryConfig
from ms_agent.memory.unified.orchestrator import MemoryOrchestrator


class FakeBackend:
    """Backend that keeps the config object it was constructed with, the way
    every real backend does."""

    def __init__(self, config):
        self._config = config
        self.closed = False

    async def start(self, **kwargs):
        pass

    async def inject(self, messages):
        return messages

    async def on_messages(self, messages, **kwargs):
        return len(messages)

    async def on_pre_compress(self, messages):
        pass

    async def close(self):
        self.closed = True

    def invalidate(self):
        pass


@pytest.fixture(autouse=True)
def _clean_instances():
    SharedMemoryManager._instances.clear()
    yield
    SharedMemoryManager._instances.clear()


def _cfg(tmp_path, *, model='m1', recall=10, backend='file', options=None):
    node = {
        'storage': {
            'backend': backend
        },
        'namespace': {
            'user_id': 'p1'
        },
        'user_id': 'p1',
        'base_dir': str(tmp_path),
        'recall_top_k': recall,
    }
    if options is not None:
        node['mem0'] = options
    return OmegaConf.create({
        'output_dir': str(tmp_path),
        'llm': {
            'model': model
        },
        'memory': {
            'unified_memory': node
        },
    })


def _orch(tmp_path, **cfg_kwargs):
    """A live orchestrator, built the way an agent builds one."""
    orch = MemoryOrchestrator(_cfg(tmp_path, **cfg_kwargs))
    orch._backend = FakeBackend(orch.mem_config)
    orch._started = True
    return orch


def test_identical_config_is_a_noop(tmp_path):
    orch = _orch(tmp_path)
    backend = orch._backend
    assert asyncio.run(orch.reconfigure(_cfg(tmp_path))) is False
    assert backend.closed is False
    assert orch._backend is backend


def test_recall_size_applies_without_tearing_the_store_down(tmp_path):
    """The reported bug: a changed recall size must reach the LIVE backend.

    It is applied by writing through the shared MemoryConfig object rather
    than rebinding it, because the backend holds a reference to that object —
    rebinding would leave the backend reading the old numbers.
    """
    orch = _orch(tmp_path, recall=10)
    backend = orch._backend

    torn_down = asyncio.run(orch.reconfigure(_cfg(tmp_path, recall=3)))

    assert torn_down is False  # no reason to close a store for a number
    assert backend.closed is False
    assert orch.mem_config.recall_top_k == 3
    assert backend._config.recall_top_k == 3  # what inject() actually reads


def test_store_affecting_change_rebuilds_the_backend(tmp_path):
    orch = _orch(tmp_path, backend='mem0')
    backend = orch._backend

    torn_down = asyncio.run(
        orch.reconfigure(
            _cfg(
                tmp_path,
                backend='mem0',
                options={'embedder': {
                    'provider': 'fastembed'
                }})))

    assert torn_down is True
    assert backend.closed is True  # store released, so its lock is too
    assert orch._backend is None  # next use builds from the new config


def test_switching_models_shares_one_instance(tmp_path):
    """Two agents on one store, different models: one instance.

    Keying the cache by model used to hand the second agent its own instance,
    which then could not open the (exclusively locked) store at all — memory
    silently stopped working for whoever switched models.
    """

    async def main():
        first = await SharedMemoryManager.get_shared_memory(
            _cfg(tmp_path, model='m1'), 'unified_memory')
        second = await SharedMemoryManager.get_shared_memory(
            _cfg(tmp_path, model='m2'), 'unified_memory')
        return first, second

    first, second = asyncio.run(main())
    assert first is second
    assert len(SharedMemoryManager._instances) == 1


def test_manager_adopts_a_changed_recall_size(tmp_path):

    async def main():
        await SharedMemoryManager.get_shared_memory(
            _cfg(tmp_path, recall=10), 'unified_memory')
        return await SharedMemoryManager.get_shared_memory(
            _cfg(tmp_path, recall=5), 'unified_memory')

    assert asyncio.run(main()).mem_config.recall_top_k == 5


def test_different_stores_stay_separate(tmp_path):

    async def main():
        a = await SharedMemoryManager.get_shared_memory(
            _cfg(tmp_path / 'a'), 'unified_memory')
        b = await SharedMemoryManager.get_shared_memory(
            _cfg(tmp_path / 'b'), 'unified_memory')
        return a, b

    a, b = asyncio.run(main())
    assert a is not b
    assert len(SharedMemoryManager._instances) == 2


def test_reconfigure_failure_keeps_the_cached_instance(tmp_path):
    """A broken incoming config must not take an agent's memory down with it:
    the existing instance keeps serving its own configuration."""

    async def main():
        instance = await SharedMemoryManager.get_shared_memory(
            _cfg(tmp_path, recall=10), 'unified_memory')

        async def boom(_config):
            raise RuntimeError('bad config')

        instance.reconfigure = boom
        again = await SharedMemoryManager.get_shared_memory(
            _cfg(tmp_path, recall=5), 'unified_memory')
        return instance, again

    instance, again = asyncio.run(main())
    assert instance is again
    assert again.mem_config.recall_top_k == 10
