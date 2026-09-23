# Copyright (c) ModelScope Contributors. All rights reserved.
"""Scope tokens for slash commands: a default when one exists, else a menu.

Claude-style: only silent-default a scope when it cannot send the user looking
in the wrong place. Otherwise pick interactively (TUI arrow menu) or print a
focused ``Need:`` line so scripts/tests never block.
"""
from __future__ import annotations

import inspect
import os
import sys
from typing import Sequence

from ms_agent.command.types import CommandContext, CommandResult, CommandResultType
from ms_agent.command.usage import arg_error

SCOPE_TOKENS = frozenset({'global', 'project'})

# (scope, label) — labels match the Claude plugin install picker tone.
SCOPE_CHOICES: tuple[tuple[str, str], ...] = (
    ('global', 'This machine (global)'),
    ('project', 'This folder (project)'),
)


def parse_optional_scope(tokens: Sequence[str]) -> tuple[str | None, list[str]]:
    """Pull a trailing global|project token when a name/path precedes it.

    A lone ``project`` (or ``global``) is the id/path, not a scope — otherwise
    ``/skills disable project`` could never target that skill.
    """
    rest = list(tokens)
    if len(rest) >= 2 and rest[-1] in SCOPE_TOKENS:
        return rest[-1], rest[:-1]
    return None, rest


def work_dir_of(ctx: CommandContext) -> str | None:
    """Resolve ``--work-dir`` from whatever the dispatcher passed as runtime.

    Live TUI/CLI slash commands receive ``ms_agent.agent.runtime.Runtime``
    (``runtime.llm.config.output_dir``). Tests often pass a fake agent with
    ``runtime.config.output_dir``. Accept either, plus ``extra['work_dir']``.
    """
    extra = (ctx.extra or {}).get('work_dir')
    if extra:
        return str(extra)
    runtime = ctx.runtime
    if runtime is None:
        return None
    for holder in (runtime, getattr(runtime, 'llm', None)):
        if holder is None:
            continue
        config = getattr(holder, 'config', None)
        work = getattr(config, 'output_dir', None) if config is not None else None
        if work:
            return str(work)
    return None


def can_pick_interactively(ctx: CommandContext) -> bool:
    """True only for a live TUI prompt on a TTY.

    Router-dispatched tests (and pipes) must not open a blocking menu.
    ``InteractiveSession`` sets ``extra['interactive']`` when it has a TUI
    input source. Pytest is never interactive even if stdin is a TTY.
    """
    extra = ctx.extra or {}
    if extra.get('choose_scope'):
        return False
    if os.environ.get('PYTEST_CURRENT_TEST'):
        return False
    if not extra.get('interactive'):
        return False
    try:
        return bool(sys.stdin.isatty())
    except Exception:  # noqa: BLE001
        return False


async def pick_scope(
    ctx: CommandContext,
    *,
    syntax: str,
    header: str,
    choices: Sequence[tuple[str, str]] | None = None,
    note: str = 'Pass global or project — there is no default.',
) -> str | CommandResult:
    """Return a scope, or a CommandResult (Need: / Cancelled).

    One remaining choice is taken without asking. Tests may inject
    ``extra['choose_scope']`` (sync or async callable) returning an index,
    a scope id, or a label.
    """
    rows = list(choices) if choices is not None else list(SCOPE_CHOICES)
    if len(rows) == 1:
        return rows[0][0]
    if not rows:
        return arg_error(syntax, reason='No global or project copy found', ctx=ctx)

    labels = [label for _, label in rows]
    picked = await _invoke_test_picker(ctx, labels, header)
    if picked is None and can_pick_interactively(ctx):
        from ms_agent.tui.select import select_async
        picked = await select_async(labels, header=header)
        if picked is None:
            return CommandResult(
                type=CommandResultType.MESSAGE, content='Cancelled.')

    scope = _coerce_pick(picked, rows)
    if scope is not None:
        return scope
    return arg_error(syntax, note=note, ctx=ctx)


async def _invoke_test_picker(
    ctx: CommandContext,
    labels: Sequence[str],
    header: str,
):
    picker = (ctx.extra or {}).get('choose_scope')
    if not callable(picker):
        return None
    try:
        result = picker(labels, header)
        if inspect.isawaitable(result):
            result = await result
        return result
    except Exception:  # noqa: BLE001 — a test hook must not crash the TUI
        return None


def _coerce_pick(picked, rows: Sequence[tuple[str, str]]) -> str | None:
    if picked is None:
        return None
    if isinstance(picked, int) and 0 <= picked < len(rows):
        return rows[picked][0]
    if isinstance(picked, str):
        low = picked.strip().lower()
        for scope, label in rows:
            if low in (scope, label.lower()):
                return scope
    return None
