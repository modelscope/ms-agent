"""Slash command for memory on/off (same files WebUI personalization / project)."""
from __future__ import annotations

from dataclasses import replace

from ms_agent.command.router import CommandRouter
from ms_agent.command.scope import work_dir_of
from ms_agent.command.types import (CommandContext, CommandDef, CommandResult,
                                    CommandResultType)
from ms_agent.command.usage import arg_error, status_then_usage

CMD_MEMORY = CommandDef(
    name='memory',
    description='Turn memory on or off',
    category='config',
)

_USAGE = (
    'usage:\n'
    '  /memory\n'
    '  /memory on|off                 (this project)\n'
    '  /memory project on|off\n'
    '  /memory global on|off          (default for newly opened folders)\n'
    'Project on/off turns memory on for this folder. '
    'Global on/off is the default for newly opened folders. '
    'Memory is written to MEMORY.md under <work>/.ms_agent/memory/.'
)

_ON = frozenset({'on', 'true', '1', 'enable', 'enabled'})
_OFF = frozenset({'off', 'false', '0', 'disable', 'disabled'})


def _work_dir(ctx: CommandContext) -> str | None:
    return work_dir_of(ctx)


def _pm():
    from ms_agent.project import ProjectManager
    from ms_agent.project.paths import global_home
    return ProjectManager(base_dir=str(global_home()))


def _project(ctx: CommandContext):
    work = _work_dir(ctx)
    if not work:
        return None
    return _pm().find_by_path(work)


def _status_text(ctx: CommandContext) -> str:
    from ms_agent.personalization.settings import PersonalizationSettings
    loaded = PersonalizationSettings().load()
    g_on = 'on' if loaded.memory_enabled else 'off'
    lines = [
        f'Global default: {g_on}',
        '(applies when a new folder is opened)',
    ]
    project = _project(ctx)
    if project is None:
        lines.append('Project: (no work dir)')
    else:
        p_on = 'on' if project.memory_enabled else 'off'
        lines.append(f'Project: {p_on}  id={project.id}')
    return status_then_usage('\n'.join(lines), _USAGE)


def _parse_bool(token: str) -> bool | None:
    low = token.lower()
    if low in _ON:
        return True
    if low in _OFF:
        return False
    return None


def _arm_memory(ctx: CommandContext) -> None:
    """The next user message should try to start file memory."""
    runtime = getattr(ctx, 'runtime', None)
    if runtime is not None:
        runtime._memory_pending = True


async def _apply_live(ctx: CommandContext, project) -> str:
    """Arm the next user message. The command does not patch ``Runtime``.

    ``ctx.runtime`` is the session ``Runtime``, which has no config. The
    ledger is already saved; ``live_config`` writes ``agent.config`` and
    starts or drops the memory tools.
    """
    from omegaconf import OmegaConf

    from ms_agent.personalization.memory_apply import apply_project_memory
    _arm_memory(ctx)
    kind = apply_project_memory(OmegaConf.create({}), project)
    if kind == 'vector-unavailable':
        return '当前会话不会启用该记忆后端。'
    return ''


async def cmd_memory(ctx: CommandContext) -> CommandResult:
    arg = (ctx.args or '').strip()
    if not arg or arg in ('help', '-h', '--help', 'status'):
        return CommandResult(
            type=CommandResultType.MESSAGE, content=_status_text(ctx))

    import shlex
    try:
        parts = shlex.split(arg)
    except ValueError:
        parts = arg.split()
    action = parts[0].lower()
    rest = parts[1:]

    if action in ('global', 'project'):
        return await _cmd_toggle(ctx, action, rest)
    if action in _ON or action in _OFF:
        return await _cmd_toggle(ctx, action, rest)
    return arg_error(
        '/memory on|off | /memory global|project on|off',
        reason=f'Unknown memory action {action!r}',
        note='Type /memory for status and all commands',
        ctx=ctx,
    )


async def _cmd_toggle(ctx: CommandContext, action: str,
                      rest: list[str]) -> CommandResult:
    from ms_agent.personalization.settings import PersonalizationSettings

    scope = 'project'
    token = action
    if action in ('global', 'project'):
        scope = action
        if not rest:
            return arg_error(
                f'/memory {scope} on|off', ctx=ctx)
        token = rest[0]
    enabled = _parse_bool(token)
    if enabled is None:
        return arg_error('/memory on|off', ctx=ctx)

    if scope == 'global':
        settings = PersonalizationSettings()
        loaded = settings.load()
        settings.save(replace(loaded, memory_enabled=enabled))
        state = 'on' if enabled else 'off'
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=(
                f'Global memory default → {state}. '
                'New folders inherit this; this project is unchanged.'),
        )

    project = _project(ctx)
    if project is None:
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content='Project memory needs a work dir (TUI --work-dir).',
        )
    updated = _pm().update(project.id, memory_enabled=enabled)
    note = await _apply_live(ctx, updated)
    state = 'on' if enabled else 'off'
    content = f'Project memory → {state}.'
    if note:
        content = f'{content} {note}'
    return CommandResult(
        type=CommandResultType.MESSAGE,
        content=content,
    )


def register_memory_commands(router: CommandRouter) -> None:
    router.register(CMD_MEMORY, cmd_memory)
