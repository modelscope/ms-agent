"""Concurrent admission must preserve protocol-store capacity and identity."""

import asyncio
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from omegaconf import OmegaConf


@pytest.fixture(params=['a2a', 'acp'])
def store_case(request, tmp_path, monkeypatch):
    module = import_module(f'ms_agent.{request.param}.session_store')
    config_path = tmp_path / 'agent.yaml'
    config_path.write_text('{}', encoding='utf-8')
    agents = []

    def build(**kwargs):
        agent = SimpleNamespace(cleanup_tools=AsyncMock())
        agents.append(agent)
        return agent

    monkeypatch.setattr(module.Config, 'from_task',
                        lambda path: OmegaConf.create({}))
    monkeypatch.setattr(module.AgentLoader, 'build', build)
    if request.param == 'a2a':
        store = module.A2AAgentStore(str(config_path), max_tasks=1)
        create = store.get_or_create
        entries = store._tasks
        capacity_error = module.MaxTasksError
    else:
        store = module.ACPSessionStore(max_sessions=1)

        async def create(key):
            return await store.create(str(config_path), str(tmp_path))

        entries = store._sessions
        capacity_error = module.MaxSessionsError
    return store, create, entries, agents, capacity_error


@pytest.mark.parametrize('store_case', ['a2a'], indirect=True)
@pytest.mark.asyncio
async def test_same_a2a_task_during_eviction_reuses_its_agent(store_case):
    store, create, entries, agents, _ = store_case
    started, release = asyncio.Event(), asyncio.Event()

    async def cleanup():
        started.set()
        await release.wait()

    try:
        old = await create('old')
        old.agent.cleanup_tools.side_effect = cleanup
        first = asyncio.create_task(create('shared'))
        await asyncio.wait_for(started.wait(), timeout=2)
        second = asyncio.create_task(create('shared'))
        await asyncio.sleep(0)
        release.set()
        first_entry, second_entry = await asyncio.gather(first, second)
        assert first_entry is second_entry
        assert store.get('shared') is first_entry
        assert len(agents) == 2
    finally:
        release.set()
        await store.close_all()


@pytest.mark.asyncio
async def test_concurrent_admission_during_eviction_respects_capacity(store_case):
    store, create, entries, agents, capacity_error = store_case
    started, release = asyncio.Event(), asyncio.Event()

    async def cleanup():
        started.set()
        await release.wait()

    async def admit(key):
        entry = await create(key)
        entry.is_running = True
        return entry

    try:
        old = await create('old')
        old.agent.cleanup_tools.side_effect = cleanup
        first = asyncio.create_task(admit('first'))
        await asyncio.wait_for(started.wait(), timeout=2)
        second = asyncio.create_task(admit('second'))
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)

        assert len(entries) == 1
        assert sum(isinstance(r, capacity_error) for r in results) == 1
        assert len(agents) == 2  # the evicted agent and one admitted agent
    finally:
        release.set()
        await store.close_all()


@pytest.mark.asyncio
async def test_cancelled_admission_does_not_block_the_next_request(store_case):
    store, create, entries, _, _ = store_case
    started = asyncio.Event()

    async def cleanup():
        started.set()
        await asyncio.Event().wait()

    try:
        old = await create('old')
        old.agent.cleanup_tools.side_effect = cleanup
        pending = asyncio.create_task(create('cancelled'))
        await asyncio.wait_for(started.wait(), timeout=2)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        entry = await asyncio.wait_for(create('next'), timeout=2)
        assert list(entries.values()) == [entry]
    finally:
        await store.close_all()


@pytest.mark.asyncio
async def test_idle_replacement_cleans_the_evicted_agent(store_case):
    store, create, entries, agents, _ = store_case
    try:
        old = await create('old')
        new = await create('new')
        assert list(entries.values()) == [new]
        old.agent.cleanup_tools.assert_awaited_once()
        assert len(agents) == 2
    finally:
        await store.close_all()
