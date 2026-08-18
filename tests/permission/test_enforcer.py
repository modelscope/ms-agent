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
    async def test_blacklist_denies(self):
        # A blacklist entry outranks even auto mode. The list ships EMPTY now
        # (network commands are ask rules, not refusals), so this states its own
        # rule rather than leaning on a default.
        config = PermissionConfig(
            mode='auto',
            blacklist=('code_executor---shell_executor:curl *', ),
        )
        r = await PermissionEnforcer(config=config).check(
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


class TestNetworkCommandsAsk:
    """curl/wget/ssh/... used to sit in the DEFAULT BLACKLIST, which nothing can
    override — so the agent reported "blocked" and the user had no way to permit
    it, in any mode. They are ask rules now: confirmed, never silently refused."""

    @pytest.mark.asyncio
    async def test_curl_asks_in_interactive_mode(self, tmp_path):
        class Probe:
            asked = 0

            async def ask(self, tool_name, tool_args, context, suggestions=None):
                Probe.asked += 1
                return PermissionResponse(action=PermissionAction.ALLOW_ONCE)

        enforcer = PermissionEnforcer(
            config=_interactive_config(),
            handler=Probe(),
            memory=PermissionMemory(project_path=tmp_path),
        )
        r = await enforcer.check('code_executor---shell_executor',
                                 {'command': 'curl --version'})
        assert r.action == 'allow'
        assert Probe.asked == 1

    @pytest.mark.asyncio
    async def test_curl_still_asks_under_full_access(self, tmp_path):
        """Reaching the network is worth one deliberate click even from a user
        who waved the agent through everything else — the ask rule outranks the
        mode AND the whitelist."""
        class Probe:
            asked = 0

            async def ask(self, tool_name, tool_args, context, suggestions=None):
                Probe.asked += 1
                return PermissionResponse(action=PermissionAction.ALLOW_ONCE)

        config = PermissionConfig.from_dict({
            'mode': 'auto',
            'whitelist': ['code_executor---shell_executor'],
        })
        enforcer = PermissionEnforcer(
            config=config,
            handler=Probe(),
            memory=PermissionMemory(project_path=tmp_path),
        )
        r = await enforcer.check('code_executor---shell_executor',
                                 {'command': 'curl https://example.com'})
        assert r.action == 'allow'
        assert Probe.asked == 1

    @pytest.mark.asyncio
    async def test_ordinary_command_unaffected_in_auto_mode(self, tmp_path):
        class Probe:
            asked = 0

            async def ask(self, tool_name, tool_args, context, suggestions=None):
                Probe.asked += 1
                return PermissionResponse(action=PermissionAction.ALLOW_ONCE)

        enforcer = PermissionEnforcer(
            config=PermissionConfig.from_dict({'mode': 'auto'}),
            handler=Probe(),
            memory=PermissionMemory(project_path=tmp_path),
        )
        r = await enforcer.check('code_executor---shell_executor',
                                 {'command': 'ls -la'})
        assert r.action == 'allow'
        assert Probe.asked == 0

    @pytest.mark.asyncio
    async def test_curl_denied_when_nobody_can_be_asked(self, tmp_path):
        """Headless: AutoPermissionHandler answers "allow" to everything, so
        running the thing an ask rule exists to gate would be worse than
        refusing."""
        enforcer = PermissionEnforcer(
            config=PermissionConfig.from_dict({'mode': 'auto'}),
            handler=AutoPermissionHandler(),
            memory=PermissionMemory(project_path=tmp_path),
        )
        r = await enforcer.check('code_executor---shell_executor',
                                 {'command': 'curl https://example.com'})
        assert r.action == 'deny'
        assert 'curl' in r.reason

    @pytest.mark.asyncio
    async def test_allow_network_opts_out(self, tmp_path):
        class Probe:
            asked = 0

            async def ask(self, tool_name, tool_args, context, suggestions=None):
                Probe.asked += 1
                return PermissionResponse(action=PermissionAction.ALLOW_ONCE)

        config = PermissionConfig.from_dict({
            'mode': 'auto',
            'allow_network': True,
        })
        enforcer = PermissionEnforcer(
            config=config,
            handler=Probe(),
            memory=PermissionMemory(project_path=tmp_path),
        )
        r = await enforcer.check('code_executor---shell_executor',
                                 {'command': 'curl https://example.com'})
        assert r.action == 'allow'
        assert Probe.asked == 0


class TestRememberedPatternBreadth:
    """A caller that names no pattern used to have the BARE TOOL NAME
    remembered — for the shell that is every future command, so approving
    `ls -la` once handed over unrestricted shell access."""

    @pytest.mark.asyncio
    async def test_shell_remembers_the_command_not_the_whole_tool(self, tmp_path):
        class PatternlessSession:
            async def ask(self, tool_name, tool_args, context, suggestions=None):
                return PermissionResponse(action=PermissionAction.ALLOW_SESSION)

        memory = PermissionMemory(project_path=tmp_path)
        enforcer = PermissionEnforcer(
            config=_interactive_config(),
            handler=PatternlessSession(),
            memory=memory,
        )
        r = await enforcer.check('code_executor---shell_executor',
                                 {'command': 'ls -la'})
        assert r.action == 'allow'
        # Same command family: remembered.
        assert memory.matches('code_executor---shell_executor',
                              {'command': 'ls /tmp'})
        # Including with no arguments at all.
        assert memory.matches('code_executor---shell_executor',
                              {'command': 'ls'})
        # A different command is NOT covered by approving `ls`.
        assert not memory.matches('code_executor---shell_executor',
                                  {'command': 'rm -rf build'})

    @pytest.mark.asyncio
    async def test_argument_less_command_remembers_itself(self, tmp_path):
        """Approving bare `whoami` must cover `whoami` — the remembered pattern
        used not to match the very command it was generated from."""
        class PatternlessSession:
            async def ask(self, tool_name, tool_args, context, suggestions=None):
                return PermissionResponse(action=PermissionAction.ALLOW_SESSION)

        memory = PermissionMemory(project_path=tmp_path)
        enforcer = PermissionEnforcer(
            config=_interactive_config(),
            handler=PatternlessSession(),
            memory=memory,
        )
        await enforcer.check('code_executor---shell_executor',
                             {'command': 'whoami'})
        assert memory.matches('code_executor---shell_executor',
                              {'command': 'whoami'})

    @pytest.mark.asyncio
    async def test_fallback_never_widens_past_the_tool(self, tmp_path):
        """`web_search` suggests a server-wide `web_search---*`; a FALLBACK must
        not be broader than the tool the user actually approved."""
        class PatternlessSession:
            async def ask(self, tool_name, tool_args, context, suggestions=None):
                return PermissionResponse(action=PermissionAction.ALLOW_SESSION)

        memory = PermissionMemory(project_path=tmp_path)
        enforcer = PermissionEnforcer(
            config=_interactive_config(),
            handler=PatternlessSession(),
            memory=memory,
        )
        await enforcer.check('web_search---search', {'query': 'x'})
        assert memory.matches('web_search---search', {'query': 'y'})
        assert not memory.matches('web_search---fetch_page', {'url': 'z'})
