from ms_agent.command.router import CommandRouter
from ms_agent.command.types import (
    CommandContext,
    CommandDef,
    CommandResult,
    CommandResultType,
)

CMD_HELP = CommandDef(
    name='help',
    description='Show available commands',
    category='info',
    aliases=('?',),
)

CMD_VERSION = CommandDef(
    name='version',
    description='Show MS-Agent version',
    category='info',
)


async def cmd_help(ctx: CommandContext) -> CommandResult:
    router = ctx.extra.get('router')
    if not router:
        return CommandResult(
            type=CommandResultType.MESSAGE, content='No commands available.'
        )

    lines = ['Available commands:\n']
    for category, cmds in router.list_commands(ctx.source).items():
        lines.append(f'\n  [{category}]')
        for cmd in cmds:
            aliases = f' ({", ".join(cmd.aliases)})' if cmd.aliases else ''
            lines.append(f'    /{cmd.name}{aliases} — {cmd.description}')

    return CommandResult(
        type=CommandResultType.MESSAGE, content='\n'.join(lines)
    )


async def cmd_version(ctx: CommandContext) -> CommandResult:
    try:
        from ms_agent import __version__

        ver = __version__
    except (ImportError, AttributeError):
        ver = 'unknown'
    return CommandResult(
        type=CommandResultType.MESSAGE, content=f'MS-Agent v{ver}'
    )


def register_info_commands(router: CommandRouter) -> None:
    router.register(CMD_HELP, cmd_help)
    router.register(CMD_VERSION, cmd_version)
