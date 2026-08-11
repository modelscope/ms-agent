# Copyright (c) ModelScope Contributors. All rights reserved.
"""Human-friendly formatting helpers for agent-hub CLI output.

Self-contained copy of the small formatting utilities the agent workspace
tooling needs (``style``/``supports_color``/``format_size``/``tabulate``), so
this package does not reach into modelscope-hub's private ``utils`` module.
"""

from __future__ import annotations

import os
import sys
from typing import IO, Iterable, Sequence

# ---------------------------------------------------------------------------
# Terminal color
# ---------------------------------------------------------------------------
_ANSI: dict[str, str] = {
    'reset': '\033[0m',
    'bold': '\033[1m',
    'dim': '\033[2m',
    'red': '\033[31m',
    'green': '\033[32m',
    'yellow': '\033[33m',
    'blue': '\033[34m',
    'magenta': '\033[35m',
    'cyan': '\033[36m',
}


def supports_color(stream: IO | None = None) -> bool:
    """Return True when ANSI color should be emitted to *stream*.

    ``NO_COLOR`` (any value) disables color; ``FORCE_COLOR`` (any value) forces
    it on; otherwise color is used only for interactive TTYs.
    """
    if os.environ.get('NO_COLOR'):
        return False
    if os.environ.get('FORCE_COLOR'):
        return True
    stream = stream if stream is not None else sys.stdout
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def style(text: str, *names: str, stream: IO | None = None) -> str:
    """Wrap *text* in the ANSI codes named by *names* (e.g. ``"bold"``, ``"cyan"``).

    Returns *text* unchanged when no names are given or when *stream* does not
    support color, so call sites never need their own TTY guard.
    """
    if not names or not supports_color(stream):
        return text
    codes = ''.join(_ANSI.get(n, '') for n in names)
    if not codes:
        return text
    return f"{codes}{text}{_ANSI['reset']}"


# ---------------------------------------------------------------------------
# Size formatting
# ---------------------------------------------------------------------------
_UNIT_SYSTEMS: dict[str, tuple[int, tuple[str, ...]]] = {
    'iec': (1024, ('B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB')),
    'si': (1000, ('B', 'KB', 'MB', 'GB', 'TB', 'PB')),
}


def format_size(size_bytes: int | float, *, unit_system: str = 'iec') -> str:
    """Format a byte count as a human-readable string.

    ``unit_system`` selects between IEC (1024-based) and SI (1000-based) units.
    Returns ``"0 B"`` for zero, otherwise one decimal place is kept unless the
    value is integral (e.g. ``"2 MiB"``).
    """
    if unit_system not in _UNIT_SYSTEMS:
        raise ValueError(f'Unknown unit_system: {unit_system!r}')
    if size_bytes == 0:
        return '0 B'

    base, units = _UNIT_SYSTEMS[unit_system]
    value = float(size_bytes)
    unit = units[0]
    for unit in units:
        if abs(value) < base or unit is units[-1]:
            break
        value /= base

    rendered = f'{value:.0f}' if value == int(value) else f'{value:.1f}'
    return f'{rendered} {unit}'


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------
def _cell(value: object, max_width: int) -> str:
    """Stringify a cell, replacing ``None`` with ``-`` and truncating overlong text."""
    text = '-' if value is None else str(value)
    if len(text) > max_width:
        return text[:max_width - 1] + '…'
    return text


def tabulate(
    rows: Iterable[Sequence[object]],
    headers: Sequence[str],
    *,
    sep: str = '  ',
    max_width: int = 80,
) -> str:
    """Render ``rows`` as a left-aligned ASCII table.

    Columns auto-size to their widest cell; cells longer than ``max_width`` are
    truncated with an ellipsis. ``None`` values render as ``-``.

    Raises :class:`ValueError` if ``max_width`` is less than 1.
    """
    if max_width < 1:
        raise ValueError(f'max_width must be >= 1, got {max_width}')
    ncols = len(headers)
    str_rows: list[list[str]] = [[
        _cell(row[i] if i < len(row) else '', max_width) for i in range(ncols)
    ] for row in rows]

    widths = [len(h) for h in headers]
    for row in str_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def _join(cells: Sequence[str]) -> str:
        return sep.join(cells[i].ljust(widths[i]) for i in range(ncols))

    lines = [
        _join(list(headers)),
        sep.join('-' * w for w in widths),
    ]
    lines.extend(_join(row) for row in str_rows)
    return '\n'.join(lines)


__all__ = ['format_size', 'style', 'supports_color', 'tabulate']
