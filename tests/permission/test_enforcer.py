"""Tests for PermissionEnforcer."""

import pytest

from ms_agent.permission.config import PermissionConfig
from ms_agent.permission.enforcer import PermissionEnforcer
from ms_agent.permission.handler import (
    AutoPermissionHandler,
    PermissionAction,
    PermissionResponse,
)
from ms_agent.permission.memory import PermissionMemory


def _interactive_config(**kwargs) -> PermissionConfig:
    """Build interactive-mode config via from_dict (restricted → interactive alias)."""
    raw = {'mode': 'restricted', **kwargs}
    if 'whitelist' in raw:
        raw['whitelist'] = list(raw['whitelist'])
    if 'blacklist' in raw:
        raw['blacklist'] = list(raw['blacklist'])
    config = PermissionConfig.from_dict(raw)
    assert config.mode == 'interactive'
    return config


class MockDenyHandler:
    async def ask(self, tool_name, tool_args, context, suggestions=None):
        return PermissionResponse(action=PermissionAction.DENY, feedback='Denied by mock')


class MockAllowHandler:
    async def ask(self, tool_name, tool_args, context, suggestions=None):
        return PermissionResponse(action=PermissionAction.ALLOW_ONCE)


class MockAlwaysHandler:
    async def ask(self, tool_name, tool_args, context, suggestions=None):
        return PermissionResponse(
            action=PermissionAction.ALLOW_ALWAYS,
            pattern=tool_name,
        )


@pytest.fixture
def auto_enforcer():
    config = PermissionConfig(mode='auto')
    return PermissionEnforcer(config=config)


@pytest.fixture
def interactive_enforcer(tmp_path):
    config = _interactive_config(
        whitelist=('file_system---read_file',),
        blacklist=('code_executor---shell_executor:rm -rf *',),
    )
    handler = MockAllowHandler()
    memory = PermissionMemory(project_path=tmp_path)
    return PermissionEnforcer(config=config, handler=handler, memory=memory)


class TestAutoMode:
    @pytest.mark.asyncio
    async def test_always_allows(self, auto_enforcer):
        r = await auto_enforcer.check('any_tool', {})
        assert r.action == 'allow'
        assert 'Auto mode' in r.reason

    @pytest.mark.asyncio
    async def test_blacklist_denies(self, auto_enforcer):
        r = await auto_enforcer.check(
            'code_executor---shell_executor',
            {'command': 'curl http://example.com'},
        )
        assert r.action == 'deny'
        assert 'blacklist' in r.reason


class TestStrictMode:
    @pytest.mark.asyncio
    async def test_allows_non_blacklisted(self):
        config = PermissionConfig(mode='strict')
        enforcer = PermissionEnforcer(config=config)
        r = await enforcer.check('file_system---read_file', {'path': '/test'})
        assert r.action == 'allow'
        assert 'Strict mode' in r.reason

    @pytest.mark.asyncio
    async def test_blacklist_denies(self):
        config = PermissionConfig(
            mode='strict',
            blacklist=('code_executor---shell_executor:rm -rf *',),
        )
        enforcer = PermissionEnforcer(config=config)
        r = await enforcer.check(
            'code_executor---shell_executor',
            {'command': 'rm -rf /tmp'},
        )
        assert r.action == 'deny'
        assert 'blacklist' in r.reason


class TestInteractiveMode:
    @pytest.mark.asyncio
    async def test_whitelist_allows(self, interactive_enforcer):
        r = await interactive_enforcer.check('file_system---read_file', {'path': '/test'})
        assert r.action == 'allow'
        assert 'whitelist' in r.reason

    @pytest.mark.asyncio
    async def test_blacklist_denies(self, interactive_enforcer):
        r = await interactive_enforcer.check(
            'code_executor---shell_executor',
            {'command': 'rm -rf /tmp'},
        )
        assert r.action == 'deny'
        assert 'blacklist' in r.reason

    @pytest.mark.asyncio
    async def test_unknown_asks_handler(self, interactive_enforcer):
        r = await interactive_enforcer.check('unknown---tool', {'arg': 'val'})
        assert r.action == 'allow'  # MockAllowHandler returns allow_once

    @pytest.mark.asyncio
    async def test_deny_handler(self, tmp_path):
        config = _interactive_config()
        handler = MockDenyHandler()
        memory = PermissionMemory(project_path=tmp_path)
        enforcer = PermissionEnforcer(config=config, handler=handler, memory=memory)

        r = await enforcer.check('unknown---tool', {})
        assert r.action == 'deny'


class TestBlacklistPriority:
    @pytest.mark.asyncio
    async def test_blacklist_over_whitelist(self, tmp_path):
        config = _interactive_config(
            whitelist=('code_executor---*',),
            blacklist=('code_executor---shell_executor:rm *',),
        )
        enforcer = PermissionEnforcer(
            config=config,
            handler=MockAllowHandler(),
            memory=PermissionMemory(project_path=tmp_path),
        )
        r = await enforcer.check(
            'code_executor---shell_executor',
            {'command': 'rm -rf /'},
        )
        assert r.action == 'deny'


class TestMemoryIntegration:
    @pytest.mark.asyncio
    async def test_session_memory(self, tmp_path):
        config = _interactive_config()
        memory = PermissionMemory(project_path=tmp_path)
        memory.add_session('custom---tool')
        enforcer = PermissionEnforcer(
            config=config,
            handler=MockDenyHandler(),
            memory=memory,
        )
        r = await enforcer.check('custom---tool', {})
        assert r.action == 'allow'

    @pytest.mark.asyncio
    async def test_persistent_memory(self, tmp_path):
        config = _interactive_config()
        memory = PermissionMemory(project_path=tmp_path)
        memory.add('custom---tool', scope='project')
        enforcer = PermissionEnforcer(
            config=config,
            handler=MockDenyHandler(),
            memory=memory,
        )
        r = await enforcer.check('custom---tool', {})
        assert r.action == 'allow'

    @pytest.mark.asyncio
    async def test_allow_always_persists(self, tmp_path):
        config = _interactive_config()
        memory = PermissionMemory(project_path=tmp_path)
        enforcer = PermissionEnforcer(
            config=config,
            handler=MockAlwaysHandler(),
            memory=memory,
        )

        r = await enforcer.check('new---tool', {})
        assert r.action == 'allow'

        # Second call should match from memory
        enforcer2 = PermissionEnforcer(
            config=config,
            handler=MockDenyHandler(),
            memory=memory,
        )
        r2 = await enforcer2.check('new---tool', {})
        assert r2.action == 'allow'


class TestModifyAction:
    @pytest.mark.asyncio
    async def test_modify_returns_updated_args(self, tmp_path):
        class MockModifyHandler:
            async def ask(self, tool_name, tool_args, context, suggestions=None):
                return PermissionResponse(
                    action=PermissionAction.MODIFY,
                    updated_args={'command': 'ls -la'},
                )

        config = _interactive_config()
        enforcer = PermissionEnforcer(
            config=config,
            handler=MockModifyHandler(),
            memory=PermissionMemory(project_path=tmp_path),
        )
        r = await enforcer.check('code_executor---shell_executor', {'command': 'rm -rf /'})
        assert r.action == 'allow'
        assert r.updated_args == {'command': 'ls -la'}
