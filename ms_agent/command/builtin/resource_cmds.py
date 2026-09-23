"""Slash commands for managed MCP servers and skills (same files as WebUI)."""
from __future__ import annotations

from ms_agent.command.router import CommandRouter
from ms_agent.command.scope import parse_optional_scope, work_dir_of
from ms_agent.command.types import (CommandContext, CommandDef, CommandResult,
                                    CommandResultType)
from ms_agent.command.usage import (arg_error, ledger_dir, same_as_webui,
                                    status_then_usage)

CMD_MCP = CommandDef(
    name='mcp',
    description='List/add/enable MCP servers (shared with WebUI mcp.json)',
    category='config',
)

CMD_SKILL_MANAGE = CommandDef(
    name='skills',
    description='List/add/enable skills (shared with WebUI skills.json)',
    category='config',
    aliases=('skill-mgr', ),
)


def _mcp_usage() -> str:
    return (
        'usage:\n'
        '  /mcp list [global|project]\n'
        '  /mcp add <name> [global|project] command=<cmd>\n'
        '  /mcp add <name> [global|project] url=<url>\n'
        '  /mcp update <name> [global|project] command=<cmd>|url=<url>\n'
        '  /mcp json <file.json>\n'
        '  /mcp enable|disable|remove <name> [global|project]\n'
        'Omitting scope on add writes this folder (project). '
        'WebUI Settings → MCP is the global page.\n'
        f'{same_as_webui("mcp.json")} Also project .ms_agent/mcp.json. '
        'New servers connect this session when possible; otherwise /new or restart.'
    )


def _skill_usage() -> str:
    return (
        'usage:\n'
        '  /skills list\n'
        '  /skills add <path> [global|project]\n'
        '  /skills enable|disable <id> [global|project]\n'
        '  /skills remove <id> [global|project]\n'
        f'Directory drop-in: global → {ledger_dir()}/skills, '
        'project → <work>/.ms_agent/skills. '
        'Omit scope: this folder (project) when TUI has --work-dir, '
        'otherwise this machine (global). '
        f'{same_as_webui("skills")} '
        'remove only deletes a managed copy, not auto-discovered skills.'
    )


_PROJECT_MCP_NOT_ON_SETTINGS = (
    'Not visible on WebUI Settings → MCP (that page is global). '
    'Add with `global` to show it there.'
)


def _home_work(ctx: CommandContext) -> tuple[str, str | None]:
    from ms_agent.project.paths import global_home
    return str(global_home()), work_dir_of(ctx)


def _parse_scope(tokens: list[str], default: str = 'project') -> tuple[str, list[str]]:
    """Optional last-token scope so a path/name can contain spaces."""
    if tokens and tokens[-1] in ('global', 'project'):
        return tokens[-1], tokens[:-1]
    return default, list(tokens)


def _split_kv(tokens: list[str]) -> tuple[list[str], dict[str, str]]:
    rest: list[str] = []
    fields: dict[str, str] = {}
    for tok in tokens:
        if '=' in tok:
            key, val = tok.split('=', 1)
            fields[key] = val
        else:
            rest.append(tok)
    return rest, fields


def _stdio_fields(fields: dict[str, str]) -> dict:
    """Match WebUI: command + args list (shlex-split the command line)."""
    import shlex
    out = dict(fields)
    if 'command' in out:
        parts = shlex.split(out['command'])
        extra = shlex.split(out.pop('args', '')) if out.get('args') else []
        if parts:
            out['command'] = parts[0]
            out['args'] = parts[1:] + extra
        else:
            out['args'] = extra
    elif 'url' in out:
        out.setdefault('type', 'streamable_http')
    return out


def _need_work(scope: str, work: str | None) -> CommandResult | None:
    if scope == 'project' and not work:
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content='Project scope needs a work dir (TUI --work-dir).',
        )
    return None


def _mcp_list_text(mgr, scope: str) -> str:
    rows = mgr.list(scope if scope != 'merged' else 'merged')
    if not rows:
        return 'No MCP servers.'
    lines = [f'MCP servers ({scope}):']
    for name, entry in rows.items():
        on = 'on' if entry.get('enabled', True) is not False else 'off'
        how = entry.get('command') or entry.get('url') or '?'
        lines.append(f'  [{on}] {name}  {how}')
    return '\n'.join(lines)


async def cmd_mcp(ctx: CommandContext) -> CommandResult:
    arg = (ctx.args or '').strip()
    home, work = _home_work(ctx)
    from ms_agent.config.mcp_manager import MCPConfigManager
    mgr = MCPConfigManager(home, work)
    if not arg:
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=status_then_usage(_mcp_list_text(mgr, 'merged'), _mcp_usage()),
        )
    if arg in ('help', '-h', '--help'):
        return CommandResult(type=CommandResultType.MESSAGE, content=_mcp_usage())
    import shlex
    try:
        parts = shlex.split(arg)
    except ValueError:
        parts = arg.split()
    action = parts[0].lower()
    tokens = parts[1:]

    if action == 'list':
        scope, _ = _parse_scope(tokens, default='merged')
        if scope not in ('global', 'project', 'merged'):
            scope = 'merged'
        if scope == 'project':
            miss = _need_work(scope, work)
            if miss:
                return miss
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=_mcp_list_text(mgr, scope),
        )

    if action == 'json':
        if not tokens:
            return arg_error('/mcp json <file.json>', ctx=ctx)
        n = mgr.import_cursor_format(tokens[0])
        note = await _reload_mcp(ctx)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Imported {n} server(s). {note}',
        )

    if action in ('enable', 'disable', 'remove'):
        if not tokens:
            return arg_error(
                f'/mcp {action} <name> [global|project]', ctx=ctx)
        scope, rest = _parse_scope(tokens, default='project')
        miss = _need_work(scope, work)
        if miss:
            return miss
        if not rest:
            return arg_error(
                f'/mcp {action} <name> [global|project]', ctx=ctx)
        name = rest[0]
        try:
            if action == 'remove':
                mgr.remove(name, scope=scope)
            else:
                mgr.set_enabled(name, action == 'enable', scope=scope)
        except KeyError as exc:
            return CommandResult(
                type=CommandResultType.MESSAGE, content=str(exc))
        note = await _reload_mcp(ctx)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'{action} {name} ({scope}). {note}',
        )

    if action == 'add':
        rest, fields = _split_kv(tokens)
        explicit = bool(rest and rest[-1] in ('global', 'project'))
        scope, rest = _parse_scope(rest, default='project')
        miss = _need_work(scope, work)
        if miss:
            return miss
        if not rest:
            return arg_error(
                '/mcp add <name> [global|project] command=<cmd>|url=<url>',
                ctx=ctx,
            )
        name = ' '.join(rest)
        if 'command' not in fields and 'url' not in fields:
            return CommandResult(
                type=CommandResultType.MESSAGE,
                content='Need command=<cmd> or url=<url>.',
            )
        mgr.add(name, _stdio_fields(fields), scope=scope)
        note = await _reload_mcp(ctx)
        lines = [f'Added {name} ({scope}). {note}']
        if scope == 'project' and not explicit:
            lines.append(_PROJECT_MCP_NOT_ON_SETTINGS)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content='\n'.join(lines),
        )

    if action == 'update':
        rest, fields = _split_kv(tokens)
        scope, rest = _parse_scope(rest, default='project')
        miss = _need_work(scope, work)
        if miss:
            return miss
        if not rest or not fields:
            return arg_error(
                '/mcp update <name> [global|project] command=<cmd>|url=<url>',
                ctx=ctx,
            )
        name = ' '.join(rest)
        try:
            mgr.update(name, _stdio_fields(fields), scope=scope)
        except KeyError as exc:
            return CommandResult(
                type=CommandResultType.MESSAGE, content=str(exc))
        note = await _reload_mcp(ctx)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Updated {name} ({scope}). {note}',
        )

    return arg_error(
        '/mcp list|add|update|json|enable|disable|remove ...',
        reason=f'Unknown mcp action {action!r}',
        note='Type /mcp for all commands',
        ctx=ctx,
    )


async def _reload_mcp(ctx: CommandContext) -> str:
    home, work = _home_work(ctx)
    from ms_agent.tui.managed_config import resolve_mcp_config
    cfg = resolve_mcp_config(home, work)
    agent = ctx.runtime
    tm = getattr(agent, 'tool_manager', None) if agent is not None else None
    client = getattr(tm, 'servers', None) if tm is not None else None
    if client is None or not cfg or not hasattr(client, 'add_mcp_config'):
        return 'Takes effect on /new or restart.'
    try:
        await client.add_mcp_config(cfg)
        if hasattr(tm, 'reindex_tool'):
            await tm.reindex_tool()
        return 'Connected for this session.'
    except Exception as exc:  # noqa: BLE001 - surface, do not crash TUI
        return f'Saved; connect failed ({exc}). /new or restart to apply.'


async def cmd_skills(ctx: CommandContext) -> CommandResult:
    arg = (ctx.args or '').strip()
    home, work = _home_work(ctx)
    from ms_agent.config.skills_manager import SkillsConfigManager
    mgr = SkillsConfigManager(global_dir=home)
    runtime = getattr(ctx.runtime, '_skill_runtime', None)
    if not arg:
        listed = (
            _format_skill_rows(runtime.list_all()) if runtime is not None else
            _list_skills_from_disk(mgr, work))
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=status_then_usage(listed.content, _skill_usage()),
        )
    if arg in ('help', '-h', '--help'):
        return CommandResult(
            type=CommandResultType.MESSAGE, content=_skill_usage())
    import shlex
    try:
        parts = shlex.split(arg)
    except ValueError:
        parts = arg.split()
    action = parts[0].lower()
    tokens = parts[1:]

    if action == 'list':
        if runtime is not None:
            return _format_skill_rows(runtime.list_all())
        return _list_skills_from_disk(mgr, work)

    if action in ('enable', 'disable'):
        resolved = _resolve_skill_scope(
            tokens,
            work,
            syntax=f'/skills {action} <id> [global|project]',
            ctx=ctx)
        if isinstance(resolved, CommandResult):
            return resolved
        scope, rest = resolved
        skill_id = ' '.join(rest)
        mgr.set_skill_enabled(
            skill_id, action == 'enable', scope=scope, project_path=work)
        _resync_skills(ctx, mgr, home, work)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'{action} {skill_id} ({scope}).',
        )

    if action == 'add':
        resolved = _resolve_skill_scope(
            tokens,
            work,
            syntax='/skills add <path> [global|project]',
            ctx=ctx)
        if isinstance(resolved, CommandResult):
            return resolved
        scope, rest = resolved
        try:
            names = mgr.import_from_path(
                ' '.join(rest), scope=scope, project_path=work)
        except FileNotFoundError as exc:
            return CommandResult(
                type=CommandResultType.MESSAGE, content=str(exc))
        if not names:
            return CommandResult(
                type=CommandResultType.MESSAGE,
                content='No SKILL.md found under that path.',
            )
        _resync_skills(ctx, mgr, home, work)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=(
                'Imported: ' + ', '.join(names)
                + f' ({scope}). Available this session.'),
        )

    if action == 'remove':
        resolved = _resolve_skill_scope(
            tokens,
            work,
            syntax='/skills remove <id> [global|project]',
            ctx=ctx)
        if isinstance(resolved, CommandResult):
            return resolved
        scope, rest = resolved
        skill_id = ' '.join(rest)
        try:
            dest = mgr.remove_imported(
                skill_id, scope=scope, project_path=work)
        except (FileNotFoundError, ValueError) as exc:
            return CommandResult(
                type=CommandResultType.MESSAGE, content=str(exc))
        _resync_skills(ctx, mgr, home, work)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Removed managed skill {skill_id} ({dest}).',
        )

    return arg_error(
        '/skills list|add|enable|disable|remove ...',
        reason=f'Unknown skills action {action!r}',
        note='Type /skills for all commands',
        ctx=ctx,
    )


def _default_skill_scope(work: str | None) -> str:
    return 'project' if work else 'global'


def _resolve_skill_scope(
    tokens: list[str],
    work: str | None,
    *,
    syntax: str,
    ctx: CommandContext,
) -> tuple[str, list[str]] | CommandResult:
    if not tokens:
        return arg_error(syntax, ctx=ctx)
    scope, rest = parse_optional_scope(tokens)
    if not rest:
        return arg_error(syntax, ctx=ctx)
    if scope is None:
        scope = _default_skill_scope(work)
    miss = _need_work(scope, work)
    if miss:
        return miss
    return scope, rest


def _format_skill_rows(rows) -> CommandResult:
    if not rows:
        return CommandResult(
            type=CommandResultType.MESSAGE, content='No skills.')
    lines = ['Skills:']
    for row in rows:
        on = 'on' if row.get('enabled') else 'off'
        lines.append(
            f'  [{on}] {row["skill_id"]}  {row.get("name") or ""}'.rstrip())
    return CommandResult(
        type=CommandResultType.MESSAGE, content='\n'.join(lines))


def _list_skills_from_disk(mgr, work: str | None) -> CommandResult:
    """Scan live trees the same way WebUI does (presence = registered)."""
    from ms_agent.skill.loader import SkillLoader
    merged = mgr.load_merged(work)
    sources = [
        source for source in (merged.get('sources') or [])
        if isinstance(source, str)
    ]
    try:
        discovered = SkillLoader().discover_skills(sources)
    except Exception:  # noqa: BLE001 — listing must not crash the TUI
        discovered = {}
    disabled = set(merged.get('disabled') or [])
    by_id: dict[str, dict] = {}
    for desc in discovered.values():
        by_id[desc.skill_id] = {
            'skill_id': desc.skill_id,
            'name': desc.name or '',
            'enabled': desc.skill_id not in disabled,
        }
    rows = [by_id[sid] for sid in sorted(by_id)]
    return _format_skill_rows(rows)


def _resync_skills(ctx, mgr, home: str, work: str | None) -> None:
    agent = ctx.runtime
    if agent is None:
        return
    from ms_agent.tui.managed_config import merge_skills_into_config
    merge_skills_into_config(agent.config, home, work)
    runtime = getattr(agent, '_skill_runtime', None)
    if runtime is not None:
        runtime.sync_with_config(getattr(agent.config, 'skills', None))
        runtime.reload_all()


def register_resource_commands(router: CommandRouter) -> None:
    router.register(CMD_MCP, cmd_mcp)
    router.register(CMD_SKILL_MANAGE, cmd_skills)
