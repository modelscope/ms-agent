"""Unit tests for the ACP proxy module."""

import asyncio
import os
import tempfile

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ms_agent.acp.proxy import (
    BackendConfig,
    MSAgentACPProxy,
    ProxyConfig,
    _RelayClient,
)
from ms_agent.acp.proxy_session import ProxySessionEntry, ProxySessionStore
from ms_agent.acp.errors import (
    ConfigError,
    MaxSessionsError,
    SessionNotFoundError,
)


class TestProxyConfig:

    def test_from_yaml_basic(self, tmp_path):
        cfg_file = tmp_path / 'proxy.yaml'
        cfg_file.write_text("""
proxy:
  max_sessions: 4
  session_timeout: 1800
  default_backend: agent-a

backends:
  agent-a:
    command: echo
    args: [hello]
    description: "Test agent A"
  agent-b:
    command: cat
    description: "Test agent B"
""")
        config = ProxyConfig.from_yaml(str(cfg_file))
        assert config.max_sessions == 4
        assert config.session_timeout == 1800
        assert config.default_backend == 'agent-a'
        assert len(config.backends) == 2
        assert config.backends['agent-a'].command == 'echo'
        assert config.backends['agent-a'].args == ['hello']
        assert config.backends['agent-b'].args == []

    def test_from_yaml_default_backend_auto(self, tmp_path):
        cfg_file = tmp_path / 'proxy.yaml'
        cfg_file.write_text("""
backends:
  only-one:
    command: true
""")
        config = ProxyConfig.from_yaml(str(cfg_file))
        assert config.default_backend == 'only-one'
        assert config.max_sessions == 8

    def test_from_yaml_missing_command_skipped(self, tmp_path):
        cfg_file = tmp_path / 'proxy.yaml'
        cfg_file.write_text("""
backends:
  good:
    command: echo
  bad:
    description: "no command field"
""")
        config = ProxyConfig.from_yaml(str(cfg_file))
        assert 'good' in config.backends
        assert 'bad' not in config.backends

    def test_from_yaml_not_found(self):
        with pytest.raises(ConfigError):
            ProxyConfig.from_yaml('/nonexistent/proxy.yaml')

    def test_from_yaml_empty_file(self, tmp_path):
        cfg_file = tmp_path / 'empty.yaml'
        cfg_file.write_text('')
        with pytest.raises(ConfigError, match='Invalid'):
            ProxyConfig.from_yaml(str(cfg_file))

    def test_from_yaml_with_env(self, tmp_path):
        cfg_file = tmp_path / 'proxy.yaml'
        cfg_file.write_text("""
backends:
  myagent:
    command: agent
    env:
      MY_KEY: my_value
""")
        config = ProxyConfig.from_yaml(str(cfg_file))
        assert config.backends['myagent'].env == {'MY_KEY': 'my_value'}


class TestProxySessionStore:

    def test_register_and_get(self):
        store = ProxySessionStore(max_sessions=4)
        entry = store.register(
            backend_name='test',
            backend_sid='bk_123',
            backend_conn=MagicMock(),
            backend_proc=MagicMock(),
            ctx_manager=None,
            cwd='/tmp',
        )
        assert entry.id.startswith('pxy_')
        assert entry.backend_name == 'test'
        assert entry.backend_sid == 'bk_123'

        fetched = store.get(entry.id)
        assert fetched is entry

    def test_get_not_found(self):
        store = ProxySessionStore()
        with pytest.raises(SessionNotFoundError):
            store.get('nonexistent')

    def test_max_sessions_eviction(self):
        store = ProxySessionStore(max_sessions=2)
        e1 = store.register(
            'a', 'sid1', MagicMock(), MagicMock(), None, '/tmp')
        e2 = store.register(
            'b', 'sid2', MagicMock(), MagicMock(), None, '/tmp')
        e3 = store.register(
            'c', 'sid3', MagicMock(), MagicMock(), None, '/tmp')
        assert len(store._sessions) == 2
        assert e3.id in store._sessions

    def test_max_sessions_all_running(self):
        store = ProxySessionStore(max_sessions=1)
        e1 = store.register(
            'a', 'sid1', MagicMock(), MagicMock(), None, '/tmp')
        e1.is_running = True
        with pytest.raises(MaxSessionsError):
            store.register(
                'b', 'sid2', MagicMock(), MagicMock(), None, '/tmp')

    def test_list_sessions(self):
        store = ProxySessionStore()
        store.register('a', 'sid1', MagicMock(), MagicMock(), None, '/tmp')
        store.register('b', 'sid2', MagicMock(), MagicMock(), None, '/work')
        result = store.list_sessions()
        assert len(result) == 2
        backends = {e['backend'] for e in result}
        assert backends == {'a', 'b'}

    @pytest.mark.asyncio
    async def test_remove(self):
        store = ProxySessionStore()
        entry = store.register(
            'a', 'sid1', MagicMock(), MagicMock(), None, '/tmp')
        await store.remove(entry.id)
        assert entry.id not in store._sessions

    @pytest.mark.asyncio
    async def test_close_all(self):
        store = ProxySessionStore()
        store.register('a', 'sid1', MagicMock(), MagicMock(), None, '/tmp')
        store.register('b', 'sid2', MagicMock(), MagicMock(), None, '/tmp')
        await store.close_all()
        assert len(store._sessions) == 0

    def test_cancel(self):
        store = ProxySessionStore()
        entry = store.register(
            'a', 'sid1', MagicMock(), MagicMock(), None, '/tmp')
        assert not entry.cancelled
        entry.request_cancel()
        assert entry.cancelled


class TestRelayClient:

    @pytest.mark.asyncio
    async def test_session_update_relay(self):
        mock_conn = AsyncMock()
        relay = _RelayClient(mock_conn, 'pxy_abc')
        update = MagicMock()

        await relay.session_update('backend_sid', update)
        mock_conn.session_update.assert_awaited_once_with('pxy_abc', update)

    @pytest.mark.asyncio
    async def test_request_permission_relay(self):
        mock_conn = AsyncMock()
        relay = _RelayClient(mock_conn, 'pxy_abc')
        options = [MagicMock()]
        tool_call = MagicMock()

        await relay.request_permission(options, 'backend_sid', tool_call)
        mock_conn.request_permission.assert_awaited_once_with(
            session_id='pxy_abc',
            tool_call=tool_call,
            options=options,
        )


class TestMSAgentACPProxy:

    def _make_config(self):
        return ProxyConfig(
            max_sessions=4,
            session_timeout=3600,
            default_backend='agent-a',
            backends={
                'agent-a': BackendConfig(
                    name='agent-a',
                    command='echo',
                    args=['acp'],
                    description='Test A',
                ),
                'agent-b': BackendConfig(
                    name='agent-b',
                    command='cat',
                    description='Test B',
                ),
            },
        )

    @pytest.mark.asyncio
    async def test_initialize(self):
        proxy = MSAgentACPProxy(self._make_config())
        resp = await proxy.initialize(protocol_version=1)
        assert resp.agent_info.name == 'ms-agent-proxy'
        assert resp.protocol_version >= 1

    def test_build_config_options_multiple_backends(self):
        proxy = MSAgentACPProxy(self._make_config())
        opts = proxy._build_config_options('agent-a')
        assert opts is not None
        assert len(opts) == 1
        assert opts[0].id == 'backend'
        assert opts[0].current_value == 'agent-a'

    def test_build_config_options_single_backend(self):
        config = ProxyConfig(
            backends={
                'only': BackendConfig(name='only', command='echo'),
            },
            default_backend='only',
        )
        proxy = MSAgentACPProxy(config)
        opts = proxy._build_config_options('only')
        assert opts is None

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self):
        proxy = MSAgentACPProxy(self._make_config())
        resp = await proxy.list_sessions()
        assert resp.sessions == []
