"""Unit tests for A2A components (no external processes or SDK needed)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ms_agent.a2a.errors import (
    A2AServerError,
    AgentLoadError,
    ConfigError,
    LLMError,
    MaxTasksError,
    RateLimitError,
    TaskNotFoundError,
    wrap_a2a_error,
)
from ms_agent.a2a.translator import (
    a2a_message_to_ms_messages,
    collect_full_response,
    extract_text_from_a2a_message,
    ms_messages_to_text,
)
from ms_agent.llm.utils import Message


# ======================================================================
# Error mapping tests
# ======================================================================

class TestErrorMapping:

    def test_task_not_found(self):
        err = TaskNotFoundError('task_abc')
        assert err.code == -32001
        assert 'task_abc' in str(err.data)

    def test_agent_load_error(self):
        err = AgentLoadError('config parse failure')
        assert err.code == -32002
        assert 'config parse failure' in err.data['detail']

    def test_llm_error(self):
        err = LLMError('timeout')
        assert err.code == -32003

    def test_rate_limit_error(self):
        err = RateLimitError('too many requests')
        assert err.code == -32004

    def test_config_error(self):
        err = ConfigError('missing key')
        assert err.code == -32005

    def test_max_tasks_error(self):
        err = MaxTasksError(8)
        assert err.code == -32006
        assert err.data['max'] == 8

    def test_wrap_a2a_server_error(self):
        err = LLMError('timeout')
        result = wrap_a2a_error(err)
        assert result['code'] == -32003
        assert 'timeout' in result['data']['detail']

    def test_wrap_file_not_found(self):
        result = wrap_a2a_error(FileNotFoundError('/path'))
        assert result['code'] == -32002

    def test_wrap_value_error(self):
        result = wrap_a2a_error(ValueError('bad param'))
        assert result['code'] == -32602

    def test_wrap_unknown_error(self):
        result = wrap_a2a_error(RuntimeError('unexpected'))
        assert result['code'] == -32603
        assert 'unexpected' in result['data']['detail']

    def test_wrap_permission_error(self):
        result = wrap_a2a_error(PermissionError('denied'))
        assert result['code'] == -32000

    def test_wrap_timeout_error(self):
        result = wrap_a2a_error(TimeoutError('timed out'))
        assert result['code'] == -32004


# ======================================================================
# Translator tests
# ======================================================================

class TestTranslator:

    def test_extract_text_from_text_part(self):
        msg = MagicMock()
        part = MagicMock()
        part.root = MagicMock(type='text', text='Hello world')
        msg.parts = [part]
        assert extract_text_from_a2a_message(msg) == 'Hello world'

    def test_extract_text_multiple_parts(self):
        msg = MagicMock()
        p1 = MagicMock()
        p1.root = MagicMock(type='text', text='Part A')
        p2 = MagicMock()
        p2.root = MagicMock(type='text', text='Part B')
        msg.parts = [p1, p2]
        result = extract_text_from_a2a_message(msg)
        assert 'Part A' in result
        assert 'Part B' in result

    def test_extract_text_file_part(self):
        msg = MagicMock()
        part = MagicMock()
        file_obj = MagicMock(spec=['name', 'mimeType', 'uri'])
        file_obj.name = 'test.txt'
        file_obj.mimeType = 'text/plain'
        file_obj.uri = 'file:///test.txt'
        part.root = MagicMock(spec=['type', 'file'])
        part.root.type = 'file'
        part.root.file = file_obj
        msg.parts = [part]
        result = extract_text_from_a2a_message(msg)
        assert 'test.txt' in result

    def test_extract_text_none_message(self):
        assert extract_text_from_a2a_message(None) == ''

    def test_extract_text_no_parts(self):
        msg = MagicMock()
        msg.parts = None
        result = extract_text_from_a2a_message(msg)
        assert isinstance(result, str)

    def test_a2a_message_to_ms_messages(self):
        msg = MagicMock()
        part = MagicMock()
        part.root = MagicMock(type='text', text='Hello')
        msg.parts = [part]
        result = a2a_message_to_ms_messages(msg)
        assert len(result) == 1
        assert result[0].role == 'user'
        assert result[0].content == 'Hello'

    def test_a2a_message_to_ms_messages_appends(self):
        existing = [Message(role='system', content='You are helpful')]
        msg = MagicMock()
        part = MagicMock()
        part.root = MagicMock(type='text', text='Query')
        msg.parts = [part]
        result = a2a_message_to_ms_messages(msg, existing)
        assert len(result) == 2
        assert result is existing

    def test_ms_messages_to_text(self):
        msgs = [
            Message(role='user', content='Hi'),
            Message(role='assistant', content='Hello back!'),
        ]
        assert ms_messages_to_text(msgs) == 'Hello back!'

    def test_ms_messages_to_text_empty(self):
        assert ms_messages_to_text([]) == ''

    def test_ms_messages_to_text_no_assistant(self):
        msgs = [Message(role='user', content='Hi')]
        assert ms_messages_to_text(msgs) == ''

    def test_collect_full_response(self):
        msgs = [
            Message(role='user', content='Hi'),
            Message(role='assistant', content='Part 1'),
            Message(role='tool', content='tool output', tool_call_id='tc_1'),
            Message(role='assistant', content='Part 2'),
        ]
        result = collect_full_response(msgs)
        assert 'Part 1' in result
        assert 'Part 2' in result

    def test_collect_full_response_empty(self):
        assert collect_full_response([]) == ''


# ======================================================================
# Session store tests
# ======================================================================

class TestSessionStore:

    @pytest.mark.asyncio
    async def test_get_or_create_missing_config(self):
        from ms_agent.a2a.session_store import A2AAgentStore
        store = A2AAgentStore(
            config_path='/nonexistent/config.yaml',
            max_tasks=2,
        )
        with pytest.raises(ConfigError):
            await store.get_or_create('task_1')

    @pytest.mark.asyncio
    async def test_get_returns_none_for_unknown(self):
        from ms_agent.a2a.session_store import A2AAgentStore
        store = A2AAgentStore(config_path='/tmp/fake.yaml')
        assert store.get('unknown_task') is None

    @pytest.mark.asyncio
    async def test_close_all_empty(self):
        from ms_agent.a2a.session_store import A2AAgentStore
        store = A2AAgentStore(config_path='/tmp/fake.yaml')
        await store.close_all()


# ======================================================================
# Client manager tests
# ======================================================================

class TestClientManager:

    @pytest.mark.asyncio
    async def test_call_unknown_agent(self):
        from ms_agent.a2a.client import A2AClientManager
        mgr = A2AClientManager({})
        result = await mgr.call_agent('unknown', 'hi')
        assert 'Error' in result
        assert 'not configured' in result

    @pytest.mark.asyncio
    async def test_call_agent_no_url(self):
        from ms_agent.a2a.client import A2AClientManager
        mgr = A2AClientManager({'test_agent': {'description': 'test'}})
        result = await mgr.call_agent('test_agent', 'hi')
        assert 'Error' in result
        assert 'no URL' in result

    @pytest.mark.asyncio
    async def test_list_agents(self):
        from ms_agent.a2a.client import A2AClientManager
        mgr = A2AClientManager({
            'agent_a': {'url': 'http://a'},
            'agent_b': {'url': 'http://b'},
        })
        agents = mgr.list_agents()
        assert 'agent_a' in agents
        assert 'agent_b' in agents

    @pytest.mark.asyncio
    async def test_close_all(self):
        from ms_agent.a2a.client import A2AClientManager
        mgr = A2AClientManager({})
        await mgr.close_all()

    def test_build_auth_headers_bearer(self):
        from ms_agent.a2a.client import A2AClientManager
        headers = A2AClientManager._build_auth_headers({
            'auth': {'type': 'bearer', 'token': 'my_token'}
        })
        assert headers['Authorization'] == 'Bearer my_token'

    def test_build_auth_headers_no_auth(self):
        from ms_agent.a2a.client import A2AClientManager
        headers = A2AClientManager._build_auth_headers({})
        assert headers == {}


# ======================================================================
# Tool tests
# ======================================================================

class TestA2AAgentTool:

    def test_from_config_no_a2a_agents(self):
        from ms_agent.tools.a2a_agent_tool import A2AAgentTool
        config = MagicMock(spec=[])
        result = A2AAgentTool.from_config(config)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_tools(self):
        from ms_agent.tools.a2a_agent_tool import A2AAgentTool
        config = MagicMock()
        tool = A2AAgentTool(config, a2a_agents_config={
            'my_agent': {
                'url': 'http://localhost:9999',
                'description': 'Test agent',
            }
        })
        tools = await tool.get_tools()
        assert 'a2a_my_agent' in tools
        assert len(tools['a2a_my_agent']) == 1
        assert tools['a2a_my_agent'][0]['tool_name'] == 'my_agent'

    @pytest.mark.asyncio
    async def test_call_tool_missing_query(self):
        from ms_agent.tools.a2a_agent_tool import A2AAgentTool
        config = MagicMock()
        tool = A2AAgentTool(config, a2a_agents_config={
            'my_agent': {
                'url': 'http://localhost:9999',
                'description': 'Test agent',
            }
        })
        result = await tool.call_tool(
            'a2a_my_agent', tool_name='my_agent', tool_args={})
        assert 'Error' in result
        assert 'query' in result
