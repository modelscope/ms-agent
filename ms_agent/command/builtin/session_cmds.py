from ms_agent.command.router import CommandRouter
from ms_agent.command.types import (
    CommandContext,
    CommandDef,
    CommandResult,
    CommandResultType,
)

CMD_STOP = CommandDef(
    name='stop',
    description='Stop the current agent execution',
    category='session',
    priority=0,
    aliases=('abort', 'cancel'),
)

CMD_NEW = CommandDef(
    name='new',
    description='End current session',
    category='session',
    aliases=('reset',),
)

CMD_STATUS = CommandDef(
    name='status',
    description='Show current agent status',
    category='session',
)


async def cmd_stop(ctx: CommandContext) -> CommandResult:
    if ctx.runtime:
        ctx.runtime.should_stop = True
    return CommandResult(type=CommandResultType.MESSAGE, content='Agent stopped.')


async def cmd_new(ctx: CommandContext) -> CommandResult:
    if ctx.runtime:
        ctx.runtime.should_stop = True
    return CommandResult(
        type=CommandResultType.QUIT, content='Session ended. Start a new one.'
    )


async def cmd_status(ctx: CommandContext) -> CommandResult:
    if ctx.runtime:
        content = (
            f'Round: {ctx.runtime.round}\n'
            f'Tag: {ctx.runtime.tag}\n'
            f'Should stop: {ctx.runtime.should_stop}'
        )
    else:
        content = 'No active agent.'
    return CommandResult(type=CommandResultType.MESSAGE, content=content)


def register_session_commands(router: CommandRouter) -> None:
    router.register(CMD_STOP, cmd_stop)
    router.register(CMD_NEW, cmd_new)
    router.register(CMD_STATUS, cmd_status)
