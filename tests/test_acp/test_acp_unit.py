"""Unit tests for ACP components (no external processes needed)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ms_agent.acp.errors import (
    ACPError,
    ConfigError,
    LLMError,
    MaxSessionsError,
    RateLimitError,
    SessionNotFoundError,
    wrap_agent_error,
)
from ms_agent.acp.translator import ACPTranslator
from ms_agent.acp.session_store import ACPSessionStore
from ms_agent.llm.utils import Message


# ======================================================================
# Error mapping tests
# ======================================================================

class TestErrorMapping:

    def test_session_not_found(self):
        err = SessionNotFoundError('ses_abc')
        assert err.code == -32001
        assert 'ses_abc' in str(err.data)

    def test_wrap_acp_error(self):
        err = LLMError('timeout')
        rpc_err = wrap_agent_error(err)
        assert rpc_err.code == -32003

    def test_wrap_file_not_found(self):
        rpc_err = wrap_agent_error(FileNotFoundError('/path'))
        assert rpc_err.code == -32002

    def test_wrap_value_error(self):
        rpc_err = wrap_agent_error(ValueError('bad param'))
        assert rpc_err.code == -32602

    def test_wrap_unknown_error(self):
        rpc_err = wrap_agent_error(RuntimeError('unexpected'))
        assert rpc_err.code == -32603

    def test_max_sessions_error(self):
        err = MaxSessionsError(8)
        assert err.code == -32006
        assert err.data['max'] == 8


# ======================================================================
# Translator tests
# ======================================================================

class TestTranslator:

    def test_prompt_to_messages_text(self):
        block = MagicMock()
        block.type = 'text'
        block.text = 'Hello world'
        msgs = ACPTranslator.prompt_to_messages([block])
        assert len(msgs) == 1
        assert msgs[0].role == 'user'
        assert msgs[0].content == 'Hello world'

    def test_prompt_to_messages_multiple_blocks(self):
        b1 = MagicMock(type='text', text='Part A')
        b2 = MagicMock(type='text', text='Part B')
        msgs = ACPTranslator.prompt_to_messages([b1, b2])
        assert len(msgs) == 1
        assert 'Part A' in msgs[0].content
        assert 'Part B' in msgs[0].content

    def test_prompt_appends_to_existing(self):
        existing = [Message(role='system', content='You are helpful')]
        block = MagicMock(type='text', text='Query')
        result = ACPTranslator.prompt_to_messages([block], existing)
        assert len(result) == 2
        assert result is existing

    def test_messages_to_updates_assistant_content(self):
        t = ACPTranslator()
        msgs = [
            Message(role='assistant', content='Hello'),
        ]
        updates = t.messages_to_updates(msgs)
        assert len(updates) >= 1

    def test_messages_to_updates_delta_tracking(self):
        t = ACPTranslator()
        msgs1 = [Message(role='assistant', content='He')]
        u1 = t.messages_to_updates(msgs1)
        assert len(u1) == 1

        msgs2 = [Message(role='assistant', content='Hello')]
        u2 = t.messages_to_updates(msgs2)
        assert len(u2) == 1

    def test_messages_to_updates_reasoning(self):
        t = ACPTranslator()
        msgs = [
            Message(role='assistant', content='', reasoning_content='thinking'),
        ]
        updates = t.messages_to_updates(msgs)
        assert len(updates) >= 1

    def test_messages_to_updates_tool_call(self):
        t = ACPTranslator()
        tc = {
            'id': 'tc_1',
            'type': 'function',
            'tool_name': 'web_search',
            'arguments': '{"query": "test"}',
        }
        msgs = [Message(role='assistant', content='', tool_calls=[tc])]
        updates = t.messages_to_updates(msgs)
        assert any(hasattr(u, 'tool_call_id') for u in updates)

    def test_messages_to_updates_tool_result(self):
        t = ACPTranslator()
        t._emitted_tool_ids.add('tc_1')
        msgs = [
            Message(role='tool', content='search done', tool_call_id='tc_1'),
        ]
        updates = t.messages_to_updates(msgs)
        assert len(updates) >= 1

    def test_map_stop_reason_normal(self):
        session = MagicMock()
        session.cancelled = False
        session.agent.runtime.round = 5
        session.agent.max_chat_round = 20
        reason = ACPTranslator.map_stop_reason(session)
        assert reason == 'end_turn'

    def test_map_stop_reason_max_rounds(self):
        session = MagicMock()
        session.cancelled = False
        session.agent.runtime.round = 21
        session.agent.max_chat_round = 20
        reason = ACPTranslator.map_stop_reason(session)
        assert reason == 'max_turn_requests'

    def test_map_stop_reason_cancelled(self):
        session = MagicMock()
        session.cancelled = True
        reason = ACPTranslator.map_stop_reason(session, cancelled=True)
        assert reason == 'cancelled'

    def test_reset_turn(self):
        t = ACPTranslator()
        t._last_content_len = 100
        t._emitted_tool_ids.add('tc_1')
        t.reset_turn()
        assert t._last_content_len == 0
        assert len(t._emitted_tool_ids) == 0

    def test_build_plan_update(self):
        steps = [
            {'description': 'Search papers', 'status': 'in_progress', 'priority': 'high'},
            {'description': 'Analyze', 'status': 'pending'},
        ]
        update = ACPTranslator.build_plan_update(steps)
        assert hasattr(update, 'entries')
        assert len(update.entries) == 2


# ======================================================================
# Session store tests
# ======================================================================

class TestSessionStore:

    def test_get_nonexistent_raises(self):
        store = ACPSessionStore()
        with pytest.raises(SessionNotFoundError):
            store.get('nonexistent')

    @pytest.mark.asyncio
    async def test_max_sessions_with_no_idle(self):
        store = ACPSessionStore(max_sessions=1)
        entry = MagicMock()
        entry.is_running = True
        entry.last_activity = 0
        store._sessions['ses_1'] = entry
        with pytest.raises(MaxSessionsError):
            await store.create(
                config_path='/nonexistent/agent.yaml',
                cwd='/tmp',
            )

    def test_list_sessions_empty(self):
        store = ACPSessionStore()
        assert store.list_sessions() == []


# ======================================================================
# ACP Client Manager tests
# ======================================================================

class TestACPClientManager:

    def test_list_agents_empty(self):
        from ms_agent.acp.client import ACPClientManager
        mgr = ACPClientManager()
        assert mgr.list_agents() == []

    def test_list_agents_from_config(self):
        from ms_agent.acp.client import ACPClientManager
        cfg = {
            'openclaw': {'command': 'openclaw', 'args': ['acp'], 'description': 'test'},
            'claude': {'command': 'claude', 'args': [], 'description': 'test2'},
        }
        mgr = ACPClientManager(cfg)
        assert set(mgr.list_agents()) == {'openclaw', 'claude'}

    @pytest.mark.asyncio
    async def test_call_unconfigured_agent(self):
        from ms_agent.acp.client import ACPClientManager
        mgr = ACPClientManager()
        result = await mgr.call_agent('nonexistent', 'hello')
        assert 'not configured' in result


# ======================================================================
# ACP Agent Tool tests
# ======================================================================

class TestACPAgentTool:

    def test_from_config_none(self):
        from ms_agent.tools.acp_agent_tool import ACPAgentTool
        from omegaconf import OmegaConf
        config = OmegaConf.create({'llm': {'model': 'test'}})
        assert ACPAgentTool.from_config(config) is None

    def test_from_config_with_agents(self):
        from ms_agent.tools.acp_agent_tool import ACPAgentTool
        from omegaconf import OmegaConf
        config = OmegaConf.create({
            'llm': {'model': 'test'},
            'acp_agents': {
                'openclaw': {
                    'command': 'openclaw',
                    'args': ['acp'],
                    'description': 'OpenClaw agent',
                },
            },
        })
        tool = ACPAgentTool.from_config(config)
        assert tool is not None

    @pytest.mark.asyncio
    async def test_get_tools(self):
        from ms_agent.tools.acp_agent_tool import ACPAgentTool
        from omegaconf import OmegaConf
        config = OmegaConf.create({
            'llm': {'model': 'test'},
            'acp_agents': {
                'openclaw': {
                    'command': 'openclaw',
                    'args': ['acp'],
                    'description': 'OpenClaw coding agent',
                },
            },
        })
        tool = ACPAgentTool(config, acp_agents_config={
            'openclaw': {
                'command': 'openclaw',
                'args': ['acp'],
                'description': 'OpenClaw coding agent',
            },
        })
        tools = await tool._get_tools_inner()
        assert 'acp_openclaw' in tools
        assert len(tools['acp_openclaw']) == 1
        assert tools['acp_openclaw'][0]['description'] == 'OpenClaw coding agent'


# ======================================================================
# Config options tests
# ======================================================================

class TestConfigOptions:

    def test_build_config_options_with_model(self):
        from ms_agent.acp.config import build_config_options
        from omegaconf import OmegaConf
        cfg = OmegaConf.create({'llm': {'model': 'qwen-max'}})
        opts = build_config_options(cfg)
        assert opts is not None
        assert len(opts) == 1
        assert opts[0].id == 'model'

    def test_build_config_options_without_model(self):
        from ms_agent.acp.config import build_config_options
        from omegaconf import OmegaConf
        cfg = OmegaConf.create({})
        opts = build_config_options(cfg)
        assert opts is None

    def test_apply_config_option_model(self):
        from ms_agent.acp.config import apply_config_option
        from omegaconf import OmegaConf
        cfg = OmegaConf.create({'llm': {'model': 'qwen-max'}})
        result = apply_config_option(cfg, 'model', 'gpt-4o')
        assert result is True
        assert cfg.llm.model == 'gpt-4o'

    def test_apply_config_option_unknown(self):
        from ms_agent.acp.config import apply_config_option
        from omegaconf import OmegaConf
        cfg = OmegaConf.create({'llm': {'model': 'qwen-max'}})
        result = apply_config_option(cfg, 'unknown_option', 'value')
        assert result is False


# ======================================================================
# Permission policy tests
# ======================================================================

class TestPermissionPolicy:

    def test_auto_approve_never_asks(self):
        from ms_agent.acp.permissions import PermissionPolicy
        p = PermissionPolicy('auto_approve')
        assert p.should_ask('any_tool') is False
        assert p.auto_decision('any_tool') == 'allow_once'

    def test_always_ask(self):
        from ms_agent.acp.permissions import PermissionPolicy
        p = PermissionPolicy('always_ask')
        assert p.should_ask('web_search') is True
        assert p.auto_decision('web_search') is None

    def test_remember_choice(self):
        from ms_agent.acp.permissions import PermissionPolicy
        p = PermissionPolicy('remember_choice')
        assert p.should_ask('web_search') is True
        p.record_choice('web_search', True)
        assert p.should_ask('web_search') is False
        assert 'allow' in p.auto_decision('web_search')

    def test_remember_deny(self):
        from ms_agent.acp.permissions import PermissionPolicy
        p = PermissionPolicy('remember_choice')
        p.record_choice('dangerous_tool', False)
        assert 'deny' in p.auto_decision('dangerous_tool')

    def test_reset(self):
        from ms_agent.acp.permissions import PermissionPolicy
        p = PermissionPolicy('remember_choice')
        p.record_choice('tool_a', True)
        p.reset()
        assert p.should_ask('tool_a') is True


# ======================================================================
# Registry tests
# ======================================================================

class TestRegistry:

    def test_generate_manifest(self):
        from ms_agent.acp.registry import generate_agent_manifest
        manifest = generate_agent_manifest(
            config_path='/path/to/config.yaml',
            output_path=None,
        )
        assert manifest['name'] == 'ms-agent'
        assert manifest['protocol'] == 'acp'
        assert manifest['protocolVersion'] == 1
        assert manifest['transport']['type'] == 'stdio'
        assert '--config' in manifest['transport']['args']
        assert '/path/to/config.yaml' in manifest['transport']['args']

    def test_generate_manifest_without_config(self):
        from ms_agent.acp.registry import generate_agent_manifest
        manifest = generate_agent_manifest(output_path=None)
        assert manifest['transport']['args'] == ['acp']
