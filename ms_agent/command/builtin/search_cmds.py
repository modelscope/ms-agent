"""Slash command for web-search settings (same settings.json block as WebUI)."""
from __future__ import annotations

from ms_agent.command.router import CommandRouter
from ms_agent.command.types import (CommandContext, CommandDef, CommandResult,
                                    CommandResultType)
from ms_agent.command.usage import (arg_error, ledger_file, status_then_usage)

CMD_SEARCH = CommandDef(
    name='search',
    description='Show or set the web-search engine',
    category='config',
)


def _usage() -> str:
    return (
        'usage:\n'
        '  /search\n'
        '  /search list\n'
        '  /search engine <tavily|exa|serpapi|arxiv>\n'
        '  /search key <value>\n'
        '  /search key clear\n'
        '  /search enable|disable\n'
        f'Saved in {ledger_file("settings.json")}.'
    )


def _mgr():
    from ms_agent.config.search_settings import SearchSettingsManager
    from ms_agent.project.paths import global_home
    return SearchSettingsManager(global_home())


def _engine_notice(engine: str, *, has_key: bool, requires_key: bool) -> str:
    from ms_agent.tools.search.availability import unavailable_notice
    return unavailable_notice(
        engine, has_key=has_key, requires_key=requires_key) or ''


def _status_text(mgr) -> str:
    from ms_agent.config.search_settings import requires_key
    cur = mgr.get()
    on = 'on' if cur.enabled else 'off'
    key = 'set' if cur.has_key else 'missing'
    needed = requires_key(cur.engine)
    if not needed:
        key = 'not required'
    elif cur.supports_keyless and not cur.has_key:
        key = 'missing (keyless tier may still work)'
    lines = [
        f'Search: {on}',
        f'Engine: {cur.engine}',
        f'API key: {key}',
    ]
    notice = _engine_notice(
        cur.engine, has_key=cur.has_key, requires_key=needed)
    if notice:
        lines.append(notice)
    lines.extend([
        'Switch: /search engine <id>   Key: /search key <value>',
        'List engines: /search list',
    ])
    return '\n'.join(lines)


async def cmd_search(ctx: CommandContext) -> CommandResult:
    arg = (ctx.args or '').strip()
    mgr = _mgr()
    if not arg or arg in ('help', '-h', '--help'):
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=status_then_usage(_status_text(mgr), _usage()),
        )

    import shlex
    try:
        parts = shlex.split(arg)
    except ValueError:
        parts = arg.split()
    action = parts[0].lower()
    rest = parts[1:]

    if action == 'list':
        lines = ['Search engines:']
        current = mgr.get().engine
        for row in mgr.list_engines():
            mark = '*' if row['id'] == current else ' '
            key = 'key=set' if row['has_key'] else (
                'key=n/a' if not row['requires_key'] else 'key=missing')
            extra = ' keyless-ok' if row['supports_keyless'] else ''
            notice = _engine_notice(
                row['id'],
                has_key=row['has_key'],
                requires_key=row['requires_key'],
            )
            if notice:
                extra = f'{extra}  {notice}'
            lines.append(
                f'  {mark} {row["id"]}  {row["label"]}  {key}{extra}')
        return CommandResult(
            type=CommandResultType.MESSAGE, content='\n'.join(lines))

    if action in ('enable', 'on'):
        mgr.set_enabled(True)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content='Search enabled.',
        )
    if action in ('disable', 'off'):
        mgr.set_enabled(False)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content='Search disabled.',
        )

    if action == 'engine':
        if not rest:
            return arg_error(
                '/search engine <tavily|exa|serpapi|arxiv>', ctx=ctx)
        try:
            cur = mgr.set_engine(rest[0])
        except ValueError as exc:
            return CommandResult(
                type=CommandResultType.MESSAGE, content=str(exc))
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Engine → {cur.engine}.',
        )

    if action == 'key':
        if not rest:
            return arg_error('/search key <value>|clear', ctx=ctx)
        raw = ' '.join(rest)
        clear = raw.lower() in ('clear', 'none', '-')
        try:
            mgr.set_api_key(None if clear else raw)
        except ValueError as exc:
            return CommandResult(
                type=CommandResultType.MESSAGE, content=str(exc))
        verb = 'cleared' if clear else 'saved'
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'API key {verb} for {mgr.get().engine}.',
        )

    return arg_error(
        '/search engine|key|list|enable|disable ...',
        reason=f'Unknown search action {action!r}',
        note='Type /search for status and all commands',
        ctx=ctx,
    )


def register_search_commands(router: CommandRouter) -> None:
    router.register(CMD_SEARCH, cmd_search)
