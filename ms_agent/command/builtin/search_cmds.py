"""Slash command for web-search settings (same settings.json block as WebUI)."""
from __future__ import annotations

from ms_agent.command.router import CommandRouter
from ms_agent.command.types import (CommandContext, CommandDef, CommandResult,
                                    CommandResultType)
from ms_agent.command.usage import arg_error, same_as_webui, status_then_usage

CMD_SEARCH = CommandDef(
    name='search',
    description='Show or set the web-search engine (shared with WebUI)',
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
        f'{same_as_webui("settings.json")} '
        'Takes effect on the next turn, or /new if search was already connected.'
    )


def _mgr():
    from ms_agent.config.search_settings import SearchSettingsManager
    from ms_agent.project.paths import global_home
    return SearchSettingsManager(global_home())


def _status_text(mgr) -> str:
    from ms_agent.config.search_settings import requires_key
    cur = mgr.get()
    on = 'on' if cur.enabled else 'off'
    key = 'set' if cur.has_key else 'missing'
    if not requires_key(cur.engine):
        key = 'not required'
    elif cur.supports_keyless and not cur.has_key:
        key = 'missing (keyless tier may still work)'
    lines = [
        f'Search: {on}',
        f'Engine: {cur.engine}',
        f'API key: {key}',
        'Switch: /search engine <id>   Key: /search key <value>',
        'List engines: /search list',
    ]
    return '\n'.join(lines)


def _apply_runtime(ctx: CommandContext, mgr) -> str:
    agent = ctx.runtime
    cfg = getattr(agent, 'config', None) if agent is not None else None
    if cfg is None:
        return 'Takes effect on /new or restart.'
    try:
        from omegaconf import OmegaConf
        OmegaConf.update(
            cfg, 'tools.web_search', mgr.raw_block(), merge=True)
        return 'Next turn uses this setting (or /new if search was already connected).'
    except Exception:
        return 'Saved; /new or restart to apply in this session.'


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
        lines = ['Search engines (shared with WebUI):']
        current = mgr.get().engine
        for row in mgr.list_engines():
            mark = '*' if row['id'] == current else ' '
            key = 'key=set' if row['has_key'] else (
                'key=n/a' if not row['requires_key'] else 'key=missing')
            extra = ' keyless-ok' if row['supports_keyless'] else ''
            lines.append(
                f'  {mark} {row["id"]}  {row["label"]}  {key}{extra}')
        return CommandResult(
            type=CommandResultType.MESSAGE, content='\n'.join(lines))

    if action in ('enable', 'on'):
        mgr.set_enabled(True)
        note = _apply_runtime(ctx, mgr)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Search enabled. {note}',
        )
    if action in ('disable', 'off'):
        mgr.set_enabled(False)
        note = _apply_runtime(ctx, mgr)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Search disabled. {note}',
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
        note = _apply_runtime(ctx, mgr)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Engine → {cur.engine}. {note}',
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
        note = _apply_runtime(ctx, mgr)
        verb = 'cleared' if clear else 'saved'
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'API key {verb} for {mgr.get().engine}. {note}',
        )

    return arg_error(
        '/search engine|key|list|enable|disable ...',
        reason=f'Unknown search action {action!r}',
        note='Type /search for status and all commands',
        ctx=ctx,
    )


def register_search_commands(router: CommandRouter) -> None:
    router.register(CMD_SEARCH, cmd_search)
