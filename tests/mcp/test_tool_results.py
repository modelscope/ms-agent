# Copyright (c) ModelScope Contributors. All rights reserved.
"""MCP tool results must survive normalization into agent tool messages."""
import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from mcp.types import (CallToolResult, EmbeddedResource, ImageContent,
                       TextContent, TextResourceContents)
from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.llm.utils import Message, ToolResult
from ms_agent.tools.mcp_client import MCPClient
from ms_agent.tools.tool_manager import ToolManager


PAYLOAD = {'answer': 42, 'label': '中文', 'items': [True, None, 1.5]}


async def call_result(response, output_dir=None):
    client = MCPClient()
    if output_dir is not None:
        client.output_dir = str(output_dir)
    session = SimpleNamespace(call_tool=AsyncMock(return_value=response))
    client.sessions['demo'] = session
    raw = await client.call_tool('demo', 'lookup', {'query': 'test'})
    session.call_tool.assert_awaited_once_with('lookup', {'query': 'test'})
    return raw


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [PAYLOAD, {}])
@pytest.mark.parametrize('content', [
    [],
    [TextContent(type='text', text='')],
    [TextContent(type='text', text='  ')],
])
async def test_structured_result_without_readable_text(payload, content):
    response = CallToolResult(content=content, structuredContent=payload)
    result = ToolResult.from_raw(await call_result(response))
    assert json.loads(result.text) == payload
    assert result.extra['structuredContent'] == payload
    assert not result.is_error
    if payload:
        assert '中文' in result.text


@pytest.mark.asyncio
async def test_structured_result_preserves_image_attachment(tmp_path):
    response = CallToolResult(
        content=[ImageContent(type='image', data='AA==', mimeType='image/png')],
        structuredContent=PAYLOAD)
    result = ToolResult.from_raw(await call_result(response, tmp_path))
    structured_text, media_text = result.text.split('\n\n', 1)
    assert json.loads(structured_text) == PAYLOAD
    assert 'Image returned' in media_text
    assert result.extra['structuredContent'] == PAYLOAD
    assert result.attachments[0]['media_type'] == 'image/png'
    assert (tmp_path / result.attachments[0]['path']).read_bytes() == b'\x00'


@pytest.mark.asyncio
async def test_existing_text_is_not_duplicated_by_structured_result():
    response = CallToolResult(
        content=[TextContent(type='text', text='The answer is 42.')],
        structuredContent=PAYLOAD)
    result = ToolResult.from_raw(await call_result(response))
    assert result.text == 'The answer is 42.'
    assert result.extra['structuredContent'] == PAYLOAD


@pytest.mark.asyncio
@pytest.mark.parametrize('legacy', [False, True])
async def test_text_only_result_keeps_its_original_return_type(legacy):
    content = [TextContent(type='text', text='first'),
               TextContent(type='text', text='second')]
    response = (SimpleNamespace(content=content, isError=False) if legacy
                else CallToolResult(content=content))
    assert await call_result(response) == 'first\n\nsecond'


@pytest.mark.asyncio
async def test_empty_unstructured_result_stays_empty():
    assert await call_result(CallToolResult(content=[])) == ''


def resource_block():
    return EmbeddedResource(type='resource', resource=TextResourceContents(
        uri='file:///result.json', mimeType='application/json', text='{"x": 1}'))


@pytest.mark.asyncio
async def test_resource_only_result_keeps_its_original_shape():
    resource = resource_block()
    assert await call_result(CallToolResult(content=[resource])) == {
        'text': resource.resource.model_dump_json(by_alias=True),
        'resources': [resource.resource.model_dump(mode='json', by_alias=True)],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize('with_text', [False, True])
async def test_structured_result_preserves_embedded_resources(with_text):
    resource = resource_block()
    content = [resource]
    if with_text:
        content.insert(0, TextContent(type='text', text='See attached result.'))
    result = ToolResult.from_raw(await call_result(CallToolResult(
        content=content, structuredContent=PAYLOAD)))
    assert result.resources == [resource.resource.model_dump(mode='json', by_alias=True)]
    assert result.extra['structuredContent'] == PAYLOAD
    first, remainder = result.text.split('\n\n', 1)
    if with_text:
        assert first == 'See attached result.'
    else:
        assert json.loads(first) == PAYLOAD
    assert remainder == resource.resource.model_dump_json(by_alias=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('with_text', [False, True])
async def test_structured_error_remains_an_error(with_text):
    payload = {'reason': 'invalid query'}
    response = CallToolResult(
        isError=True, structuredContent=payload,
        content=[TextContent(type='text', text='Query rejected.')] if with_text else [])
    result = ToolResult.from_raw(await call_result(response))
    assert result.is_error
    assert result.extra['structuredContent'] == payload
    prefix = 'execute tool call error: [demo]lookup, '
    assert result.text.startswith(prefix)
    detail = result.text[len(prefix):]
    if with_text:
        assert detail == 'Query rejected.'
    else:
        assert json.loads(detail) == payload


@pytest.mark.asyncio
async def test_legacy_error_response_keeps_its_original_shape():
    response = SimpleNamespace(isError=True, content=['first', 'second'])
    assert await call_result(response) == {
        'result': 'execute tool call error: [demo]lookup, first\n\nsecond',
        'is_error': True,
    }


async def make_manager(client):
    manager = ToolManager(config=OmegaConf.create({'tools': {}}), mcp_client=client)
    await manager.connect()
    return manager


def tool_call(name='demo---lookup'):
    return {'id': 'call-1', 'tool_name': name, 'arguments': '{}'}


@pytest.mark.asyncio
async def test_manager_bounds_model_text_without_discarding_structured_data(monkeypatch):
    payload = {'body': 'x' * 1000}
    client = MCPClient()
    client.sessions['demo'] = SimpleNamespace(
        call_tool=AsyncMock(return_value=CallToolResult(content=[], structuredContent=payload)),
        list_tools=AsyncMock(return_value=SimpleNamespace(tools=[])))
    manager = await make_manager(client)
    manager._tool_index['demo---lookup'] = (client, 'demo', {})
    monkeypatch.setenv('MAX_TOOL_OUTPUT_LEN', '100')
    result = ToolResult.from_raw(await manager.single_call_tool(tool_call()))
    assert 'Output truncated' in result.text
    assert len(result.text) < 1000
    assert result.extra['structuredContent'] == payload


@pytest.mark.asyncio
async def test_resolved_tool_name_keeps_structured_result_text():
    client = MCPClient()
    client.sessions['demo'] = SimpleNamespace(
        call_tool=AsyncMock(return_value=CallToolResult(content=[], structuredContent=PAYLOAD)),
        list_tools=AsyncMock(return_value=SimpleNamespace(tools=[])))
    manager = await make_manager(client)
    manager._tool_index['demo---lookup'] = (client, 'demo', {})
    result = ToolResult.from_raw(await manager.single_call_tool(tool_call('demo')))
    note, text = result.text.split('\n', 1)
    assert 'resolved to "demo---lookup"' in note
    assert json.loads(text) == PAYLOAD


@pytest.mark.asyncio
async def test_injected_mcp_client_can_use_existing_text_envelope(monkeypatch):
    # Injected clients may use the other envelope supported by ToolResult.
    payload = {'body': 'x' * 1000}
    client = MCPClient()
    client.call_tool = AsyncMock(return_value={
        'result': None, 'text': json.dumps(payload), 'structuredContent': payload})
    manager = await make_manager(client)
    manager._tool_index['demo---lookup'] = (client, 'demo', {})
    monkeypatch.setenv('MAX_TOOL_OUTPUT_LEN', '100')
    result = ToolResult.from_raw(await manager.single_call_tool(tool_call()))
    assert not result.is_error
    assert 'Output truncated' in result.text
    assert result.extra['structuredContent'] == payload


# A real stdio server: unlike FastMCP's default conversion, it deliberately
# returns structuredContent without the optional backward-compatible text.
STDIO_SERVER = '''
import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, Tool

server = Server('structured-result-test')

@server.list_tools()
async def list_tools():
    return [Tool(name='lookup', description='Return structured data',
                 inputSchema={'type': 'object', 'properties': {}})]

@server.call_tool()
async def call_tool(name, arguments):
    return CallToolResult(content=[], structuredContent={'answer': 42, 'label': '中文'})

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

asyncio.run(main())
'''


@pytest.mark.asyncio
async def test_stdio_structured_result_reaches_agent_tool_message():
    client = MCPClient(mcp_config={'mcpServers': {'demo': {
        'command': sys.executable, 'args': ['-c', STDIO_SERVER]}}})
    try:
        await asyncio.wait_for(client.connect(), timeout=15)
        manager = await make_manager(client)
        assert any(tool['tool_name'] == 'demo---lookup' for tool in await manager.get_tools())
        agent = LLMAgent.__new__(LLMAgent)
        agent.tool_manager = manager
        agent.log_output = Mock()
        agent._event_sink = None
        messages = [Message(role='assistant', tool_calls=[tool_call()])]
        await asyncio.wait_for(agent.parallel_tool_call(messages), timeout=10)
        message = messages[-1]
        assert message.role == 'tool'
        assert message.tool_call_id == 'call-1'
        assert not message.is_error
        assert json.loads(message.content) == {'answer': 42, 'label': '中文'}
        # Providers receive the JSON as content, not an unsupported API field.
        wire = message.to_dict_clean()
        assert wire['content'] == message.content
        assert 'structuredContent' not in wire
    finally:
        await client.cleanup()
