# Copyright (c) ModelScope Contributors. All rights reserved.
"""Tests for MCPRuntime and ToolManager integration (design doc §14)."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from ms_agent.config.mcp_schema import ResolvedMCPConfig
from ms_agent.llm.utils import Tool
from ms_agent.mcp.runtime import (
    DEGRADED_FAILURE_THRESHOLD,
    MCPRuntime,
    classify_mcp_failure,
    is_connection_error,
)
from ms_agent.tools.tool_manager import ToolManager


class FakeMCPClient:
    """Minimal MCPClient stand-in for unit tests."""

    def __init__(self, mcp_config: Dict[str, Any] | None = None):
        self.mcp_config = mcp_config or {'mcpServers': {}}
        self.sessions: Dict[str, Any] = {}
        self.connect_calls: list[str] = []
        self.get_tools_calls = 0
        self.call_tool_calls = 0
        self.list_tools_raises_for: str | None = None

    def is_connected(self, server_name: str) -> bool:
        return server_name in self.sessions

    def list_connected_servers(self) -> list[str]:
        return list(self.sessions.keys())

    async def connect_single_server(self, server_name: str, server_config: dict):
        self.connect_calls.append(server_name)
        if server_config.get('fail_connect') or server_config.get('command') == 'x':
            raise ConnectionError(f'connect failed: {server_name}')
        self.sessions[server_name] = object()
        return server_name

    async def disconnect_server(self, server_name: str):
        self.sessions.pop(server_name, None)

    async def get_tools_for_server(self, server_name: str) -> List[Tool]:
        self.get_tools_calls += 1
        if self.list_tools_raises_for == server_name:
            raise ConnectionError('session closed')
        if server_name not in self.sessions:
            return []
        return [
            Tool(
                tool_name='demo_tool',
                server_name=server_name,
                description='demo',
                parameters={},
            )
        ]

    async def get_tools(self) -> Dict[str, List[Tool]]:
        tools: Dict[str, List[Tool]] = {}
        for name in self.sessions:
            try:
                tools[name] = await self.get_tools_for_server(name)
            except Exception:
                tools[name] = []
        return tools

    async def call_tool(self, server_name: str, tool_name: str, tool_args: dict):
        self.call_tool_calls += 1
        if getattr(self, 'call_raises', False):
            raise ConnectionError('broken pipe')
        if getattr(self, 'call_timeout', False):
            raise TimeoutError('tool call timeout')
        return 'ok'

    async def cleanup(self):
        self.sessions.clear()


def _resolved(*servers: tuple[str, dict]) -> ResolvedMCPConfig:
    return ResolvedMCPConfig(
        mcp_servers={name: dict(cfg, enabled=cfg.get('enabled', True))
                     for name, cfg in servers})


@pytest.mark.asyncio
async def test_independent_client_injection():
    client = FakeMCPClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('fetch', {'command': 'echo'})),
        owns_client=False,
    )
    await runtime.start()
    assert client.is_connected('fetch')


@pytest.mark.asyncio
async def test_disable_removes_tools_but_keeps_session():
    client = FakeMCPClient()
    config = _resolved(('fetch', {'command': 'echo'}))
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=config,
        owns_client=False,
    )
    tm = _make_tool_manager(client, runtime)
    await tm.connect()
    runtime.bind_tool_manager(tm)
    await runtime.start()
    await runtime.sync_tools()
    tools = await tm.get_tools()
    assert any('fetch---' in t['tool_name'] for t in tools)

    await runtime.disable_server('fetch')
    tools = await tm.get_tools()
    assert not any('fetch---' in t['tool_name'] for t in tools)
    assert client.is_connected('fetch')


@pytest.mark.asyncio
async def test_sync_mcp_tools_clears_and_is_idempotent():
    client = FakeMCPClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('fetch', {'command': 'echo'})),
        owns_client=False,
    )
    tm = _make_tool_manager(client, runtime)
    await tm.connect()
    runtime.bind_tool_manager(tm)
    await runtime.start()
    await runtime.sync_tools()
    await runtime.sync_tools()
    keys = [t['tool_name'] for t in await tm.get_tools()]
    assert keys.count('fetch---demo_tool') == 1


@pytest.mark.asyncio
async def test_connect_skip_policy():
    client = FakeMCPClient()
    config = ResolvedMCPConfig(mcp_servers={
        'bad': {'command': 'x'},
        'good': {'command': 'echo'},
    })
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=config,
        connect_policy='skip',
        owns_client=False,
    )
    await runtime.start()
    assert runtime.get_server('bad').status == 'error'
    assert runtime.get_server('good').status == 'connected'


@pytest.mark.asyncio
async def test_runtime_mode_a_no_double_connect():
    client = FakeMCPClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('fetch', {'command': 'echo'})),
        owns_client=False,
    )
    await runtime.start()
    class _Cfg:
        tools = type('T', (), {})()

    tm = ToolManager(
        config=_Cfg(),
        mcp_config={},
        mcp_client=client,  # type: ignore[arg-type]
    )
    tm._skip_mcp_reindex = True
    await tm.connect()
    assert client.connect_calls.count('fetch') == 1


@pytest.mark.asyncio
async def test_degraded_hidden_from_llm_tools():
    client = FakeMCPClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('fetch', {'command': 'echo'})),
        owns_client=False,
    )
    tm = _make_tool_manager(client, runtime)
    await tm.connect()
    runtime.bind_tool_manager(tm)
    await runtime.start()
    await runtime.sync_tools()

    await runtime.record_failure(
        'fetch', 'call_tool', 'Connection closed',
        exc=ConnectionError('Connection closed'))
    assert runtime.get_server('fetch').status == 'degraded'
    tools = await tm.get_tools()
    assert not any('fetch---' in t['tool_name'] for t in tools)
    assert runtime.is_callable('fetch') is False


@pytest.mark.asyncio
async def test_transient_failure_not_immediately_degraded():
    client = FakeMCPClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('fetch', {'command': 'echo'})),
        owns_client=False,
    )
    tm = _make_tool_manager(client, runtime)
    await tm.connect()
    runtime.bind_tool_manager(tm)
    await runtime.start()
    await runtime.sync_tools()

    for _ in range(DEGRADED_FAILURE_THRESHOLD - 1):
        await runtime.record_failure(
            'fetch', 'call_tool', 'timeout',
            exc=TimeoutError('timeout'))

    assert runtime.get_server('fetch').status == 'connected'
    tools = await tm.get_tools()
    assert any('fetch---' in t['tool_name'] for t in tools)


@pytest.mark.asyncio
async def test_transient_failure_threshold_degrades():
    client = FakeMCPClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('fetch', {'command': 'echo'})),
        owns_client=False,
    )
    tm = _make_tool_manager(client, runtime)
    await tm.connect()
    runtime.bind_tool_manager(tm)
    await runtime.start()
    await runtime.sync_tools()

    for _ in range(DEGRADED_FAILURE_THRESHOLD):
        await runtime.record_failure(
            'fetch', 'call_tool', 'timeout',
            exc=TimeoutError('timeout'))

    assert runtime.get_server('fetch').status == 'degraded'
    tools = await tm.get_tools()
    assert not any('fetch---' in t['tool_name'] for t in tools)


@pytest.mark.asyncio
async def test_get_tools_per_server_isolation():
    client = FakeMCPClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(
            ('good', {'command': 'echo'}),
            ('bad', {'command': 'echo'}),
        ),
        owns_client=False,
    )
    tm = _make_tool_manager(client, runtime)
    await tm.connect()
    runtime.bind_tool_manager(tm)
    await runtime.start()
    client.list_tools_raises_for = 'bad'
    await runtime.sync_tools()
    tools = await tm.get_tools()
    assert any('good---' in t['tool_name'] for t in tools)
    assert not any('bad---' in t['tool_name'] for t in tools)


@pytest.mark.asyncio
async def test_mcp_failure_handler_on_connection_error():
    client = FakeMCPClient()
    client.call_raises = True
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('fetch', {'command': 'echo'})),
        owns_client=False,
    )
    tm = _make_tool_manager(client, runtime)
    await tm.connect()
    runtime.bind_tool_manager(tm)
    await runtime.start()
    await runtime.sync_tools()

    await tm.single_call_tool({
        'tool_name': 'fetch---demo_tool',
        'arguments': {},
    })
    assert runtime.get_server('fetch').status == 'degraded'


@pytest.mark.asyncio
async def test_sync_mcp_tools_during_parallel_hooks():
    client = FakeMCPClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('fetch', {'command': 'echo'})),
        owns_client=False,
    )
    tm = _make_tool_manager(client, runtime)
    await tm.connect()
    runtime.bind_tool_manager(tm)
    await runtime.start()
    await runtime.sync_tools()

    async def call_and_sync():
        task = asyncio.create_task(tm.single_call_tool({
            'tool_name': 'fetch---demo_tool',
            'arguments': {},
        }))
        await asyncio.sleep(0)
        await runtime.sync_tools()
        return await task

    results = await asyncio.gather(call_and_sync(), runtime.sync_tools())
    assert results is not None


@pytest.mark.asyncio
async def test_record_success_resets_transient_counter():
    client = FakeMCPClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('fetch', {'command': 'echo'})),
        owns_client=False,
    )
    await runtime.start()
    await runtime.record_failure(
        'fetch', 'call_tool', 'timeout', exc=TimeoutError('timeout'))
    await runtime.record_failure(
        'fetch', 'call_tool', 'timeout', exc=TimeoutError('timeout'))
    assert runtime.get_server('fetch').consecutive_failures == 2
    await runtime.record_success('fetch')
    assert runtime.get_server('fetch').consecutive_failures == 0
    assert runtime.get_server('fetch').status == 'connected'


def test_classify_mcp_failure():
    assert classify_mcp_failure(TimeoutError()) == 'transient'
    assert classify_mcp_failure(ConnectionError('x')) == 'hard'
    assert classify_mcp_failure(BrokenPipeError()) == 'hard'
    assert classify_mcp_failure(ValueError('bad arg')) == 'none'


def test_is_connection_error():
    assert is_connection_error(ConnectionError('x'))
    assert is_connection_error(TimeoutError())
    assert not is_connection_error(ValueError('bad arg'))


class _DenyHookRuntime:
    is_empty = False

    async def run_pre_tool_use(self, tool_name, tool_args, **kwargs):
        from ms_agent.hooks.events import HookResult
        return HookResult(action='deny', reason='blocked by test'), []

    async def run_post_tool_use(self, **kwargs):
        from ms_agent.hooks.events import HookResult
        return HookResult(action='allow'), []


@pytest.mark.asyncio
async def test_mcp_tool_pre_tool_use_deny():
    client = FakeMCPClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('fetch', {'command': 'echo'})),
        owns_client=False,
    )
    tm = _make_tool_manager(client, runtime, hook_runtime=_DenyHookRuntime())
    await tm.connect()
    runtime.bind_tool_manager(tm)
    await runtime.start()
    await runtime.sync_tools()

    result = await tm.single_call_tool({
        'tool_name': 'fetch---demo_tool',
        'arguments': {},
    })
    assert 'Blocked by hook' in result
    assert client.call_tool_calls == 0


@pytest.mark.asyncio
async def test_timeout_triggers_transient_failure():
    client = FakeMCPClient()

    async def slow_call_tool(server_name, tool_name, tool_args):
        await asyncio.sleep(2)
        return 'ok'

    client.call_tool = slow_call_tool  # type: ignore[method-assign]
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('fetch', {'command': 'echo'})),
        owns_client=False,
    )
    tm = _make_tool_manager(client, runtime)
    await tm.connect()
    runtime.bind_tool_manager(tm)
    await runtime.start()
    await runtime.sync_tools()

    await tm.single_call_tool({
        'tool_name': 'fetch---demo_tool',
        'arguments': {'timeout': 1},
    })
    state = runtime.get_server('fetch')
    assert state.consecutive_failures == 1
    assert state.status == 'connected'


@pytest.mark.asyncio
async def test_sync_mcp_tools_list_failure_records():
    client = FakeMCPClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('fetch', {'command': 'echo'})),
        owns_client=False,
    )
    tm = _make_tool_manager(client, runtime)
    await tm.connect()
    runtime.bind_tool_manager(tm)
    await runtime.start()
    client.list_tools_raises_for = 'fetch'
    await runtime.sync_tools()
    state = runtime.get_server('fetch')
    assert state.consecutive_failures >= 1
    assert state.last_error is not None


@pytest.mark.asyncio
async def test_mcp_client_aexit_disconnects_server_stacks():
    from contextlib import AsyncExitStack

    from ms_agent.tools.mcp_client import MCPClient

    client = MCPClient({'mcpServers': {}})
    client.sessions['fake'] = object()
    stack = AsyncExitStack()
    await stack.__aenter__()
    client._server_stacks['fake'] = stack

    await client.__aexit__(None, None, None)
    assert 'fake' not in client.sessions
    assert 'fake' not in client._server_stacks


def _make_tool_manager(client, runtime, hook_runtime=None):
    class _Tools:
        pass

    class _Config:
        tool_call_timeout = 30
        tool_call_timeout_max = 600
        tools = _Tools()

    tm = ToolManager(
        config=_Config(),
        mcp_config={},
        mcp_client=client,  # type: ignore[arg-type]
        hook_runtime=hook_runtime,
        mcp_callable_check=runtime.is_callable,
        mcp_failure_handler=runtime.record_failure,
        mcp_unavailable_detail=runtime.unavailable_detail,
        mcp_success_handler=runtime.record_success,
    )
    tm._skip_mcp_reindex = True
    return tm
