"""86121430: MCP streamable_http / jupyter teardown must not dump stack on quit."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from ms_agent.tools.mcp_client import MCPClient, _is_teardown_noise


def test_is_teardown_noise_matches_sdk_errors():
    assert _is_teardown_noise(
        RuntimeError(
            'Attempted to exit cancel scope in a different task than it was entered in'
        ))
    assert _is_teardown_noise(
        RuntimeError('athrow(): asynchronous generator is already running'))
    assert not _is_teardown_noise(RuntimeError('connection refused'))


@pytest.mark.asyncio
async def test_stop_server_does_not_cancel_owner_when_waiter_is_cancelled():
    client = MCPClient({'mcpServers': {}})
    shutdown = asyncio.Event()
    cancelled = asyncio.Event()
    closed = asyncio.Event()

    async def _owner():
        try:
            await shutdown.wait()
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        finally:
            closed.set()

    task = asyncio.create_task(_owner())
    client._server_shutdown['time'] = shutdown
    client._server_tasks['time'] = task
    await asyncio.sleep(0)

    async def _waiter():
        await client._stop_server('time', graceful=True)

    waiter = asyncio.create_task(_waiter())
    await asyncio.sleep(0)
    waiter.cancel()
    await waiter
    await asyncio.wait_for(closed.wait(), timeout=1)
    assert not cancelled.is_set()
    assert task.done()
    assert not task.cancelled()


@pytest.mark.asyncio
async def test_stop_server_swallows_cancel_scope_runtimeerror():
    client = MCPClient({'mcpServers': {}})
    shutdown = asyncio.Event()

    async def _owner():
        await shutdown.wait()
        raise RuntimeError(
            'Attempted to exit cancel scope in a different task than it was entered in'
        )

    client._server_shutdown['time'] = shutdown
    client._server_tasks['time'] = asyncio.create_task(_owner())
    await asyncio.sleep(0)
    await client._stop_server('time', graceful=True)


@pytest.mark.asyncio
async def test_cleanup_tools_swallows_mcp_runtimeerror():
    from ms_agent.agent.llm_agent import LLMAgent

    agent = LLMAgent.__new__(LLMAgent)
    agent._tools_cleaned = False
    agent.task_manager = None
    agent.tool_manager = None
    agent.memory_tools = []

    class _Boom:
        async def stop(self):
            raise RuntimeError(
                'Attempted to exit cancel scope in a different task than it was entered in'
            )

    agent.mcp_runtime = _Boom()
    await agent.cleanup_tools()
    await agent.cleanup_tools()  # idempotent


@pytest.mark.asyncio
async def test_kernel_session_stop_swallows_cancellederror():
    from ms_agent.tools.code.local_code_executor import LocalKernelSession

    session = LocalKernelSession.__new__(LocalKernelSession)
    session._client = SimpleNamespace(stop_channels=lambda: None)

    async def _boom():
        raise asyncio.CancelledError()

    session._km = SimpleNamespace(shutdown_kernel=lambda now=True: _boom())
    session.start_ts = 1.0
    session.execution_count = 3
    await session.stop()
    assert session._km is None
    assert session._client is None
