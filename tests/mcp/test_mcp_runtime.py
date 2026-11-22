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

    async def connect_single_server(self, server_name: str, server_config: dict,
                                    **kwargs):
        self.connect_calls.append(server_name)
        if server_config.get('fail_connect') or server_config.get('command') == 'x':
            raise ConnectionError(f'connect failed: {server_name}')
        self.sessions[server_name] = object()
        return server_name

    async def disconnect_server(self, server_name: str, **kwargs):
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
        if getattr(self, 'call_cancel', False):
            raise asyncio.CancelledError()
        if getattr(self, 'call_group', False):
            raise ExceptionGroup('mcp', [ConnectionError('broken pipe')])
        if getattr(self, 'call_raises', False):
            raise ConnectionError('broken pipe')
        if getattr(self, 'call_timeout', False):
            raise TimeoutError('tool call timeout')
        return 'ok'

    async def cleanup(self):
        self.sessions.clear()


class _FakeExtraTool:
    """Minimal non-MCP extra tool used to exercise index_extra_tool()."""

    def __init__(self, name: str = 'mem', tool: str = 'do'):
        self._name = name
        self._tool = tool

    async def connect(self):
        pass

    async def cleanup(self):
        pass

    async def get_tools(self) -> Dict[str, List[Tool]]:
        return {
            self._name: [
                Tool(
                    tool_name=self._tool,
                    server_name=self._name,
                    description='d',
                    parameters={},
                )
            ]
        }


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
async def test_extra_tools_indexed_at_connect_with_runtime():
    """Extra (non-MCP) tools must be indexed at connect() even when the MCP
    runtime owns MCP indexing (_skip_mcp_reindex=True); connect() must not
    index MCP itself."""
    client = FakeMCPClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('fetch', {'command': 'echo'})),
        owns_client=False,
    )
    tm = _make_tool_manager(client, runtime)
    tm.extra_tools.append(_FakeExtraTool(name='mem', tool='do'))
    await tm.connect()

    keys = [t['tool_name'] for t in await tm.get_tools()]
    assert 'mem---do' in keys
    assert not any(k.startswith('fetch---') for k in keys)

    runtime.bind_tool_manager(tm)
    await runtime.start()
    await runtime.sync_tools()
    keys = [t['tool_name'] for t in await tm.get_tools()]
    assert 'mem---do' in keys
    assert 'fetch---demo_tool' in keys


@pytest.mark.asyncio
async def test_reindex_does_not_resurface_degraded_mcp():
    """Registering an extra tool later (as load_memory does) triggers a reindex;
    it must not resurface tools for servers the runtime hid (degraded), nor
    duplicate healthy MCP tools."""
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
    assert any('fetch---' in t['tool_name'] for t in await tm.get_tools())

    # Degrade the server; the runtime hides its tools while keeping the session.
    await runtime.record_failure(
        'fetch', 'call_tool', 'Connection closed',
        exc=ConnectionError('Connection closed'))
    assert runtime.get_server('fetch').status == 'degraded'
    assert client.is_connected('fetch')
    assert not any('fetch---' in t['tool_name'] for t in await tm.get_tools())

    tm.extra_tools.append(_FakeExtraTool(name='mem', tool='do'))
    await tm.reindex_tool()

    keys = [t['tool_name'] for t in await tm.get_tools()]
    assert 'mem---do' in keys
    assert not any(k.startswith('fetch---') for k in keys)


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
    grouped = ExceptionGroup('mcp', [ConnectionError('broken pipe')])
    assert classify_mcp_failure(grouped) == 'hard'


@pytest.mark.asyncio
async def test_dead_server_group_is_a_tool_error_not_a_failed_turn():
    client = FakeMCPClient()
    client.call_group = True
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

    result = await tm.single_call_tool({
        'tool_name': 'fetch---demo_tool',
        'arguments': {},
    })
    assert result['is_error'] is True
    assert runtime.get_server('fetch').status == 'degraded'


@pytest.mark.asyncio
async def test_cancelled_tool_call_still_propagates():
    client = FakeMCPClient()
    client.call_cancel = True
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

    with pytest.raises(asyncio.CancelledError):
        await tm.single_call_tool({
            'tool_name': 'fetch---demo_tool',
            'arguments': {},
        })


@pytest.mark.asyncio
async def test_disconnect_notice_once_when_server_becomes_unusable():
    from ms_agent.agent.llm_agent import LLMAgent

    client = FakeMCPClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('fetch', {'command': 'echo'})),
        owns_client=False,
    )
    await runtime.start()
    agent = LLMAgent.__new__(LLMAgent)
    agent.mcp_runtime = runtime

    class _Sink:
        def __init__(self):
            self.texts = []

        def emit(self, event):
            self.texts.append(event.text)

    agent._event_sink = _Sink()
    exc = ConnectionError('connection closed')
    await agent._on_mcp_failure(
        'fetch', 'call_tool', 'connection closed', exc=exc)
    await agent._on_mcp_failure(
        'fetch', 'call_tool', 'connection closed', exc=exc)
    assert agent._event_sink.texts == []
    assert agent._mcp_fp is None
    assert 'fetch' in agent._mcp_reconnect_names


@pytest.mark.asyncio
async def test_timeout_notice_waits_for_the_degrade_threshold():
    from ms_agent.agent.llm_agent import LLMAgent

    client = FakeMCPClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('fetch', {'command': 'echo'})),
        owns_client=False,
    )
    await runtime.start()
    agent = LLMAgent.__new__(LLMAgent)
    agent.mcp_runtime = runtime

    class _Sink:
        def __init__(self):
            self.texts = []

        def emit(self, event):
            self.texts.append(event.text)

    agent._event_sink = _Sink()
    for _ in range(DEGRADED_FAILURE_THRESHOLD - 1):
        await agent._on_mcp_failure(
            'fetch', 'call_tool', 'timeout', exc=TimeoutError('timeout'))
    assert agent._event_sink.texts == []
    await agent._on_mcp_failure(
        'fetch', 'call_tool', 'timeout', exc=TimeoutError('timeout'))
    assert agent._event_sink.texts == []


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
    import asyncio

    from ms_agent.tools.mcp_client import MCPClient

    client = MCPClient({'mcpServers': {}})

    # Stand in for a live server: an owner task parked on its shutdown event,
    # exactly as _own_server parks once its transport is open.
    shutdown = asyncio.Event()
    closed = asyncio.Event()

    async def _owner():
        try:
            await shutdown.wait()
        finally:
            client.sessions.pop('fake', None)
            closed.set()

    client.sessions['fake'] = object()
    client._server_shutdown['fake'] = shutdown
    client._server_tasks['fake'] = asyncio.create_task(_owner())
    await asyncio.sleep(0)

    await client.__aexit__(None, None, None)
    assert closed.is_set()
    assert 'fake' not in client.sessions
    assert 'fake' not in client._server_tasks
    assert 'fake' not in client._server_shutdown


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


@pytest.mark.asyncio
async def test_start_probes_servers_together(monkeypatch):
    monkeypatch.setattr('ms_agent.mcp.runtime.MCP_PROBE_TIMEOUT', 1)

    class SlowClient(FakeMCPClient):

        async def connect_single_server(self, server_name: str, server_config: dict,
                                        **kwargs):
            await asyncio.sleep(0.2)
            return await super().connect_single_server(
                server_name, server_config, **kwargs)

    client = SlowClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(
            ('a', {'command': 'echo'}),
            ('b', {'command': 'echo'}),
        ),
        owns_client=False,
    )
    started = asyncio.get_running_loop().time()
    await runtime.start()
    elapsed = asyncio.get_running_loop().time() - started
    assert elapsed < 0.35
    assert runtime.get_server('a').status == 'connected'
    assert runtime.get_server('b').status == 'connected'


@pytest.mark.asyncio
async def test_start_leaves_a_slow_stdio_server_running(monkeypatch):
    """A cold stdio process must not hold startup, and is not a failure yet."""
    monkeypatch.setattr('ms_agent.mcp.runtime.MCP_TURN_WAIT', 0.05)

    class HungClient(FakeMCPClient):

        def __init__(self):
            super().__init__()
            self.budgets: dict[str, float] = {}

        async def connect_single_server(self, server_name: str, server_config: dict,
                                        **kwargs):
            self.budgets[server_name] = kwargs.get('startup_timeout')
            if server_name == 'slow':
                await asyncio.Event().wait()
            return await super().connect_single_server(
                server_name, server_config, **kwargs)

    from ms_agent.tools.mcp_client import DEFAULT_SERVER_STARTUP_TIMEOUT

    client = HungClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(
            ('slow', {'command': 'echo'}),
            ('good', {'command': 'echo'}),
        ),
        owns_client=False,
    )
    started = asyncio.get_running_loop().time()
    try:
        await runtime.start()
        elapsed = asyncio.get_running_loop().time() - started
        assert elapsed < 0.4
        assert runtime.get_server('good').status == 'connected'
        slow = runtime.get_server('slow')
        assert slow.status == 'connecting'
        assert slow.last_error is None
        assert not runtime.is_callable('slow')
        assert client.is_connected('good')
        assert not client.is_connected('slow')
        assert client.budgets['slow'] == DEFAULT_SERVER_STARTUP_TIMEOUT
    finally:
        await runtime._cancel_probes()


@pytest.mark.asyncio
async def test_apply_config_does_not_reprobe_a_recorded_failure():
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
    assert client.connect_calls.count('bad') == 1
    await runtime.apply_config(ResolvedMCPConfig(mcp_servers={
        'bad': {'command': 'x'},
        'good': {'command': 'echo'},
        'extra': {'command': 'echo'},
    }))
    assert client.connect_calls.count('bad') == 1
    assert client.is_connected('extra')
    assert runtime.get_server('bad').status == 'error'
    assert runtime.get_server('bad').last_error == 'connect failed: bad'


@pytest.mark.asyncio
async def test_apply_config_reconnects_a_degraded_server():
    client = FakeMCPClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('fetch', {'command': 'echo'})),
        owns_client=False,
    )
    await runtime.start()
    assert client.is_connected('fetch')
    runtime.get_server('fetch').status = 'degraded'
    before = len(client.connect_calls)
    await runtime.apply_config(_resolved(('fetch', {'command': 'echo'})))
    assert len(client.connect_calls) > before
    assert runtime.get_server('fetch').status == 'connected'
    assert client.is_connected('fetch')


@pytest.mark.asyncio
async def test_apply_config_leaves_a_healthy_server_connected():
    client = FakeMCPClient()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(
            ('fetch', {'command': 'echo'}),
            ('docs', {'command': 'echo'}),
        ),
        owns_client=False,
    )
    await runtime.start()
    docs_session = client.sessions['docs']
    runtime.get_server('fetch').status = 'degraded'
    await runtime.apply_config(
        _resolved(
            ('fetch', {'command': 'echo'}),
            ('docs', {'command': 'echo'}),
        ))
    assert client.connect_calls.count('docs') == 1
    assert client.sessions['docs'] is docs_session
    assert client.connect_calls.count('fetch') == 2
    assert runtime.get_server('fetch').status == 'connected'


@pytest.mark.asyncio
async def test_remote_handshake_still_stops_at_the_probe_cap(monkeypatch):
    monkeypatch.setattr('ms_agent.mcp.runtime.MCP_PROBE_TIMEOUT', 0.05)
    monkeypatch.setattr('ms_agent.mcp.runtime.MCP_TURN_WAIT', 1)

    class HungRemote(FakeMCPClient):

        async def connect_single_server(self, server_name: str, server_config: dict,
                                        **kwargs):
            self.connect_calls.append(server_name)
            self.budget = kwargs.get('startup_timeout')
            await asyncio.Event().wait()

    client = HungRemote()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('remote', {'url': 'http://127.0.0.1:9/mcp'})),
        owns_client=False,
    )
    started = asyncio.get_running_loop().time()
    await runtime.start()
    elapsed = asyncio.get_running_loop().time() - started
    assert elapsed < 0.4
    remote = runtime.get_server('remote')
    assert remote.status == 'error'
    assert remote.last_error == '0.05秒内没有连上'
    assert client.budget == 0.05
    assert not runtime.is_callable('remote')


@pytest.mark.asyncio
async def test_stdio_that_finishes_late_joins_the_next_turn(monkeypatch):
    monkeypatch.setattr('ms_agent.mcp.runtime.MCP_TURN_WAIT', 0.05)

    class Delayed(FakeMCPClient):

        def __init__(self):
            super().__init__()
            self.release = asyncio.Event()

        async def connect_single_server(self, server_name: str, server_config: dict,
                                        **kwargs):
            if server_name == 'slow':
                await self.release.wait()
            return await super().connect_single_server(
                server_name, server_config, **kwargs)

    client = Delayed()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('slow', {'command': 'npx'})),
        owns_client=False,
    )
    try:
        await runtime.start()
        assert runtime.get_server('slow').status == 'connecting'
        assert not runtime.is_callable('slow')
        client.release.set()
        for _ in range(20):
            if runtime.get_server('slow').status == 'connected':
                break
            await asyncio.sleep(0.01)
        await runtime.refresh_for_turn(wait=False)
        assert runtime.get_server('slow').status == 'connected'
        assert runtime.is_callable('slow')
        assert runtime.get_server('slow').process_exited is False
    finally:
        await runtime._cancel_probes()


@pytest.mark.asyncio
async def test_dead_stdio_drops_tools_and_does_not_retry_forever(monkeypatch):
    monkeypatch.setattr('ms_agent.mcp.runtime.MCP_TURN_WAIT', 0.05)

    class ThenHang(FakeMCPClient):

        def __init__(self):
            super().__init__()
            self.block = False

        async def connect_single_server(self, server_name: str, server_config: dict,
                                        **kwargs):
            if self.block:
                self.connect_calls.append(server_name)
                await asyncio.Event().wait()
            return await super().connect_single_server(
                server_name, server_config, **kwargs)

    client = ThenHang()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('box', {'command': 'npx'})),
        owns_client=False,
    )
    try:
        await runtime.start()
        assert runtime.get_server('box').status == 'connected'
        client.sessions.pop('box')
        client.block = True
        await runtime.refresh_for_turn()
        state = runtime.get_server('box')
        assert state.process_exited is True
        assert state.status == 'connecting'
        assert state.tool_count == 0
        assert not runtime.is_callable('box')
        started = client.connect_calls.count('box')
        await runtime.refresh_for_turn()
        assert client.connect_calls.count('box') == started
    finally:
        await runtime._cancel_probes()


@pytest.mark.asyncio
async def test_dead_stdio_is_noticed_while_the_session_is_still_registered():
    """The child can be gone before the owner task drops the session."""

    class StillRegistered(FakeMCPClient):

        def __init__(self):
            super().__init__()
            self._dead = False

        def stdio_process_exited(self, name):
            del name
            if self._dead:
                self._dead = False
                return True
            return False

    client = StillRegistered()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('box', {'command': 'npx'})),
        owns_client=False,
    )
    await runtime.start()
    assert client.is_connected('box')
    client._dead = True
    await runtime.refresh_for_turn()
    assert client.connect_calls.count('box') == 2
    assert runtime.get_server('box').status == 'connected'
    await runtime.refresh_for_turn()
    assert client.connect_calls.count('box') == 2


@pytest.mark.asyncio
async def test_a_failed_reconnect_stays_failed_until_retry():
    class ThenFail(FakeMCPClient):

        def __init__(self):
            super().__init__()
            self.fail = False

        async def connect_single_server(self, server_name: str, server_config: dict,
                                        **kwargs):
            if self.fail:
                self.connect_calls.append(server_name)
                raise ConnectionError('gone')
            return await super().connect_single_server(
                server_name, server_config, **kwargs)

    client = ThenFail()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=_resolved(('box', {'command': 'npx'})),
        owns_client=False,
    )
    await runtime.start()
    client.sessions.pop('box')
    client.fail = True
    await runtime.refresh_for_turn()
    state = runtime.get_server('box')
    assert state.status == 'error'
    assert state.process_exited is True
    assert state.last_error == 'gone'
    assert not runtime.is_callable('box')
    failed = client.connect_calls.count('box')
    await runtime.refresh_for_turn()
    assert client.connect_calls.count('box') == failed

    client.fail = False
    await runtime.retry_server('box')
    assert runtime.get_server('box').status == 'connected'
    assert runtime.get_server('box').process_exited is False
    assert runtime.is_callable('box')
    assert client.connect_calls.count('box') == failed + 1
