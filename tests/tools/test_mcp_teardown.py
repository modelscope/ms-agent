"""86121430: MCP streamable_http / jupyter teardown must not dump stack on quit."""
from __future__ import annotations

import asyncio
import base64
import inspect
import os
from datetime import timedelta
from types import SimpleNamespace

import pytest
from mcp.client.session import ClientSession

from ms_agent.tools.mcp_client import (MCPClient, _is_teardown_noise,
                                       _session_read_timeout,
                                       _tool_call_is_error, _tool_input_schema)


def test_session_read_timeout_matches_installed_client():
    value = _session_read_timeout(12)
    annotation = str(inspect.signature(
        ClientSession.__init__).parameters['read_timeout_seconds'].annotation)
    if 'timedelta' in annotation and 'float' not in annotation:
        assert value == timedelta(seconds=12)
    else:
        assert value == 12.0


def test_tool_call_error_reads_mcp2_name_then_mcp1_name():
    assert _tool_call_is_error(SimpleNamespace(is_error=True))
    assert not _tool_call_is_error(SimpleNamespace(is_error=False))
    assert _tool_call_is_error(SimpleNamespace(isError=True))
    assert not _tool_call_is_error(SimpleNamespace(isError=False))
    both = SimpleNamespace(is_error=False, isError=True)
    assert not _tool_call_is_error(both)


def test_tool_schema_reads_mcp2_name_then_mcp1_name():
    class _V2:
        input_schema = {'type': 'object', 'properties': {'msg': {}}}

    class _V1:
        inputSchema = {'type': 'object', 'properties': {'q': {}}}

    class _Neither:
        pass

    assert _tool_input_schema(_V2())['properties'] == {'msg': {}}
    assert _tool_input_schema(_V1())['properties'] == {'q': {}}
    both = _V2()
    both.inputSchema = {'type': 'object', 'properties': {'old': {}}}
    assert 'msg' in _tool_input_schema(both)['properties']
    assert _tool_input_schema(_Neither()) == {
        'type': 'object',
        'properties': {},
    }


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
async def test_quit_during_connect_does_not_leave_a_cancelled_future():
    import gc

    loop = asyncio.get_running_loop()
    logged: list[str] = []
    previous = loop.get_exception_handler()

    def _handler(_loop, context):
        logged.append(str(context.get('message', '')))

    loop.set_exception_handler(_handler)
    client = MCPClient({'mcpServers': {}})

    async def _hang(stack, server_name, **kwargs):
        await asyncio.Event().wait()

    client._open_session = _hang  # type: ignore[method-assign]
    connect = asyncio.create_task(
        client.connect_to_server('slow', startup_timeout=5))
    await asyncio.sleep(0.02)
    connect.cancel()
    with pytest.raises(asyncio.CancelledError):
        await connect
    try:
        await client.cleanup()
        gc.collect()
        await asyncio.sleep(0)
        assert all(task.done() for task in client._live_tasks)
        assert not any('never retrieved' in message for message in logged)
    finally:
        loop.set_exception_handler(previous)
        await client.cleanup()


@pytest.mark.asyncio
async def test_stdio_hook_records_the_child_process():
    import mcp.client.stdio as stdio_mod

    from ms_agent.tools.mcp_client import _install_stdio_child_hook, _stdio_child

    class _Proc:
        returncode = None

    async def fake_create(*args, **kwargs):
        del args, kwargs
        return _Proc()

    previous = stdio_mod._create_platform_compatible_process
    stdio_mod._create_platform_compatible_process = fake_create
    try:
        _install_stdio_child_hook()
        hooked = stdio_mod._create_platform_compatible_process
        holder: list = []
        token = _stdio_child.set(holder)
        try:
            process = await hooked('npx', ['-y'])
        finally:
            _stdio_child.reset(token)
        assert holder == [process]
        process.returncode = 1
        client = MCPClient({'mcpServers': {}})
        client._stdio_children['box'] = process
        assert client.stdio_process_exited('box')
    finally:
        stdio_mod._create_platform_compatible_process = previous


class _FakeSession:
    def __init__(self, response):
        self.response = response

    async def call_tool(self, tool_name, tool_args):
        return self.response


@pytest.mark.asyncio
async def test_image_audio_and_structured_results_reach_the_caller(tmp_path):
    client = MCPClient()
    client.output_dir = str(tmp_path)
    png = base64.b64encode(b'\x89PNG').decode()
    wav = base64.b64encode(b'RIFF').decode()
    client.sessions['s'] = _FakeSession(
        SimpleNamespace(
            is_error=False,
            content=[
                SimpleNamespace(type='image', data=png, mime_type='image/png'),
                SimpleNamespace(type='audio', data=wav, mimeType='audio/wav'),
            ],
            structured_content=None,
        ))
    result = await client.call_tool('s', 'shot', {})
    assert result['attachments'][0]['type'] == 'image'
    assert result['attachments'][0]['media_type'] == 'image/png'
    assert os.path.isfile(os.path.join(tmp_path, result['attachments'][0]['path']))
    assert 'Audio returned' in result['text']
    assert 'saved at' in result['text']

    client.sessions['s'] = _FakeSession(
        SimpleNamespace(
            isError=False,
            content=[],
            structuredContent={'ok': True},
        ))
    text = await client.call_tool('s', 'ping', {})
    assert '"ok": true' in text


@pytest.mark.asyncio
async def test_resource_without_model_dump_json_still_returns():
    client = MCPClient()
    client.sessions['s'] = _FakeSession(
        SimpleNamespace(
            is_error=False,
            content=[SimpleNamespace(type='resource', resource={'uri': 'file://a'})],
            structured_content=None,
        ))
    result = await client.call_tool('s', 'read', {})
    assert result['resources'] == [{'uri': 'file://a'}]


def test_output_schema_is_appended_to_the_tool_description():
    listed = SimpleNamespace(
        tools=[
            SimpleNamespace(
                name='ping',
                description='Ping.',
                input_schema={'type': 'object'},
                output_schema={'type': 'object', 'properties': {'msg': {}}},
            )
        ])
    tools = MCPClient()._filter_session_tools('mini', listed)
    assert 'Returns:' in tools[0]['description']
    assert 'msg' in tools[0]['description']
