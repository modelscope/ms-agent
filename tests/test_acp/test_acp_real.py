"""Real integration tests for ACP modules — NO mocks.

Validates every ACP component using real objects, real SDK types,
real agent configs, and real subprocess spawning.
"""

import asyncio
import json
import os
import sys
import tempfile
import time

import pytest

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_CONFIG = os.path.join(_REPO_ROOT, 'ms_agent', 'agent', 'agent.yaml')
_ACP_TEST_CONFIG = os.environ.get('ACP_TEST_CONFIG', _DEFAULT_CONFIG)

sys.path.insert(0, _REPO_ROOT)


# ======================================================================
# 1. Error mapping — real exception objects, real RequestError
# ======================================================================

class TestErrorMappingReal:

    def test_all_custom_errors_have_correct_codes(self):
        from ms_agent.acp.errors import (
            SessionNotFoundError, ResourceNotFoundError, LLMError,
            RateLimitError, ConfigError, MaxSessionsError,
        )
        cases = [
            (SessionNotFoundError('ses_x'), -32001),
            (ResourceNotFoundError('/tmp/x'), -32002),
            (LLMError('timeout'), -32003),
            (RateLimitError('too fast'), -32004),
            (ConfigError('bad yaml'), -32005),
            (MaxSessionsError(4), -32006),
        ]
        for err, expected_code in cases:
            assert err.code == expected_code, f'{type(err).__name__} code mismatch'
            assert err.message, f'{type(err).__name__} should have a message'
            assert isinstance(err.data, dict), f'{type(err).__name__} data should be dict'

    def test_wrap_agent_error_produces_real_request_error(self):
        from acp import RequestError
        from ms_agent.acp.errors import wrap_agent_error, LLMError

        rpc = wrap_agent_error(LLMError('model down'))
        assert isinstance(rpc, RequestError)
        assert rpc.code == -32003

    def test_wrap_python_stdlib_exceptions(self):
        from acp import RequestError
        from ms_agent.acp.errors import wrap_agent_error

        for exc, expected_code in [
            (FileNotFoundError('/no'), -32002),
            (PermissionError('denied'), -32000),
            (TimeoutError('slow'), -32004),
            (ValueError('bad'), -32602),
        ]:
            rpc = wrap_agent_error(exc)
            assert isinstance(rpc, RequestError)
            assert rpc.code == expected_code, f'{type(exc).__name__} mapped to wrong code'

    def test_wrap_unknown_exception_fallback(self):
        from acp import RequestError
        from ms_agent.acp.errors import wrap_agent_error

        rpc = wrap_agent_error(RuntimeError('surprise'))
        assert isinstance(rpc, RequestError)
        assert rpc.code == -32603

    def test_wrap_already_request_error_passthrough(self):
        from acp import RequestError
        from ms_agent.acp.errors import wrap_agent_error

        original = RequestError(-32999, 'custom')
        result = wrap_agent_error(original)
        assert result is original


# ======================================================================
# 2. Translator — real ACP SDK types, real Message objects
# ======================================================================

class TestTranslatorReal:

    def test_prompt_to_messages_with_real_text_block(self):
        from acp import text_block
        from ms_agent.acp.translator import ACPTranslator
        from ms_agent.llm.utils import Message

        block = text_block('What is 2+2?')
        msgs = ACPTranslator.prompt_to_messages([block])
        assert len(msgs) == 1
        assert msgs[0].role == 'user'
        assert '2+2' in msgs[0].content

    def test_prompt_to_messages_appends_to_history(self):
        from acp import text_block
        from ms_agent.acp.translator import ACPTranslator
        from ms_agent.llm.utils import Message

        history = [Message(role='system', content='You are helpful.')]
        block = text_block('Hello')
        result = ACPTranslator.prompt_to_messages([block], history)
        assert len(result) == 2
        assert result[0].role == 'system'
        assert result[1].role == 'user'
        assert result is history

    def test_delta_tracking_content(self):
        from ms_agent.acp.translator import ACPTranslator
        from ms_agent.llm.utils import Message

        t = ACPTranslator()

        msgs1 = [Message(role='assistant', content='Hel')]
        u1 = t.messages_to_updates(msgs1)
        assert len(u1) == 1
        assert t._last_content_len == 3

        msgs2 = [Message(role='assistant', content='Hello world')]
        u2 = t.messages_to_updates(msgs2)
        assert len(u2) == 1
        assert t._last_content_len == 11

    def test_delta_tracking_reasoning(self):
        from ms_agent.acp.translator import ACPTranslator
        from ms_agent.llm.utils import Message

        t = ACPTranslator()
        msgs = [Message(role='assistant', content='', reasoning_content='thinking step 1')]
        u = t.messages_to_updates(msgs)
        assert len(u) >= 1
        assert t._last_reasoning_len == len('thinking step 1')

    def test_tool_call_emitted_once(self):
        from ms_agent.acp.translator import ACPTranslator
        from ms_agent.llm.utils import Message

        t = ACPTranslator()
        tc = {'id': 'tc_abc', 'type': 'function', 'tool_name': 'web_search',
              'arguments': '{"q": "test"}'}
        msg = Message(role='assistant', content='', tool_calls=[tc])

        u1 = t.messages_to_updates([msg])
        assert any(getattr(u, 'tool_call_id', None) == 'tc_abc' for u in u1)

        u2 = t.messages_to_updates([msg])
        assert not any(getattr(u, 'tool_call_id', None) == 'tc_abc' for u in u2)

    def test_tool_result_translation(self):
        from ms_agent.acp.translator import ACPTranslator
        from ms_agent.llm.utils import Message

        t = ACPTranslator()
        t._emitted_tool_ids.add('tc_123')
        msg = Message(role='tool', content='result data', tool_call_id='tc_123')
        updates = t.messages_to_updates([msg])
        assert len(updates) == 1

    def test_reset_turn_clears_state(self):
        from ms_agent.acp.translator import ACPTranslator

        t = ACPTranslator()
        t._last_content_len = 50
        t._last_reasoning_len = 30
        t._emitted_tool_ids.add('tc_1')
        t._completed_tool_ids.add('tc_1')
        t.reset_turn()
        assert t._last_content_len == 0
        assert t._last_reasoning_len == 0
        assert len(t._emitted_tool_ids) == 0
        assert len(t._completed_tool_ids) == 0

    def test_build_plan_update_produces_real_acp_type(self):
        from ms_agent.acp.translator import ACPTranslator
        from acp.schema import AgentPlanUpdate

        steps = [
            {'description': 'Step 1', 'status': 'completed', 'priority': 'high'},
            {'description': 'Step 2', 'status': 'in_progress'},
            {'description': 'Step 3', 'status': 'pending'},
        ]
        update = ACPTranslator.build_plan_update(steps)
        assert isinstance(update, AgentPlanUpdate)
        assert len(update.entries) == 3

    def test_map_stop_reason_end_turn(self):
        from ms_agent.acp.translator import ACPTranslator
        from types import SimpleNamespace

        session = SimpleNamespace(
            cancelled=False,
            agent=SimpleNamespace(
                runtime=SimpleNamespace(round=3),
                max_chat_round=20,
            ),
        )
        assert ACPTranslator.map_stop_reason(session) == 'end_turn'

    def test_map_stop_reason_max_rounds(self):
        from ms_agent.acp.translator import ACPTranslator
        from types import SimpleNamespace

        session = SimpleNamespace(
            cancelled=False,
            agent=SimpleNamespace(
                runtime=SimpleNamespace(round=21),
                max_chat_round=20,
            ),
        )
        assert ACPTranslator.map_stop_reason(session) == 'max_turn_requests'

    def test_map_stop_reason_cancelled(self):
        from ms_agent.acp.translator import ACPTranslator
        from types import SimpleNamespace

        session = SimpleNamespace(
            cancelled=True,
            agent=SimpleNamespace(runtime=SimpleNamespace(round=1), max_chat_round=20),
        )
        assert ACPTranslator.map_stop_reason(session) == 'cancelled'

    def test_tool_kind_mapping(self):
        from ms_agent.acp.translator import _TOOL_KIND_MAP
        assert _TOOL_KIND_MAP['code_executor'] == 'execute'
        assert _TOOL_KIND_MAP['web_search'] == 'search'
        assert _TOOL_KIND_MAP['file_read'] == 'read'
        assert _TOOL_KIND_MAP['file_write'] == 'edit'
        assert _TOOL_KIND_MAP['todo'] == 'think'


# ======================================================================
# 3. Config module — real OmegaConf objects
# ======================================================================

class TestConfigReal:

    def test_build_config_options_with_model(self):
        from omegaconf import OmegaConf
        from ms_agent.acp.config import build_config_options
        from acp.schema import SessionConfigOptionSelect

        cfg = OmegaConf.create({'llm': {'model': 'qwen-max'}})
        opts = build_config_options(cfg)
        assert opts is not None
        assert len(opts) == 1
        assert isinstance(opts[0], SessionConfigOptionSelect)
        assert opts[0].id == 'model'
        assert opts[0].current_value == 'qwen-max'

    def test_build_config_options_with_available_models(self):
        from omegaconf import OmegaConf
        from ms_agent.acp.config import build_config_options

        cfg = OmegaConf.create({'llm': {'model': 'gpt-4o'}})
        opts = build_config_options(cfg, available_models=['gpt-4o', 'gpt-4o-mini', 'o1'])
        assert opts is not None
        assert len(opts[0].options) == 3

    def test_build_config_options_no_model(self):
        from omegaconf import OmegaConf
        from ms_agent.acp.config import build_config_options

        cfg = OmegaConf.create({'other': 'value'})
        assert build_config_options(cfg) is None

    def test_apply_config_option_model(self):
        from omegaconf import OmegaConf
        from ms_agent.acp.config import apply_config_option

        cfg = OmegaConf.create({'llm': {'model': 'qwen-max'}})
        assert apply_config_option(cfg, 'model', 'gpt-4o') is True
        assert cfg.llm.model == 'gpt-4o'

    def test_apply_config_option_unknown_id(self):
        from omegaconf import OmegaConf
        from ms_agent.acp.config import apply_config_option

        cfg = OmegaConf.create({'llm': {'model': 'qwen-max'}})
        assert apply_config_option(cfg, 'temperature', '0.5') is False

    def test_build_session_modes(self):
        from ms_agent.acp.config import build_session_modes
        from acp.schema import SessionModeState

        modes = build_session_modes()
        assert isinstance(modes, SessionModeState)
        assert modes.current_mode_id == 'agent'
        assert len(modes.available_modes) >= 1


# ======================================================================
# 4. Permissions — real PermissionPolicy objects
# ======================================================================

class TestPermissionsReal:

    def test_auto_approve_flow(self):
        from ms_agent.acp.permissions import PermissionPolicy

        p = PermissionPolicy('auto_approve')
        assert p.should_ask('code_executor') is False
        assert p.auto_decision('code_executor') == 'allow_once'
        p.record_choice('code_executor', True)
        assert p.auto_decision('code_executor') == 'allow_once'

    def test_always_ask_flow(self):
        from ms_agent.acp.permissions import PermissionPolicy

        p = PermissionPolicy('always_ask')
        assert p.should_ask('web_search') is True
        assert p.auto_decision('web_search') is None
        p.record_choice('web_search', True)
        assert p.should_ask('web_search') is True

    def test_remember_choice_allow(self):
        from ms_agent.acp.permissions import PermissionPolicy

        p = PermissionPolicy('remember_choice')
        assert p.should_ask('read_file') is True
        p.record_choice('read_file', True)
        assert p.should_ask('read_file') is False
        dec = p.auto_decision('read_file')
        assert dec is not None and 'allow' in dec

    def test_remember_choice_deny(self):
        from ms_agent.acp.permissions import PermissionPolicy

        p = PermissionPolicy('remember_choice')
        p.record_choice('dangerous', False)
        assert p.should_ask('dangerous') is False
        dec = p.auto_decision('dangerous')
        assert dec is not None and 'deny' in dec

    def test_reset_clears_remembered(self):
        from ms_agent.acp.permissions import PermissionPolicy

        p = PermissionPolicy('remember_choice')
        p.record_choice('tool_a', True)
        p.record_choice('tool_b', False)
        p.reset()
        assert p.should_ask('tool_a') is True
        assert p.should_ask('tool_b') is True

    @pytest.mark.asyncio
    async def test_request_tool_permission_auto(self):
        from ms_agent.acp.permissions import PermissionPolicy, request_tool_permission

        policy = PermissionPolicy('auto_approve')
        result = await request_tool_permission(
            connection=None,
            session_id='ses_test',
            tool_call_id='tc_1',
            tool_name='web_search',
            policy=policy,
        )
        assert result is True


# ======================================================================
# 5. Registry — real manifest generation + file write
# ======================================================================

class TestRegistryReal:

    def test_manifest_structure(self):
        from ms_agent.acp.registry import generate_agent_manifest

        m = generate_agent_manifest(
            config_path='/path/to/researcher.yaml',
            output_path=None,
        )
        assert m['name'] == 'ms-agent'
        assert m['protocol'] == 'acp'
        assert m['protocolVersion'] == 1
        assert m['transport']['type'] == 'stdio'
        assert m['transport']['command'] == 'ms-agent'
        assert '--config' in m['transport']['args']
        assert '/path/to/researcher.yaml' in m['transport']['args']
        assert 'capabilities' in m

    def test_manifest_without_config(self):
        from ms_agent.acp.registry import generate_agent_manifest

        m = generate_agent_manifest(output_path=None)
        assert m['transport']['args'] == ['acp']

    def test_manifest_write_to_file(self):
        from ms_agent.acp.registry import generate_agent_manifest

        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name

        try:
            m = generate_agent_manifest(
                config_path='/test/config.yaml',
                output_path=path,
                title='Test Agent',
            )
            with open(path) as f:
                written = json.load(f)
            assert written['title'] == 'Test Agent'
            assert written['name'] == 'ms-agent'
        finally:
            os.unlink(path)

    def test_manifest_custom_fields(self):
        from ms_agent.acp.registry import generate_agent_manifest

        m = generate_agent_manifest(
            output_path=None,
            version='1.2.3',
            title='Custom Agent',
            description='Custom description',
        )
        assert m['version'] == '1.2.3'
        assert m['title'] == 'Custom Agent'
        assert m['description'] == 'Custom description'


# ======================================================================
# 6. SessionStore — real store object (no agent creation, tests structure)
# ======================================================================

class TestSessionStoreReal:

    def test_empty_store(self):
        from ms_agent.acp.session_store import ACPSessionStore

        store = ACPSessionStore(max_sessions=4)
        assert store.list_sessions() == []
        assert store.max_sessions == 4

    def test_get_nonexistent(self):
        from ms_agent.acp.session_store import ACPSessionStore
        from ms_agent.acp.errors import SessionNotFoundError

        store = ACPSessionStore()
        with pytest.raises(SessionNotFoundError) as exc_info:
            store.get('ses_does_not_exist')
        assert exc_info.value.code == -32001

    @pytest.mark.asyncio
    async def test_create_with_invalid_config(self):
        from ms_agent.acp.session_store import ACPSessionStore
        from ms_agent.acp.errors import ConfigError

        store = ACPSessionStore()
        with pytest.raises(ConfigError):
            await store.create(config_path='/nonexistent/agent.yaml', cwd='/tmp')

    @pytest.mark.asyncio
    async def test_create_real_session(self, monkeypatch):
        """Create a real session with the default agent config."""
        if not os.path.isfile(_ACP_TEST_CONFIG):
            pytest.skip('No agent config available')

        monkeypatch.setattr(sys, 'argv', ['test'])

        from ms_agent.acp.session_store import ACPSessionStore, ACPSessionEntry

        store = ACPSessionStore()
        try:
            entry = await store.create(config_path=_ACP_TEST_CONFIG, cwd='/tmp')
            assert isinstance(entry, ACPSessionEntry)
            assert entry.id.startswith('ses_')
            assert entry.agent is not None
            assert entry.cwd == '/tmp'
            assert len(store.list_sessions()) == 1

            retrieved = store.get(entry.id)
            assert retrieved.id == entry.id
        finally:
            await store.close_all()

    @pytest.mark.asyncio
    async def test_lru_eviction(self, monkeypatch):
        """Test that LRU eviction works when max_sessions is reached."""
        if not os.path.isfile(_ACP_TEST_CONFIG):
            pytest.skip('No agent config available')

        monkeypatch.setattr(sys, 'argv', ['test'])

        from ms_agent.acp.session_store import ACPSessionStore

        store = ACPSessionStore(max_sessions=2)
        try:
            s1 = await store.create(config_path=_ACP_TEST_CONFIG, cwd='/tmp')
            s2 = await store.create(config_path=_ACP_TEST_CONFIG, cwd='/tmp')
            assert len(store.list_sessions()) == 2

            s3 = await store.create(config_path=_ACP_TEST_CONFIG, cwd='/tmp')
            assert len(store.list_sessions()) == 2
            assert s3.id in [s['session_id'] for s in store.list_sessions()]
        finally:
            await store.close_all()


# ======================================================================
# 7. ACPAgentTool — real tool object creation
# ======================================================================

class TestACPAgentToolReal:

    def test_from_config_returns_none_without_acp_agents(self):
        from omegaconf import OmegaConf
        from ms_agent.tools.acp_agent_tool import ACPAgentTool

        cfg = OmegaConf.create({'llm': {'model': 'test'}})
        assert ACPAgentTool.from_config(cfg) is None

    def test_from_config_creates_tool(self):
        from omegaconf import OmegaConf
        from ms_agent.tools.acp_agent_tool import ACPAgentTool

        cfg = OmegaConf.create({
            'llm': {'model': 'test'},
            'acp_agents': {
                'codex': {
                    'command': 'codex',
                    'args': ['mcp-server'],
                    'description': 'Codex coding agent',
                },
            },
        })
        tool = ACPAgentTool.from_config(cfg)
        assert tool is not None
        assert 'codex' in tool._client_manager.list_agents()

    @pytest.mark.asyncio
    async def test_get_tools_structure(self):
        from omegaconf import OmegaConf
        from ms_agent.tools.acp_agent_tool import ACPAgentTool

        cfg = OmegaConf.create({
            'llm': {'model': 'test'},
            'acp_agents': {
                'agent_a': {
                    'command': 'echo',
                    'args': [],
                    'description': 'Agent A desc',
                },
                'agent_b': {
                    'command': 'echo',
                    'args': [],
                    'description': 'Agent B desc',
                },
            },
        })
        tool = ACPAgentTool(cfg, acp_agents_config=OmegaConf.to_container(cfg.acp_agents, resolve=True))
        tools = await tool._get_tools_inner()
        assert 'acp_agent_a' in tools
        assert 'acp_agent_b' in tools
        assert tools['acp_agent_a'][0]['parameters']['required'] == ['query']


# ======================================================================
# 8. ACP Client Manager — real object, config-based
# ======================================================================

class TestACPClientManagerReal:

    def test_empty_manager(self):
        from ms_agent.acp.client import ACPClientManager

        mgr = ACPClientManager()
        assert mgr.list_agents() == []

    def test_configured_manager(self):
        from ms_agent.acp.client import ACPClientManager

        cfg = {
            'codex': {
                'command': 'codex',
                'args': ['mcp-server'],
                'description': 'Codex',
                'permission_policy': 'auto_approve',
            },
        }
        mgr = ACPClientManager(cfg)
        assert 'codex' in mgr.list_agents()

    @pytest.mark.asyncio
    async def test_call_unconfigured_returns_error(self):
        from ms_agent.acp.client import ACPClientManager

        mgr = ACPClientManager()
        result = await mgr.call_agent('nonexistent', 'hello')
        assert 'not configured' in result


# ======================================================================
# 9. CLI — acp-registry command real execution
# ======================================================================

class TestCLIReal:

    def test_acp_registry_generates_json(self):
        """Run 'ms-agent acp-registry' as a subprocess and verify output."""
        import subprocess

        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            outpath = f.name

        try:
            result = subprocess.run(
                [sys.executable, '-m', 'ms_agent.cli.cli',
                 'acp-registry', '--output', outpath, '--title', 'TestAgent'],
                capture_output=True, text=True, timeout=30,
                cwd=_REPO_ROOT,
            )
            assert result.returncode == 0, f'stderr: {result.stderr}'
            stdout_json = json.loads(result.stdout)
            assert stdout_json['name'] == 'ms-agent'
            assert stdout_json['title'] == 'TestAgent'

            with open(outpath) as f:
                file_json = json.load(f)
            assert file_json['protocol'] == 'acp'
        finally:
            if os.path.exists(outpath):
                os.unlink(outpath)

    def test_acp_registry_with_config(self):
        import subprocess

        result = subprocess.run(
            [sys.executable, '-m', 'ms_agent.cli.cli',
             'acp-registry', '--config', _ACP_TEST_CONFIG, '--output', ''],
            capture_output=True, text=True, timeout=30,
            cwd=_REPO_ROOT,
        )
        stdout_json = json.loads(result.stdout)
        assert '--config' in stdout_json['transport']['args']


# ======================================================================
# 10. ACP Server — real spawn_agent_process (initialize + new_session)
# ======================================================================

@pytest.mark.skipif(
    not os.path.isfile(_ACP_TEST_CONFIG),
    reason='No agent config found',
)
class TestACPServerReal:

    @pytest.mark.asyncio
    async def test_initialize_and_new_session(self):
        """Spawn a real ACP server subprocess and test initialize + new_session."""
        from acp import spawn_agent_process, text_block
        from acp.interfaces import Client

        class TestClient(Client):
            def __init__(self):
                self.updates = []

            async def session_update(self, session_id, update, **kwargs):
                self.updates.append(update)

            async def request_permission(self, options, session_id, tool_call, **kwargs):
                allow = next(
                    (o for o in options if 'allow' in (getattr(o, 'kind', '') or '')),
                    None,
                )
                if allow:
                    return {'outcome': {'outcome': 'selected', 'id': getattr(allow, 'option_id', 'allow_once')}}
                return {'outcome': {'outcome': 'cancelled'}}

        client = TestClient()
        async with spawn_agent_process(
            client,
            sys.executable,
            '-m', 'ms_agent.cli.cli',
            'acp',
            '--config', _ACP_TEST_CONFIG,
        ) as (conn, proc):
            init_resp = await conn.initialize(protocol_version=1)
            assert init_resp.protocol_version == 1
            assert init_resp.agent_info is not None
            assert init_resp.agent_info.name == 'ms-agent'
            assert init_resp.agent_info.version == '0.1.0'

            caps = init_resp.agent_capabilities
            assert caps is not None

            session = await conn.new_session(cwd='/tmp', mcp_servers=[])
            assert session.session_id
            assert session.session_id.startswith('ses_')

    @pytest.mark.asyncio
    async def test_list_sessions_after_create(self):
        """After creating a session, list_sessions should return it."""
        from acp import spawn_agent_process
        from acp.interfaces import Client

        class TestClient(Client):
            async def session_update(self, session_id, update, **kwargs):
                pass
            async def request_permission(self, options, session_id, tool_call, **kwargs):
                return {'outcome': {'outcome': 'cancelled'}}

        client = TestClient()
        async with spawn_agent_process(
            client,
            sys.executable,
            '-m', 'ms_agent.cli.cli',
            'acp',
            '--config', _ACP_TEST_CONFIG,
        ) as (conn, proc):
            await conn.initialize(protocol_version=1)
            session = await conn.new_session(cwd='/tmp', mcp_servers=[])

            sessions = await conn.list_sessions()
            session_ids = [s.session_id for s in sessions.sessions]
            assert session.session_id in session_ids


# ======================================================================
# 11. CollectorClient — real _CollectorClient object behavior
# ======================================================================

class TestCollectorClientReal:

    @pytest.mark.asyncio
    async def test_collect_text_updates(self):
        from ms_agent.acp.client import _CollectorClient
        from types import SimpleNamespace

        client = _CollectorClient()
        sid = 'ses_test'

        update1 = SimpleNamespace(session_update='agent_message_chunk',
                                  content=SimpleNamespace(text='Hello '))
        update2 = SimpleNamespace(session_update='agent_message_chunk',
                                  content=SimpleNamespace(text='World'))

        await client.session_update(sid, update1)
        await client.session_update(sid, update2)

        assert client.get_output(sid) == 'Hello World'

    @pytest.mark.asyncio
    async def test_ignores_non_text_updates(self):
        from ms_agent.acp.client import _CollectorClient
        from types import SimpleNamespace

        client = _CollectorClient()
        sid = 'ses_test'

        update = SimpleNamespace(session_update='tool_call_start', content=None)
        await client.session_update(sid, update)
        assert client.get_output(sid) == ''

    @pytest.mark.asyncio
    async def test_auto_approve_permission(self):
        from ms_agent.acp.client import _CollectorClient
        from types import SimpleNamespace

        client = _CollectorClient(permission_policy='auto_approve')
        options = [
            SimpleNamespace(kind='allow_once', option_id='allow_once'),
            SimpleNamespace(kind='deny_once', option_id='deny_once'),
        ]
        result = await client.request_permission(options, 'ses_x', None)
        assert result.outcome.outcome == 'selected'
        assert result.outcome.option_id == 'allow_once'

    def test_clear(self):
        from ms_agent.acp.client import _CollectorClient

        client = _CollectorClient()
        client.collected['ses_1'] = ['data']
        client.clear('ses_1')
        assert client.get_output('ses_1') == ''


# ======================================================================
# 12. HTTP Adapter — DummyConn queue behavior (no server start needed)
# ======================================================================

class TestHTTPAdapterComponents:

    @pytest.mark.asyncio
    async def test_dummy_conn_queue(self):
        from ms_agent.acp.http_adapter import _DummyConn
        from types import SimpleNamespace

        conn = _DummyConn()
        q = conn.get_queue('ses_1')
        assert q.empty()

        update = SimpleNamespace(session_update='agent_message_chunk')
        update.model_dump = lambda by_alias=False: {'session_update': 'agent_message_chunk'}
        await conn.session_update('ses_1', update)
        assert not q.empty()
        data = await q.get()
        assert data['session_update'] == 'agent_message_chunk'

    @pytest.mark.asyncio
    async def test_dummy_conn_auto_approve(self):
        from ms_agent.acp.http_adapter import _DummyConn
        from types import SimpleNamespace

        conn = _DummyConn()
        options = [
            SimpleNamespace(kind='allow_once', option_id='allow_once'),
        ]
        result = await conn.request_permission('ses_1', None, options)
        assert result.outcome['outcome'] == 'selected'


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short', '-x'])
