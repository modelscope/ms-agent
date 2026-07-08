# Copyright (c) ModelScope Contributors. All rights reserved.
"""Compact tool-call presentation (Codex / hermes style).

Turns a ``server---tool`` name + args into a one-line action header
(``Write path/to/file``, ``Run git push``, ``Search "modelscope"``) and a
tool result into a one-line summary (``42 lines``, ``(no output)``,
``error: …``). Pattern-based, not a per-tool hardcode: a small verb map for
common tools + a salient-argument heuristic, with a readable generic fallback.
"""
from __future__ import annotations

import json
from typing import Any

TOOL_SPLITER = '---'

# action word (part after '---') → display verb
_VERBS = {
    'write_file': 'Write', 'edit_file': 'Edit', 'read_file': 'Read',
    'append_file': 'Append', 'delete_file': 'Delete', 'move_file': 'Move',
    'shell_executor': 'Run', 'execute': 'Run', 'run_command': 'Run',
    'exa_search': 'Search', 'web_search': 'Search', 'search': 'Search',
    'skill_view': 'View skill', 'skill_manage': 'Skill',
    'skills_list': 'List skills', 'glob': 'Find', 'grep': 'Search',
    'list_dir': 'List', 'read_dir': 'List',
}
# arg keys probed, in priority order, for the salient value to show
_ARG_KEYS = ('path', 'file_path', 'filename', 'query', 'q', 'command', 'cmd',
             'skill_id', 'url', 'pattern', 'directory', 'dir', 'name')


def _short(s: str, n: int = 72) -> str:
    s = ' '.join(str(s).split())  # collapse whitespace/newlines
    return s if len(s) <= n else s[:n] + '…'


def _coerce_args(args: Any) -> Any:
    if isinstance(args, str):
        try:
            return json.loads(args)
        except (json.JSONDecodeError, ValueError):
            return args
    return args


def _salient_arg(args: Any) -> str:
    args = _coerce_args(args)
    if isinstance(args, str):
        return _short(args)
    if isinstance(args, dict):
        for k in _ARG_KEYS:
            v = args.get(k)
            if v:
                return _short(str(v))
        for v in args.values():  # fall back to first scalar
            if isinstance(v, (str, int, float)) and str(v).strip():
                return _short(str(v))
    return ''


def tool_header(name: str, args: Any) -> str:
    """One-line action header, e.g. ``Write SKILL.md`` / ``Run git push``."""
    short = name.split(TOOL_SPLITER)[-1] if TOOL_SPLITER in name else name
    arg = _salient_arg(args)
    verb = _VERBS.get(short)
    if verb:
        return f'{verb} {arg}'.rstrip()
    label = short.replace('_', ' ')
    return f'{label} {arg}'.rstrip() if arg else label


def tool_summary(result: str, error: str | None = None) -> str:
    """One-line result summary, e.g. ``42 lines`` / ``(no output)``."""
    if error:
        return f'error: {_short(error)}'
    r = (result or '').strip()
    if not r:
        return '(no output)'
    lines = r.splitlines()
    first = lines[0].strip()
    if len(lines) == 1:
        return _short(first)
    # Lead with a line count when the first line is a trivial opener (JSON/
    # array/fence), which would otherwise render a meaningless "{  (+N lines)".
    if len(first) <= 2 or first in ('{', '[', '```', '---'):
        return f'{len(lines)} lines'
    return f'{_short(first, 56)}  (+{len(lines) - 1} lines)'
