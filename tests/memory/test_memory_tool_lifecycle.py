# Copyright (c) ModelScope Contributors. All rights reserved.
"""Memory tools obey the orchestrator's store ownership and close contract."""
import asyncio

import pytest

from ms_agent.memory.unified.backends.file_based import FileBasedBackend
from ms_agent.memory.unified.config import MemoryConfig
from ms_agent.memory.unified.memory_tool import MemoryTool, SERVER_NAME
from ms_agent.memory.unified.orchestrator import MemoryOrchestrator, _store_lock


def make_tool(tmp_path, backend=None):
    config = MemoryConfig(base_dir=str(tmp_path))
    orch = MemoryOrchestrator(config)
    if backend is not None:
        orch._backend = backend
    return orch, MemoryTool(config, orch)


async def add(tool, content):
    return await tool.call_tool(SERVER_NAME, tool_name='memory',
                                tool_args={'action': 'add', 'content': content})


@pytest.mark.asyncio
async def test_closed_unused_tool_does_not_create_backend(tmp_path):
    orch, tool = make_tool(tmp_path)
    await orch.close()
    result = await add(tool, 'must not be saved')
    assert orch._backend is None
    assert not (tmp_path / 'MEMORY.md').exists()
    assert 'closed' in result.lower()


@pytest.mark.asyncio
async def test_closed_tool_does_not_reopen_or_modify_memory(tmp_path):
    orch, tool = make_tool(tmp_path)
    await add(tool, 'first memory')
    before = (tmp_path / 'MEMORY.md').read_bytes()
    await orch.close()
    result = await add(tool, 'late memory')
    assert not orch._started
    assert (tmp_path / 'MEMORY.md').read_bytes() == before
    assert 'closed' in result.lower()


@pytest.mark.asyncio
async def test_tool_waits_for_existing_store_owner(tmp_path):
    orch, tool = make_tool(tmp_path)
    lock = _store_lock(str(tmp_path))
    await lock.acquire()
    pending = asyncio.create_task(add(tool, 'after owner releases'))
    try:
        await asyncio.sleep(0)
        assert not pending.done()
        assert not (tmp_path / 'MEMORY.md').exists()
    finally:
        lock.release()
        await pending
        await orch.close()
    assert 'after owner releases' in (tmp_path / 'MEMORY.md').read_text()


class PausingFileBackend(FileBasedBackend):
    """Pause a real file write at its async boundary to control interleaving."""

    def __init__(self, config):
        super().__init__(config)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False

    async def handle_tool_call(self, tool_name, arguments):
        self.entered.set()
        await self.release.wait()
        return await super().handle_tool_call(tool_name, arguments)

    async def close(self):
        self.closed = True
        await super().close()


@pytest.mark.asyncio
async def test_close_waits_for_inflight_tool(tmp_path):
    backend = PausingFileBackend(MemoryConfig(base_dir=str(tmp_path)))
    orch, tool = make_tool(tmp_path, backend)
    writing = asyncio.create_task(add(tool, 'accepted before close'))
    await backend.entered.wait()
    closing = asyncio.create_task(orch.close())
    try:
        await asyncio.sleep(0)
        assert not closing.done()
        assert not backend.closed
    finally:
        backend.release.set()
        await writing
        await closing
    assert 'accepted before close' in (tmp_path / 'MEMORY.md').read_text()
    assert not orch._started


@pytest.mark.asyncio
async def test_tools_on_shared_store_are_serialized(tmp_path):
    backend = PausingFileBackend(MemoryConfig(base_dir=str(tmp_path)))
    first, tool1 = make_tool(tmp_path, backend)
    second, tool2 = make_tool(tmp_path)
    writing = asyncio.create_task(add(tool1, 'first'))
    await backend.entered.wait()
    following = asyncio.create_task(add(tool2, 'second'))
    try:
        await asyncio.sleep(0)
        assert not following.done()
    finally:
        backend.release.set()
        await writing
        await following
        await first.close()
        await second.close()
    assert (tmp_path / 'MEMORY.md').read_text().splitlines() == ['first', 'second']


@pytest.mark.asyncio
async def test_waiting_tool_does_not_restart_after_close(tmp_path):
    orch, tool = make_tool(tmp_path)
    await add(tool, 'original')
    lock = _store_lock(str(tmp_path))
    await lock.acquire()
    pending = asyncio.create_task(add(tool, 'late'))
    await asyncio.sleep(0)
    closing = asyncio.create_task(orch.close())
    await asyncio.sleep(0)
    assert orch._closed
    lock.release()
    result = await pending
    await closing
    assert (tmp_path / 'MEMORY.md').read_text().splitlines() == ['original']
    assert 'closed' in result.lower()


@pytest.mark.asyncio
async def test_live_tool_result_and_arguments_are_preserved(tmp_path):
    orch, tool = make_tool(tmp_path)
    assert await add(tool, 'original') == '已记住'
    result = await tool.call_tool(SERVER_NAME, tool_name='memory', tool_args={
        'action': 'replace', 'content': 'original', 'new_content': 'replacement'})
    assert result == '已更新'
    assert await tool.call_tool(SERVER_NAME, tool_name='memory_read', tool_args={}) == 'replacement\n'
    await orch.close()


@pytest.mark.asyncio
async def test_tool_exception_releases_store_lock(tmp_path):
    orch, tool = make_tool(tmp_path)
    with pytest.raises(AttributeError):
        await add(tool, None)
    assert not _store_lock(str(tmp_path)).locked()
    assert await add(tool, 'after error') == '已记住'
    await orch.close()


@pytest.mark.asyncio
async def test_close_waits_for_tool_backend_start(tmp_path):
    class StartingFileBackend(FileBasedBackend):
        def __init__(self, config):
            super().__init__(config)
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.closed = False

        async def start(self, **kwargs):
            self.entered.set()
            await self.release.wait()
            await super().start(**kwargs)

        async def close(self):
            self.closed = True
            await super().close()

    backend = StartingFileBackend(MemoryConfig(base_dir=str(tmp_path)))
    orch, tool = make_tool(tmp_path, backend)
    writing = asyncio.create_task(add(tool, 'accepted during startup'))
    await backend.entered.wait()
    closing = asyncio.create_task(orch.close())
    try:
        await asyncio.sleep(0)
        assert not closing.done()
        assert not backend.closed
    finally:
        backend.release.set()
        await writing
        await closing
    assert backend.closed
    assert not orch._started
    assert 'accepted during startup' in (tmp_path / 'MEMORY.md').read_text()
