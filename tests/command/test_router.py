import pytest
from ms_agent.command.router import CommandRouter
from ms_agent.command.types import (
    CommandContext,
    CommandDef,
    CommandResult,
    CommandResultType,
)


def _make_ctx(text: str) -> CommandContext:
    cmd, args = CommandRouter.parse_input(text)
    return CommandContext(raw_input=text, command_name=cmd, args=args)


async def _echo_handler(ctx: CommandContext) -> CommandResult:
    return CommandResult(type=CommandResultType.MESSAGE, content=f'echo:{ctx.command_name}')


async def _args_handler(ctx: CommandContext) -> CommandResult:
    return CommandResult(type=CommandResultType.MESSAGE, content=f'args:{ctx.args}')


class TestIsCommand:
    @pytest.fixture
    def router(self):
        r = CommandRouter()
        r.register(
            CommandDef(name='help', description='help', aliases=('?',)),
            _echo_handler,
        )
        r.register(
            CommandDef(name='model', description='model'),
            _echo_handler,
        )
        return r

    def test_registered_command(self, router):
        assert router.is_command('/help')

    def test_registered_with_args(self, router):
        assert router.is_command('/model gpt-4')

    def test_alias_recognized(self, router):
        assert router.is_command('/?')

    def test_file_path_excluded(self, router):
        assert not router.is_command('/Users/foo/bar')

    def test_empty_string(self, router):
        assert not router.is_command('')

    def test_no_slash(self, router):
        assert not router.is_command('hello world')

    def test_double_slash_excluded(self, router):
        assert not router.is_command('//comment')

    def test_windows_path_excluded(self, router):
        assert not router.is_command('/c/Users/foo')

    def test_root_single_segment_path_excluded(self, router):
        assert not router.is_command('/tmp')

    def test_root_paths_excluded(self, router):
        for path in ['/etc', '/var', '/opt', '/bin', '/usr']:
            assert not router.is_command(path), f'{path} should not be a command'

    def test_unregistered_command_excluded(self, router):
        assert not router.is_command('/nonexistent')

    def test_interceptor_makes_unknown_passthrough(self):
        router = CommandRouter()
        router.register_interceptor(_echo_handler)
        assert router.is_command('/anything')


class TestParseInput:
    def test_simple(self):
        cmd, args = CommandRouter.parse_input('/help')
        assert cmd == 'help'
        assert args == ''

    def test_with_args(self):
        cmd, args = CommandRouter.parse_input('/model gpt-4')
        assert cmd == 'model'
        assert args == 'gpt-4'

    def test_with_multi_args(self):
        cmd, args = CommandRouter.parse_input('/skill-name do something complex')
        assert cmd == 'skill-name'
        assert args == 'do something complex'

    def test_case_insensitive(self):
        cmd, _ = CommandRouter.parse_input('/HELP')
        assert cmd == 'help'


class TestDispatch:
    @pytest.fixture
    def router(self):
        r = CommandRouter()
        r.register(
            CommandDef(name='stop', description='stop', priority=0),
            _echo_handler,
        )
        r.register(
            CommandDef(name='help', description='help', aliases=('?',)),
            _echo_handler,
        )
        return r

    @pytest.mark.asyncio
    async def test_priority_dispatched(self, router):
        ctx = _make_ctx('/stop')
        result = await router.dispatch(ctx)
        assert result is not None
        assert result.content == 'echo:stop'

    @pytest.mark.asyncio
    async def test_exact_dispatched(self, router):
        ctx = _make_ctx('/help')
        result = await router.dispatch(ctx)
        assert result is not None
        assert result.content == 'echo:help'

    @pytest.mark.asyncio
    async def test_alias_dispatched(self, router):
        ctx = _make_ctx('/?')
        result = await router.dispatch(ctx)
        assert result is not None
        assert result.content == 'echo:?'

    @pytest.mark.asyncio
    async def test_case_insensitive(self, router):
        ctx = _make_ctx('/HELP')
        result = await router.dispatch(ctx)
        assert result is not None

    @pytest.mark.asyncio
    async def test_unmatched_returns_none(self, router):
        ctx = _make_ctx('/unknown')
        result = await router.dispatch(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_priority_before_exact(self):
        router = CommandRouter()

        async def priority_handler(ctx):
            return CommandResult(type=CommandResultType.MESSAGE, content='priority')

        async def exact_handler(ctx):
            return CommandResult(type=CommandResultType.MESSAGE, content='exact')

        router._priority['test'] = priority_handler
        router._exact['test'] = exact_handler
        ctx = _make_ctx('/test')
        result = await router.dispatch(ctx)
        assert result.content == 'priority'


class TestPrefix:
    @pytest.mark.asyncio
    async def test_prefix_match(self):
        router = CommandRouter()
        router.register_prefix('config', _args_handler)
        ctx = _make_ctx('/config set key=value')
        result = await router.dispatch(ctx)
        assert result is not None

    @pytest.mark.asyncio
    async def test_longest_prefix_wins(self):
        router = CommandRouter()

        async def short_handler(ctx):
            return CommandResult(type=CommandResultType.MESSAGE, content='short')

        async def long_handler(ctx):
            return CommandResult(type=CommandResultType.MESSAGE, content='long')

        router.register_prefix('con', short_handler)
        router.register_prefix('config', long_handler)
        ctx = _make_ctx('/config-something')
        result = await router.dispatch(ctx)
        assert result.content == 'long'


class TestInterceptor:
    @pytest.mark.asyncio
    async def test_interceptor_fallback(self):
        router = CommandRouter()

        async def catch_all(ctx):
            return CommandResult(type=CommandResultType.MESSAGE, content=f'caught:{ctx.command_name}')

        router.register_interceptor(catch_all)
        ctx = _make_ctx('/anything')
        result = await router.dispatch(ctx)
        assert result is not None
        assert result.content == 'caught:anything'

    @pytest.mark.asyncio
    async def test_interceptor_skip_on_none(self):
        router = CommandRouter()

        async def skip(ctx):
            return None

        async def catch(ctx):
            return CommandResult(type=CommandResultType.MESSAGE, content='caught')

        router.register_interceptor(skip)
        router.register_interceptor(catch)
        ctx = _make_ctx('/test')
        result = await router.dispatch(ctx)
        assert result.content == 'caught'


class TestDispatchPriority:
    @pytest.mark.asyncio
    async def test_dispatch_priority_only(self):
        router = CommandRouter()
        router.register(
            CommandDef(name='stop', description='stop', priority=0),
            _echo_handler,
        )
        router.register(
            CommandDef(name='help', description='help'),
            _echo_handler,
        )
        ctx_stop = _make_ctx('/stop')
        assert await router.dispatch_priority(ctx_stop) is not None

        ctx_help = _make_ctx('/help')
        assert await router.dispatch_priority(ctx_help) is None

    def test_is_priority(self):
        router = CommandRouter()
        router.register(
            CommandDef(name='stop', description='stop', priority=0),
            _echo_handler,
        )
        assert router.is_priority('/stop')
        assert not router.is_priority('/help')
        assert not router.is_priority('not a command')


class TestListAndResolve:
    def test_list_commands(self):
        router = CommandRouter()
        router.register(
            CommandDef(name='a', description='aa', category='cat1'),
            _echo_handler,
        )
        router.register(
            CommandDef(name='b', description='bb', category='cat2'),
            _echo_handler,
        )
        result = router.list_commands()
        assert 'cat1' in result
        assert 'cat2' in result

    def test_resolve_by_name(self):
        router = CommandRouter()
        cmd_def = CommandDef(name='help', description='help', aliases=('?',))
        router.register(cmd_def, _echo_handler)
        assert router.resolve('help') is cmd_def
        assert router.resolve('?') is cmd_def
        assert router.resolve('unknown') is None
