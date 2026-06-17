import pytest
from dataclasses import dataclass

from ms_agent.command.builtin import register_builtin_commands
from ms_agent.command.router import CommandRouter
from ms_agent.command.types import CommandContext, CommandResultType


@dataclass
class MockRuntime:
    should_stop: bool = False
    round: int = 3
    tag: str = 'test-agent'


def _make_ctx(text: str, router: CommandRouter, runtime=None) -> CommandContext:
    cmd, args = CommandRouter.parse_input(text)
    return CommandContext(
        raw_input=text,
        command_name=cmd,
        args=args,
        source='cli',
        runtime=runtime,
        extra={'router': router},
    )


class TestBuiltinCommands:
    @pytest.fixture
    def router(self):
        r = CommandRouter()
        register_builtin_commands(r)
        return r

    @pytest.mark.asyncio
    async def test_stop_sets_should_stop(self, router):
        runtime = MockRuntime()
        ctx = _make_ctx('/stop', router, runtime)
        result = await router.dispatch(ctx)
        assert result.type == CommandResultType.MESSAGE
        assert runtime.should_stop is True

    @pytest.mark.asyncio
    async def test_stop_is_priority(self, router):
        assert router.is_priority('/stop')

    @pytest.mark.asyncio
    async def test_stop_aliases(self, router):
        runtime = MockRuntime()
        for alias in ['/abort', '/cancel']:
            runtime.should_stop = False
            ctx = _make_ctx(alias, router, runtime)
            result = await router.dispatch(ctx)
            assert result is not None
            assert runtime.should_stop is True

    @pytest.mark.asyncio
    async def test_new_returns_quit(self, router):
        runtime = MockRuntime()
        ctx = _make_ctx('/new', router, runtime)
        result = await router.dispatch(ctx)
        assert result.type == CommandResultType.QUIT

    @pytest.mark.asyncio
    async def test_status_shows_runtime_info(self, router):
        runtime = MockRuntime(round=5, tag='my-agent')
        ctx = _make_ctx('/status', router, runtime)
        result = await router.dispatch(ctx)
        assert 'Round: 5' in result.content
        assert 'my-agent' in result.content

    @pytest.mark.asyncio
    async def test_status_no_runtime(self, router):
        ctx = _make_ctx('/status', router, runtime=None)
        result = await router.dispatch(ctx)
        assert 'No active agent' in result.content

    @pytest.mark.asyncio
    async def test_help_lists_commands(self, router):
        ctx = _make_ctx('/help', router)
        result = await router.dispatch(ctx)
        assert result.type == CommandResultType.MESSAGE
        assert '/stop' in result.content
        assert '/help' in result.content

    @pytest.mark.asyncio
    async def test_help_alias(self, router):
        ctx = _make_ctx('/?', router)
        result = await router.dispatch(ctx)
        assert result is not None

    @pytest.mark.asyncio
    async def test_version(self, router):
        ctx = _make_ctx('/version', router)
        result = await router.dispatch(ctx)
        assert result.type == CommandResultType.MESSAGE
        assert 'MS-Agent' in result.content
