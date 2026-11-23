"""Slash command that shows where AGENTS.md and PROFILE.md live."""
from __future__ import annotations

from pathlib import Path

from ms_agent.command.router import CommandRouter
from ms_agent.command.scope import work_dir_of
from ms_agent.command.types import (CommandContext, CommandDef, CommandResult,
                                    CommandResultType)
from ms_agent.command.usage import ledger_file

CMD_PROFILE = CommandDef(
    name='profile',
    description='Show where AGENTS.md and PROFILE.md live',
    category='config',
)


def _work_dir(ctx: CommandContext) -> str | None:
    return work_dir_of(ctx)


def _show_profile(ctx: CommandContext) -> str:
    work_dir = _work_dir(ctx)
    project = (
        str(Path(work_dir) / '.ms_agent' / 'AGENTS.md')
        if work_dir else '<work>/.ms_agent/AGENTS.md')
    lines = [
        'AGENTS.md',
        f'  Global: {ledger_file("AGENTS.md")}',
        f'  Project: {project}',
        'PROFILE.md',
        f'  Global: {ledger_file("PROFILE.md")}',
        'Edit these files directly. The next turn reads them.',
    ]
    return '\n'.join(lines)


async def cmd_profile(ctx: CommandContext) -> CommandResult:
    body = _show_profile(ctx)
    arg = (ctx.args or '').strip()
    if arg and arg not in ('help', '-h', '--help', 'show'):
        body = (
            'Profile only shows these files. Edit them directly.\n\n' + body)
    return CommandResult(type=CommandResultType.MESSAGE, content=body)


def register_instruction_commands(router: CommandRouter) -> None:
    router.register(CMD_PROFILE, cmd_profile)
