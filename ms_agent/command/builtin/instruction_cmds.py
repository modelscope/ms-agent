"""Slash commands for AGENTS.md / PROFILE.md (same files WebUI settings write)."""
from __future__ import annotations

from pathlib import Path

from ms_agent.command.router import CommandRouter
from ms_agent.command.scope import work_dir_of
from ms_agent.command.types import (CommandContext, CommandDef, CommandResult,
                                    CommandResultType)
from ms_agent.command.usage import (arg_error, ledger_file, same_as_webui,
                                    status_then_usage)

CMD_INSTRUCTION = CommandDef(
    name='instruction',
    description='Show or set AGENTS.md instructions (shared with WebUI)',
    category='config',
    aliases=('ins', ),
)

CMD_PROFILE = CommandDef(
    name='profile',
    description='Show or set PROFILE.md (shared with WebUI)',
    category='config',
)


def _ins_usage() -> str:
    return (
        'usage:\n'
        '  /instruction\n'
        '  /instruction global|project\n'
        '  /instruction global|project <text>\n'
        '  /instruction global|project clear\n'
        f'Global → {ledger_file("AGENTS.md")} '
        '(user region under the seeded header).\n'
        'Project → <work>/.ms_agent/AGENTS.md (never the repo-root AGENTS.md).\n'
        f'{same_as_webui("AGENTS.md")} '
        'Takes effect on the next turn (files are read live).'
    )


def _profile_usage() -> str:
    return (
        'usage:\n'
        '  /profile\n'
        '  /profile callme <name>\n'
        '  /profile callme clear\n'
        '  /profile about <text>\n'
        '  /profile about clear\n'
        f'Writes {ledger_file("PROFILE.md")} (Call me line + free region). '
        f'{same_as_webui("PROFILE.md")} '
        'Takes effect on the next turn.'
    )


_CLEAR = frozenset({'clear', '-', 'none'})


def _work_dir(ctx: CommandContext) -> str | None:
    return work_dir_of(ctx)


def _preview(text: str, empty: str = '(empty)') -> str:
    body = (text or '').strip()
    if not body:
        return empty
    if len(body) > 1200:
        return body[:1200] + '\n... (truncated)'
    return body


def _show_instructions(work_dir: str | None) -> str:
    from ms_agent.prompting import workspace_files as wf
    lines = [f'Global ({ledger_file("AGENTS.md")}):', _preview(wf.read_global_instruction())]
    if work_dir:
        lines.extend([
            '',
            f'Project ({Path(work_dir) / ".ms_agent" / "AGENTS.md"}):',
            _preview(wf.read_project_instruction(work_dir)),
        ])
        root = Path(work_dir) / 'AGENTS.md'
        try:
            root_text = root.read_text(encoding='utf-8', errors='replace')
        except OSError:
            root_text = ''
        if root_text.strip():
            lines.extend([
                '',
                '(Repo-root AGENTS.md also exists and is injected, but '
                '/instruction never writes it.)',
            ])
    else:
        lines.extend(['', 'Project: (no work dir — start TUI with --work-dir)'])
    return status_then_usage('\n'.join(lines), _ins_usage())


async def cmd_instruction(ctx: CommandContext) -> CommandResult:
    from ms_agent.prompting import workspace_files as wf

    arg = (ctx.args or '').strip()
    work_dir = _work_dir(ctx)
    if not arg:
        return CommandResult(
            type=CommandResultType.MESSAGE, content=_show_instructions(work_dir))

    import shlex
    try:
        parts = shlex.split(arg)
    except ValueError:
        parts = arg.split()
    scope = parts[0].lower()
    rest = parts[1:]
    if scope not in ('global', 'project', 'help', '-h', '--help'):
        return arg_error(
            '/instruction global|project [text|clear]',
            reason=f'Unknown instruction scope {scope!r}',
            ctx=ctx,
        )
    if scope in ('help', '-h', '--help'):
        return CommandResult(
            type=CommandResultType.MESSAGE, content=_ins_usage())

    if scope == 'project' and not work_dir:
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content='No work dir (output_dir). Start TUI with --work-dir.',
        )

    if not rest:
        if scope == 'global':
            body = wf.read_global_instruction()
            label = f'Global ({ledger_file("AGENTS.md")})'
        else:
            body = wf.read_project_instruction(work_dir)
            label = f'Project ({Path(work_dir) / ".ms_agent" / "AGENTS.md"})'
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'{label}:\n{_preview(body)}',
        )

    text = '' if len(rest) == 1 and rest[0].lower() in _CLEAR else ' '.join(rest)
    if scope == 'global':
        wf.write_global_instruction(text)
        dest = ledger_file('AGENTS.md')
    else:
        wf.write_project_instruction(work_dir, text)
        dest = str(Path(work_dir) / '.ms_agent' / 'AGENTS.md')
    verb = 'cleared' if not text else 'saved'
    return CommandResult(
        type=CommandResultType.MESSAGE,
        content=f'{verb.capitalize()} {scope} instruction → {dest}. Next turn uses it.',
    )


def _show_profile() -> str:
    from ms_agent.prompting import workspace_files as wf
    call_me, about = wf.read_profile()
    lines = [
        f'Call me: {call_me or "(unset)"}',
        'About:',
        _preview(about),
    ]
    return status_then_usage('\n'.join(lines), _profile_usage())


async def cmd_profile(ctx: CommandContext) -> CommandResult:
    from ms_agent.prompting import workspace_files as wf

    arg = (ctx.args or '').strip()
    if not arg or arg in ('help', '-h', '--help'):
        return CommandResult(
            type=CommandResultType.MESSAGE, content=_show_profile())

    import shlex
    try:
        parts = shlex.split(arg)
    except ValueError:
        parts = arg.split()
    action = parts[0].lower()
    rest = parts[1:]
    if action in ('callme', 'call', 'name'):
        if not rest:
            call_me, _ = wf.read_profile()
            return CommandResult(
                type=CommandResultType.MESSAGE,
                content=f'Call me: {call_me or "(unset)"}',
            )
        value = '' if len(rest) == 1 and rest[0].lower() in _CLEAR else ' '.join(rest)
        wf.write_profile(call_me=value)
        verb = 'cleared' if not value else f'set to {value}'
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Call me {verb}. Next turn uses {ledger_file("PROFILE.md")}.',
        )
    if action in ('about', 'desc', 'description', 'set'):
        if not rest:
            _, about = wf.read_profile()
            return CommandResult(
                type=CommandResultType.MESSAGE,
                content=f'About:\n{_preview(about)}',
            )
        value = '' if len(rest) == 1 and rest[0].lower() in _CLEAR else ' '.join(rest)
        wf.write_profile(description=value)
        verb = 'cleared' if not value else 'saved'
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Profile about {verb}. Next turn uses {ledger_file("PROFILE.md")}.',
        )
    return arg_error(
        '/profile callme <name>|clear   or   /profile about <text>|clear',
        reason=f'Unknown profile action {action!r}',
        note='Type /profile for all commands',
        ctx=ctx,
    )


def register_instruction_commands(router: CommandRouter) -> None:
    router.register(CMD_INSTRUCTION, cmd_instruction)
    router.register(CMD_PROFILE, cmd_profile)
