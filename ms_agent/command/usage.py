# Copyright (c) ModelScope Contributors. All rights reserved.
"""Focused usage errors for slash commands.

Bare ``/cmd`` (or ``/cmd help``) still shows the full sheet. A recognized
subcommand invoked with the wrong shape should say what was missing and
print that one syntax line — not the entire help dump.
"""
from __future__ import annotations

from ms_agent.command.types import CommandContext, CommandResult, CommandResultType


def ledger_dir() -> str:
    """Effective global home for this process (honors MS_AGENT_HOME)."""
    from ms_agent.project.paths import global_home
    return str(global_home())


def ledger_file(rel: str) -> str:
    """``{global_home}/{rel}`` at call time (not import time)."""
    return f'{ledger_dir()}/{rel}'


def same_as_webui(rel: str = '') -> str:
    """Shared-ledger line: live path, then the env var that produced it.

    The path is not a secret. Showing only ``MS_AGENT_HOME`` makes a person
    expand it themselves; showing only ``~/.ms_agent`` lies when the env is set.
    """
    loc = ledger_file(rel) if rel else ledger_dir()
    return f'Same as WebUI: {loc} (from MS_AGENT_HOME).'


def status_then_usage(status: str, usage: str) -> str:
    """Bare ``/cmd``: a short identity card, then the usage sheet.

    Status stays a handful of lines (or a truncated preview). The sheet is
    below so the current value is what the user sees first.
    """
    body = (status or '').rstrip()
    sheet = (usage or '').strip()
    if not body:
        return sheet
    if not sheet:
        return body
    return f'{body}\n\n{sheet}'


def arg_error(
    syntax: str,
    *,
    reason: str = '',
    note: str = '',
    got: str = '',
    ctx: CommandContext | None = None,
) -> CommandResult:
    """Build a short parse/usage error for a known command.

    ``syntax`` is the one line the user should type, e.g.
    ``/model catalog remove <provider> <model>``.
    """
    if ctx is not None and not got:
        got = str(getattr(ctx, 'raw_input', '') or '').strip()
    lines: list[str] = []
    if reason:
        text = reason.rstrip()
        if text[-1:] not in '.!?':
            text += '.'
        lines.append(text)
    lines.append(f'Need: {syntax}')
    if got:
        lines.append(f'Got:  {got}')
    if note:
        lines.append(note)
    return CommandResult(type=CommandResultType.MESSAGE, content='\n'.join(lines))
