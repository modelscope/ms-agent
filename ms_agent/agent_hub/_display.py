# Copyright (c) ModelScope Contributors. All rights reserved.
"""Presentation helpers for ``ms agent`` upload/download/convert output.

Centralizes coloring, section headers, tabular file listings, and merge/drop
hints so the three commands share one consistent, elegant format. Everything
degrades to plain text when stdout is not a TTY (or ``NO_COLOR`` is set), so
piped output and tests stay clean.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from ._format import style, tabulate

# Semantic colors reused across sections so the same concept always reads the
# same way (written=green, merged=yellow, dropped/removed=red, skip/meta=dim).
COLOR_WRITTEN = 'green'
COLOR_MERGED = 'yellow'
COLOR_DROPPED = 'red'
COLOR_SKIP = 'dim'
COLOR_TITLE = 'cyan'

_ARROW = '\u2192'  # →


def header(action: str, src: str, dst: str | None = None) -> None:
    """Print a bold action heading, e.g. ``Convert  qwenpaw/all → hermes/all``."""
    title = style(action, 'bold', COLOR_TITLE)
    if dst is not None:
        arrow = style(_ARROW, 'dim')
        print(f"\n{title}  {style(src, 'bold')} {arrow} {style(dst, 'bold')}")
    else:
        print(f"\n{title}  {style(src, 'bold')}")


def meta(label: str, value: object) -> None:
    """Print an indented ``label  value`` line with a dim label."""
    print(f"  {style(label, 'dim')}  {value}")


def summary(items: Sequence[tuple[str, int, str]]) -> None:
    """Print a one-line ``N label · N label`` summary.

    *items* is a sequence of ``(label, count, color)``; entries are rendered in
    order and joined with a dim middle dot.
    """
    parts = [
        f"{style(str(count), 'bold', color)} {label}"
        for label, count, color in items
    ]
    if parts:
        print('  ' + style(' \u00b7 ', 'dim').join(parts))


def file_list(
    title: str,
    items: Iterable[str],
    *,
    color: str,
    note: str | None = None,
    root: object | None = None,
    marker: str | None = None,
) -> None:
    """Print a titled, indented list of relative paths.

    When *root* is given it is shown once in the header (``Title (N) → root``)
    instead of being repeated on every line. *marker* prefixes each item (e.g.
    ``[drop]``) in the section color; *note* adds a dim inline explanation.
    """
    items = sorted(items)
    if not items:
        return
    head = style(f'{title} ({len(items)})', 'bold', color)
    if root is not None:
        head += f" {style(_ARROW, 'dim')} {style(str(root), 'dim')}"
    if note:
        head += style(f'  \u2014 {note}', 'dim')
    print(f'\n{head}')
    prefix = (style(marker, color) + ' ') if marker else ''
    for it in items:
        print(f'  {prefix}{it}')


def map_table(
    title: str,
    pairs: Iterable[tuple[str, str]],
    *,
    color: str,
    headers: tuple[str, str] = ('SOURCE', 'DESTINATION'),
    note: str | None = None,
) -> None:
    """Print a titled two-column table of ``(left, right)`` path pairs."""
    pairs = sorted(pairs)
    if not pairs:
        return
    head = style(f'{title} ({len(pairs)})', 'bold', color)
    if note:
        head += style(f'  \u2014 {note}', 'dim')
    print(f'\n{head}')
    rows = [(left, _ARROW, right) for left, right in pairs]
    table = tabulate(rows, headers=(headers[0], '', headers[1]))
    for line in table.splitlines():
        print('  ' + line)


def table(
    title: str,
    rows: Sequence[Sequence[object]],
    headers: Sequence[str],
    *,
    color: str,
    note: str | None = None,
) -> None:
    """Print a titled, generic aligned table (no arrow column).

    Used where the second column is not a path (e.g. file sizes).
    """
    rows = list(rows)
    if not rows:
        return
    head = style(f'{title} ({len(rows)})', 'bold', color)
    if note:
        head += style(f'  \u2014 {note}', 'dim')
    print(f'\n{head}')
    for line in tabulate(rows, headers=headers).splitlines():
        print('  ' + line)


def done(message: str) -> None:
    """Print a final success line (checkmark shown when colored)."""
    check = style('\u2713 ', 'green')
    print(f'\n{check}{message}')
