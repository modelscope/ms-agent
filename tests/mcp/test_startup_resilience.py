"""Startup must bound readiness and isolate optional capabilities."""
import asyncio
import copy
from unittest.mock import AsyncMock

import pytest
from mcp import ListToolsResult
from omegaconf import OmegaConf

from ms_agent.tools.mcp_client import MCPClient


@pytest.mark.asyncio
@pytest.mark.parametrize('env', [None, {}, {'DEMO': 'value'}])
async def test_single_server_env_and_initial_listing(monkeypatch, env):
    client = MCPClient()
    session = AsyncMock()
    session.list_tools.return_value = ListToolsResult(tools=[])
    opened = AsyncMock(return_value=session)
    monkeypatch.setattr(client, '_open_session', opened)
    config = {'command': 'python', 'args': [], 'startup_timeout': .1}
    if env is not None:
        config['env'] = env
    before = copy.deepcopy(config)
    try:
        await client.connect_single_server('demo', config)
        await client.get_tools()
        assert config == before
        assert session.list_tools.await_count == 1
    finally:
        await client.cleanup()


@pytest.mark.asyncio
async def test_config_errors_isolated_and_source_unchanged(monkeypatch):
    config = {'mcpServers': {'bad': {'command': 'x', 'env': 5},
                            'good': {'command': 'x', 'env': {}}}}
    before = copy.deepcopy(config)
    client = MCPClient(config)
    session = AsyncMock()
    session.list_tools.return_value = ListToolsResult(tools=[])
    monkeypatch.setattr(client, '_open_session', AsyncMock(return_value=session))
    try:
        failures = await client.connect(failure_policy='skip')
        assert [name for name, _ in failures] == ['bad']
        assert client.is_connected('good')
        assert config == before
    finally:
        await client.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['ok', 'initialize', 'list_tools', 'ignore_term', 'exit', 'cancel'])
async def test_real_stdio_lifecycle(tmp_path, mode):
    import os
    import sys
    from pathlib import Path

    pidfile = tmp_path / 'child.pid'
    fixture = Path(__file__).parent / 'fixtures' / 'stdio_server.py'
    client = MCPClient()
    config = {'command': sys.executable,
              'args': [str(fixture), 'initialize' if mode == 'cancel' else mode, str(pidfile)],
              # Successful startup is not a performance assertion; leave room
              # for process scheduling while the timeout cases stay bounded.
              'startup_timeout': 5 if mode in ('ok', 'exit', 'cancel') else .5,
              'env': {'TOKEN': 'secret-value'}}
    task = asyncio.create_task(client.connect_single_server('real', config))
    try:
        if mode == 'cancel':
            for _ in range(100):
                if pidfile.exists():
                    break
                await asyncio.sleep(.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif mode == 'ok':
            await task
            assert [t['tool_name'] for t in await client.get_tools_for_server('real')] == ['demo']
        elif mode == 'exit':
            with pytest.raises(Exception):
                await task
            assert '403' in client.startup_failures['real']
            assert 'secret-value' not in client.startup_failures['real']
        else:
            with pytest.raises(TimeoutError):
                await task
    finally:
        await client.cleanup()
    assert pidfile.exists(), 'child actually started'
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)
    assert not client._server_tasks
    assert not client.sessions


@pytest.mark.asyncio
async def test_strict_client_still_raises():
    client = MCPClient({'mcpServers': {'bad': {'command': '/no-such-mcp'}}})
    try:
        with pytest.raises(RuntimeError, match='Connect bad failed'):
            await client.connect()
    finally:
        await client.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize('policy', ['skip', 'fail_fast'])
async def test_initial_list_failure_runtime_does_not_deadlock(policy):
    from ms_agent.config.mcp_schema import ResolvedMCPConfig
    from ms_agent.mcp.runtime import MCPRuntime
    client = AsyncMock()
    client.is_connected = lambda _: False
    client.list_connected_servers = lambda: []
    client.get_tools_for_server.side_effect = ConnectionError('closed')
    runtime = MCPRuntime(mcp_client=client, connect_policy=policy,
                         config=ResolvedMCPConfig(mcp_servers={'x': {'command': 'x'}}))
    if policy == 'fail_fast':
        with pytest.raises(ConnectionError):
            await asyncio.wait_for(runtime.start(), .5)
        assert not runtime.is_started
        return
    await asyncio.wait_for(runtime.start(), .5)
    assert runtime.is_started
    assert runtime.get_server('x').status == 'error'


@pytest.mark.asyncio
async def test_runtime_cancel_is_not_ready():
    from ms_agent.config.mcp_schema import ResolvedMCPConfig
    from ms_agent.mcp.runtime import MCPRuntime
    client = AsyncMock()
    client.is_connected = lambda _: False
    client.list_connected_servers = lambda: []
    entered = asyncio.Event()
    async def connect(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()
    client.connect_single_server.side_effect = connect
    runtime = MCPRuntime(mcp_client=client,
                         config=ResolvedMCPConfig(mcp_servers={'x': {'command': 'x'}}))
    task = asyncio.create_task(runtime.start())
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not runtime.is_started
    assert not runtime._probe_tasks
    client.disconnect_server.assert_awaited_once()


@pytest.mark.asyncio
async def test_real_agent_preparation_reaches_first_model_token(tmp_path, monkeypatch):
    from ms_agent.agent.llm_agent import LLMAgent
    from ms_agent.llm.utils import Message
    from ms_agent.ui.events import RecordingSink, ContentDelta, Notice

    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path / 'home'))
    sink = RecordingSink()
    config = OmegaConf.create({
        'llm': {'service': 'openai', 'model': 'test', 'openai_api_key': 'test'},
        'generation_config': {}, 'max_chat_round': 1, 'enable_snapshots': False,
        'output_dir': str(tmp_path), 'work_dir': str(tmp_path),
        'callbacks': [], 'skills': {'enabled': False},
        'tools': {'code_executor': {'mcp': False, 'implementation': 'python_env',
                                    'include': ['shell_executor']}},
    })
    seen = []
    async def generate(self, messages, tools):
        seen.extend(messages)
        assert any(t['tool_name'] == 'code_executor---shell_executor' for t in tools)
        return iter([Message(role='assistant', content='model reached')])
    monkeypatch.setattr(LLMAgent, '_generate_response', generate)
    agent = LLMAgent(config, event_sink=sink, mcp_config={'mcpServers': {
        'broken': {'command': '/no-such-mcp'}}})
    result = await agent.run('hello', stream=True)
    async for _ in result:
        pass
    assert any(isinstance(e, ContentDelta) and e.text == 'model reached' for e in sink.events)
    assert any(isinstance(e, Notice) for e in sink.events)
    assert any('optional MCP servers are unavailable' in (m.content or '') for m in seen)


@pytest.mark.asyncio
async def test_concurrent_runtime_start_waits_until_tools_are_ready():
    from ms_agent.config.mcp_schema import ResolvedMCPConfig
    from ms_agent.mcp.runtime import MCPRuntime
    entered, release = asyncio.Event(), asyncio.Event()
    client = AsyncMock()
    client.list_connected_servers = lambda: []
    client.is_connected = lambda _: False
    client.get_tools_for_server.return_value = []
    async def connect(*args, **kwargs):
        assert kwargs['startup_timeout'] == 90
        entered.set()
        await release.wait()
    client.connect_single_server.side_effect = connect
    runtime = MCPRuntime(mcp_client=client,
                         config=ResolvedMCPConfig(mcp_servers={
                             'x': {'command': 'x', 'startup_timeout': 90}}))
    first = asyncio.create_task(runtime.start())
    await asyncio.wait_for(entered.wait(), 1)
    second = asyncio.create_task(runtime.start())
    await asyncio.sleep(0)
    assert not runtime.is_started and not second.done()
    release.set()
    await asyncio.gather(first, second)
    assert runtime.is_started
    assert client.connect_single_server.await_count == 1


@pytest.mark.asyncio
async def test_stop_timeout_retains_owner_until_cleanup(monkeypatch):
    monkeypatch.setattr('ms_agent.tools.mcp_client.SERVER_STOP_TIMEOUT', .01)
    entered, release = asyncio.Event(), asyncio.Event()
    client = MCPClient()

    async def stubborn_owner():
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()

    task = asyncio.create_task(stubborn_owner())
    client._server_tasks['slow'] = task
    client._server_shutdown['slow'] = asyncio.Event()
    client._track_task(task)
    await entered.wait()
    try:
        with pytest.raises(RuntimeError, match='cleanup timed out'):
            await client._stop_server('slow', graceful=False)
        assert client._server_tasks['slow'] is task
    finally:
        release.set()
        await client.cleanup()
    assert task.done() and not client._server_tasks and not client._live_tasks
