# Copyright (c) ModelScope Contributors. All rights reserved.
"""Fixed bottom input area for the busy (type-ahead) state.

While the agent streams, the user can still type. ``prompt_toolkit``'s
``patch_stdout`` pins a prompt at the bottom but redraws it on *every* output
write — the typed text is erased and rewritten many times a second, which reads
as a flickering input box. This module instead reserves the terminal's bottom
rows with a DECSTBM scroll region: streamed output scrolls in the region above
and physically cannot touch the reserved rows, so the input area is rewritten
only when the user actually presses a key. That is the Claude Code "box pinned
below the transcript, output scrolls above, never disturbed" behaviour.

The reserved block mirrors the idle ``prompt_toolkit`` prompt so the two states
look and feel the same (top → bottom)::

    row 1 .. region_bottom   scroll region — agent output scrolls here
    ─────────────────────    full-width dim rule — the divider ABOVE the box
    ❯ <buffer>▌              the editing area — wraps to as many rows as the
                             buffer needs (▌ = simulated block cursor)
    [completion menu]        slash-command picker, drawn in the reserved menu
    <blank reserve rows>     rows below the editing area (``MENU_RESERVE``) so
                             the menu opens with no layout jump — the same space
                             prompt_toolkit reserves under the idle prompt
      model · tokens · …     dim status toolbar on the bottom row

So the divider sits ABOVE the box and the status toolbar BELOW it, exactly like
idle (idle = ``Rule`` on top, ``bottom_toolbar`` underneath). The editing area
GROWS and SHRINKS with the wrapped buffer, capped at ``_INPUT_CAP`` rows; past
that it scrolls internally around the cursor.
Growing scrolls the transcript up to make room rather than overwriting it. The
hardware cursor is hidden and parked inside the region so output scrolls there;
the visible caret is a reverse-video block drawn at the cursor. Keys are read in
termios raw mode via the event loop (``add_reader``) so this composes with the
async turn on the same loop — output writes and key redraws are serialized and
never interleave mid-sequence.

Keys: printable inserts at the cursor; Enter submits (splitting a pasted
multi-line buffer like idle does); Backspace / Ctrl-W / Ctrl-U / Ctrl-K edit;
Ctrl-A / Ctrl-E move to the logical-line start / end; Left / Right move by char;
Up / Down walk history (or the completion menu when it is open); Tab accepts a
completion; Esc closes the menu; Ctrl-C interrupts the turn; Ctrl-D ends capture.
A bracketed paste inserts its newlines into the buffer instead of submitting each
one, so a pasted block can be edited before Enter — exactly like idle.
"""
from __future__ import annotations

import asyncio
import codecs
import os
import sys
import unicodedata
from typing import Callable, List, Optional, Tuple

_CSI_FINAL = range(0x40, 0x7f)  # CSI ... <final byte>
_MENU_CAP = 8  # max completion rows shown at once
# Rows held open below the editing area for the completion menu, so it appears
# without resizing the block. The idle prompt reserves the same space via
# prompt_toolkit's ``reserve_space_for_menu`` (set from this constant in
# input.py), which is why an empty idle box and an empty busy box are the same
# height.
MENU_RESERVE = 8
_INPUT_CAP = 12  # max editing rows before the area scrolls internally
_MIN_REGION = 3  # transcript rows always kept above the reserved block
_RULE_COLOR = '38;5;239'  # rich 'grey30' — the idle divider's exact color
_TOOLBAR_COLOR = '38;5;244'  # idle bottom-toolbar '#808080' (gray)


def _cw(ch: str) -> int:
    """Display columns of one character (East-Asian wide/full count as 2)."""
    return 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1


def _dwidth(s: str) -> int:
    """Display columns of ``s``."""
    return sum(_cw(c) for c in s)


def _wrap(text: str, width: int) -> List[str]:
    """Wrap ``text`` into visual lines of at most ``width`` display columns.

    Hard newlines always break a line; a character that would exceed ``width``
    starts the next line. Returns at least one (possibly empty) line.
    """
    if width <= 0:
        width = 1
    out: List[str] = []
    for hard in text.split('\n'):
        if hard == '':
            out.append('')
            continue
        cur = ''
        used = 0
        for ch in hard:
            w = _cw(ch)
            if used + w > width:
                out.append(cur)
                cur = ch
                used = w
            else:
                cur += ch
                used += w
        out.append(cur)
    return out or ['']


def _tail_fit(s: str, width: int) -> str:
    """Trailing slice of ``s`` that fits in ``width`` display columns."""
    if width <= 0:
        return ''
    if _dwidth(s) <= width:
        return s
    out: List[str] = []
    used = 0
    for ch in reversed(s):
        if used + _cw(ch) > width:
            break
        out.append(ch)
        used += _cw(ch)
    return ''.join(reversed(out))


def _clip(s: str, width: int) -> str:
    """Leading slice of ``s`` that fits in ``width`` display columns."""
    if _dwidth(s) <= width:
        return s
    out: List[str] = []
    used = 0
    for ch in s:
        if used + _cw(ch) > width:
            break
        out.append(ch)
        used += _cw(ch)
    return ''.join(out)


class BusyLineInput:
    """A self-drawn, scroll-region-pinned multi-line input for the busy state.

    ``on_submit`` receives each submitted line; ``on_interrupt`` / ``on_eof`` are
    called for Ctrl-C / Ctrl-D. ``placeholder`` and ``status`` are zero-arg
    callables re-evaluated on each redraw. ``completions`` maps the current
    buffer text to ``[(name, description), ...]`` for the slash menu (``None``
    disables it). ``history`` is a shared, mutated list of prior submissions that
    Up/Down walk. ``draw=False`` disables all terminal I/O so the key parser
    (``_feed``) and the buffer model are unit-testable without a tty.
    """

    def __init__(self,
                 *,
                 on_submit: Callable[[str], None],
                 on_interrupt: Callable[[], None],
                 on_eof: Callable[[], None],
                 placeholder: Callable[[], str],
                 status: Callable[[], str],
                 prompt_symbol: str = '❯',
                 completions: Optional[Callable[[str], list]] = None,
                 history: Optional[list] = None,
                 console: object = None,
                 fd: Optional[int] = None,
                 out=None,
                 draw: bool = True) -> None:
        self._on_submit = on_submit
        self._on_interrupt = on_interrupt
        self._on_eof = on_eof
        self._placeholder = placeholder
        self._status = status
        self._prompt_symbol = prompt_symbol
        self._completions = completions
        self._history = history if history is not None else []
        self._console = console
        # Resolved lazily in start(): the key parser (_feed) and the draw helpers
        # are unit-tested without a tty, where sys.stdin has no fileno().
        self._fd = fd
        self._out = out if out is not None else sys.stdout
        self._draw = draw
        # ── buffer + cursor (a flat index into _buf, so Left/Right cross the
        #    hard newlines a paste inserts without any special-casing) ──
        self._buf = ''
        self._cur = 0
        self._in_paste = False
        # ── history navigation ──
        self._hist_idx = -1  # -1 = not navigating
        self._hist_stash = ''
        # ── completion menu ──
        self._comp: List[Tuple[str, str]] = []
        self._comp_sel = 0
        # ── terminal / region state ──
        self._dec = codecs.getincrementaldecoder('utf-8')(errors='ignore')
        self._saved_attrs = None
        self._saved_size = None
        self._rows = 0
        self._cols = 0
        self._last_status: Optional[str] = None
        self._reserved = 0  # rows currently reserved at the bottom
        self._stop_event = asyncio.Event()
        self._started = False
        self._reader = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ── geometry helpers ───────────────────────────────────────────────────

    @property
    def _prefix(self) -> str:
        return f'{self._prompt_symbol} '

    @property
    def _pw(self) -> int:
        return _dwidth(self._prefix)

    def _wrap_width(self) -> int:
        # One cell is held back so the block cursor at a line end never spills
        # past the right margin.
        return max(1, self._cols - self._pw - 1)

    def _menu_reserve(self) -> int:
        """Rows held open below the editing area for the completion menu.

        Normally ``MENU_RESERVE`` (matching idle's ``reserve_space_for_menu``),
        but shrunk on very short terminals so the divider + editing + toolbar
        always fit above the ``_MIN_REGION`` transcript rows. Derived from the
        worst case (a single editing row) so it never depends on the buffer.
        """
        return max(0, min(MENU_RESERVE, self._rows - _MIN_REGION - 3))

    def _max_input_rows(self) -> int:
        # Leave room for the divider, the menu reserve, the toolbar, and the
        # _MIN_REGION transcript rows kept above the block.
        return max(
            1,
            min(_INPUT_CAP,
                self._rows - _MIN_REGION - self._menu_reserve() - 2))

    def _wrapped(self) -> List[str]:
        return _wrap(self._buf, self._wrap_width())

    def _cursor_rc(self) -> Tuple[int, int]:
        """Visual (row, display-col) of the cursor within ``_wrapped()``."""
        lines = _wrap(self._buf[:self._cur], self._wrap_width())
        return len(lines) - 1, _dwidth(lines[-1])

    # ── low-level write ────────────────────────────────────────────────────

    def _query_size(self):
        try:
            cols, rows = os.get_terminal_size(self._fd)
        except OSError:
            try:
                cols, rows = os.get_terminal_size()
            except OSError:
                cols, rows = 80, 24
        return max(3, rows), max(20, cols)

    def _w(self, s: str) -> None:
        if not self._draw:
            return
        try:
            self._out.write(s)
        except Exception:  # noqa: BLE001 — a broken pipe must not kill the turn
            pass

    def _flush(self) -> None:
        if not self._draw:
            return
        try:
            self._out.flush()
        except Exception:  # noqa: BLE001
            pass

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._started:
            return
        if self._fd is None:
            self._fd = sys.stdin.fileno()
        self._loop = asyncio.get_running_loop()
        self._rows, self._cols = self._query_size()
        if self._draw:
            import termios
            import tty
            try:
                self._saved_attrs = termios.tcgetattr(self._fd)
                tty.setraw(self._fd)
                # tty.setraw also clears OPOST, which stops the line discipline
                # translating an output '\n' into CR+LF. The renderer writes plain
                # newlines, so with OPOST off every streamed line would begin at
                # the previous line's end column and staircase diagonally down the
                # screen. Re-enable output post-processing; input stays raw (no
                # echo, no canonical line editing, no signal chars).
                attrs = termios.tcgetattr(self._fd)
                attrs[1] |= termios.OPOST  # oflag
                termios.tcsetattr(self._fd, termios.TCSANOW, attrs)
            except Exception:  # noqa: BLE001 — not a real tty; stay inert
                self._saved_attrs = None
            # Pin rich's wrap width to the region so streamed output never wraps
            # under the reserved rows. Saved/restored so idle output is full size.
            self._saved_size = (getattr(self._console, '_width', None),
                                getattr(self._console, '_height', None))
            try:
                self._console.size = (self._cols, self._rows - 2)
            except Exception:  # noqa: BLE001
                pass
            self._reserve()
        try:
            self._loop.add_reader(self._fd, self._on_readable)
            self._reader = True
        except Exception:  # noqa: BLE001 — fd not selectable; capture is inert
            self._reader = False
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        if self._reader and self._loop is not None:
            try:
                self._loop.remove_reader(self._fd)
            except Exception:  # noqa: BLE001
                pass
            self._reader = False
        if self._draw:
            self._release()
            if self._saved_attrs is not None:
                import termios
                try:
                    termios.tcsetattr(self._fd, termios.TCSADRAIN,
                                      self._saved_attrs)
                except Exception:  # noqa: BLE001
                    pass
                self._saved_attrs = None
            if self._saved_size is not None and self._console is not None:
                try:
                    self._console._width, self._console._height = \
                        self._saved_size
                except Exception:  # noqa: BLE001
                    pass
                self._saved_size = None

    async def wait_stopped(self) -> None:
        """Block until Ctrl-C / Ctrl-D asks the capture loop to end."""
        await self._stop_event.wait()

    # ── reserved region ────────────────────────────────────────────────────

    def _block_height(self) -> int:
        """Rows the reserved block needs (divider + editing + menu + toolbar).

        The menu reserve is fixed for a given terminal height (like idle's), so
        the block height changes only as the editing area grows or shrinks with
        the wrapped buffer.
        """
        return 2 + self._menu_reserve() + self._input_height()

    def _input_height(self) -> int:
        return min(len(self._wrapped()), self._max_input_rows())

    def _menu_height(self) -> int:
        if not self._comp:
            return 0
        return min(len(self._comp), _MENU_CAP, self._menu_reserve())

    def _reserve(self) -> None:
        rows = self._rows
        total = max(2, min(self._block_height(), rows - _MIN_REGION))
        self._w('\x1b[?25l')  # hide the hardware cursor (we draw a fake one)
        # Ask the terminal to wrap pastes in ESC[200~ … ESC[201~ so a pasted
        # block's newlines land in the buffer for editing instead of submitting
        # each line. Matches what prompt_toolkit enables for the idle prompt.
        self._w('\x1b[?2004h')
        self._w('\x1b[r')  # full-screen region while we make room
        self._w(f'\x1b[{rows};1H')  # bottom row
        # Scroll the transcript up so reserving `total` bottom rows does not
        # overwrite the newest output. The cursor parks just above the block, so
        # each newline scrolls exactly one transcript row off the top.
        self._w(f'\x1b[{rows - total};1H')
        self._w('\n' * total)
        self._w(f'\x1b[1;{rows - total}r')  # output scrolls above the block
        self._reserved = total
        self._draw_block()
        self._w(f'\x1b[{rows - total};1H')  # park the (hidden) cursor in region
        self._flush()

    def _relayout(self) -> None:
        """Resize the region if the block height changed, then redraw it."""
        rows = self._rows
        want = max(2, min(self._block_height(), rows - _MIN_REGION))
        if want != self._reserved:
            self._resize_region(self._reserved, want)
            self._reserved = want
        self._draw_block()
        self._w(f'\x1b[{rows - self._reserved};1H')  # park in the region
        self._flush()

    def _resize_region(self, old: int, new: int) -> None:
        """Move the region/block boundary from ``old`` to ``new`` reserved rows.

        Growing scrolls the transcript up to free blank rows (never overwriting
        output); shrinking reclaims the freed rows for the transcript and erases
        the stale block content there.
        """
        rows = self._rows
        self._w('\x1b[r')  # full-screen region while resizing
        if new > old:
            # Free (new-old) blank rows just above the old block by scrolling the
            # transcript up; the cursor starts at the old region's last row.
            self._w(f'\x1b[{rows - old};1H')
            self._w('\n' * (new - old))
            for r in range(rows - new + 1, rows + 1):
                self._w(f'\x1b[{r};1H\x1b[2K')
        else:
            # Rows rows-new+1 .. rows-old return to the transcript: erase them.
            for r in range(rows - new + 1, rows - old + 1):
                self._w(f'\x1b[{r};1H\x1b[2K')
        self._w(f'\x1b[1;{rows - new}r')

    def _release(self) -> None:
        rows = self._rows
        total = self._reserved or 2
        self._w('\x1b[?25h')  # show the cursor again
        self._w('\x1b[?2004l')  # stop wrapping pastes (idle prompt re-enables)
        self._w('\x1b[r')  # reset the region to the full screen
        for r in range(rows - total + 1, rows + 1):
            self._w(f'\x1b[{r};1H\x1b[2K')  # erase every reserved row
        self._w(f'\x1b[{rows - total + 1};1H')  # idle prompt resumes here
        self._flush()

    # ── drawing the reserved block ─────────────────────────────────────────

    def _draw_block(self) -> None:
        if not self._draw:
            return
        self._w('\x1b7')  # save the parked region cursor
        self._draw_divider()
        self._draw_input()
        self._draw_menu()
        self._draw_toolbar()
        self._w('\x1b8')  # restore it, so output keeps scrolling in the region
        self._flush()

    def _draw_divider(self) -> None:
        """Full-width dim rule ABOVE the box — the idle prompt's top divider."""
        row = self._divider_row()
        rule = _clip('─' * self._cols, self._cols)
        self._w(f'\x1b[{row};1H\x1b[2K')
        self._w(f'\x1b[{_RULE_COLOR}m{rule}\x1b[0m')

    def _draw_toolbar(self) -> None:
        """Dim status text on the bottom row — like idle's ``bottom_toolbar``.

        No rule characters: idle renders the divider on top and the status as a
        plain toolbar line below, so busy does the same instead of fusing the
        status into a rule.
        """
        try:
            status = self._status() or ''
        except Exception:  # noqa: BLE001
            status = ''
        self._last_status = status
        line = _clip(status, self._cols)
        self._w(f'\x1b[{self._toolbar_row()};1H\x1b[2K')
        self._w(f'\x1b[{_TOOLBAR_COLOR}m{line}\x1b[0m')

    def _toolbar_row(self) -> int:
        """Bottom screen row — the dim status toolbar (like idle's)."""
        return self._rows

    def _menu_top(self) -> int:
        """First row of the reserved menu area, directly above the toolbar."""
        return self._rows - self._menu_reserve()

    def _input_top(self) -> int:
        """First row of the editing area, directly above the menu reserve."""
        return self._rows - self._menu_reserve() - self._input_height()

    def _divider_row(self) -> int:
        """Row of the top divider rule, directly above the editing area."""
        return self._input_top() - 1

    def _draw_menu(self) -> None:
        """Draw completions in the reserved menu area, below the editing rows.

        The whole reserve is cleared first, so the rows are blank when the menu
        is closed and stale items vanish when it shrinks — matching idle, where
        the reserved space under the prompt stays blank until the completion
        menu opens in it.
        """
        top = self._menu_top()
        mh = self._menu_height()
        start = 0
        if len(self._comp) > mh:
            half = mh // 2
            start = max(0, min(self._comp_sel - half, len(self._comp) - mh))
        width = self._cols
        for j in range(self._menu_reserve()):
            row = top + j
            self._w(f'\x1b[{row};1H\x1b[2K')
            if j >= mh:
                continue  # reserved-but-blank row
            idx = start + j
            if idx >= len(self._comp):
                continue
            name, desc = self._comp[idx]
            sel = idx == self._comp_sel
            mark = '❯ ' if sel else '  '
            label = f'{mark}{name}'
            room = width - _dwidth(label) - 2
            txt = ''
            if desc and room > 4:
                txt = '  ' + _clip(desc, room)
            line = _clip(label + txt, width)
            if sel:
                self._w(f'\x1b[1;36m{line}\x1b[0m')
            else:
                self._w(f'\x1b[90m{line}\x1b[0m')

    def _draw_input(self) -> None:
        lines = self._wrapped()
        h = self._input_height()
        crow, ccol = self._cursor_rc()
        # Scroll the wrapped lines so the cursor row is visible within h rows.
        start = 0
        if len(lines) > h:
            start = max(0, min(crow - h // 2, len(lines) - h))
        top = self._input_top()
        width = self._wrap_width()
        for r in range(h):
            li = start + r
            row = top + r
            self._w(f'\x1b[{row};1H\x1b[2K')
            prefix = self._prefix if r == 0 else ' ' * self._pw
            self._w(f'\x1b[1;36m{prefix}\x1b[0m')
            seg = lines[li] if li < len(lines) else ''
            is_cur_row = (li == crow)
            if not seg and is_cur_row and ccol == 0 and not self._buf:
                # Empty buffer: block cursor at the left edge, then the hint.
                self._w('\x1b[7m \x1b[0m')
                try:
                    ph = self._placeholder() or ''
                except Exception:  # noqa: BLE001
                    ph = ''
                room = self._cols - self._pw - 1
                if ph and room > 0:
                    self._w(f'\x1b[90m{_tail_fit(ph, room)}\x1b[0m')
                continue
            if not is_cur_row:
                self._w(_clip(seg, width))
                continue
            # Cursor row: render up to the cursor, the reverse-video cell, then
            # the remainder of the line.
            before, at, after = self._split_at_col(seg, ccol)
            self._w(_clip(before, width))
            if at == '':
                self._w('\x1b[7m \x1b[0m')
                self._w(_clip(after, max(0, width - _dwidth(before) - 1)))
            else:
                self._w(f'\x1b[7m{at}\x1b[0m')
                self._w(_clip(after, max(0, width - _dwidth(before) - _cw(at))))

    @staticmethod
    def _split_at_col(seg: str, col: int) -> Tuple[str, str, str]:
        """Split ``seg`` into (before, char_at, after) at display column ``col``.

        ``char_at`` is '' when the cursor sits at the end of the segment.
        """
        used = 0
        for i, ch in enumerate(seg):
            if used == col:
                return seg[:i], ch, seg[i + 1:]
            if used > col:  # col landed inside a wide char; snap to its start
                return seg[:i - 1], seg[i - 1], seg[i:]
            used += _cw(ch)
        return seg, '', ''

    def _redraw(self) -> None:
        if not self._draw:
            return
        self._relayout()

    # ── key reading ────────────────────────────────────────────────────────

    def _on_readable(self) -> None:
        try:
            data = os.read(self._fd, 1024)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b''
        if not data:
            self._safe(self._on_eof)
            self._stop_event.set()
            return
        self._feed(data)

    @staticmethod
    def _safe(fn) -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001
            pass

    def _feed(self, data: bytes) -> None:
        """Parse a raw read into buffer edits / submits / control actions.

        A bracketed paste (``ESC[200~`` … ``ESC[201~``) inserts its newlines into
        the buffer so the block can be edited before Enter; a bare Enter outside a
        paste submits. Other escape sequences are decoded for the arrows and
        ignored otherwise.
        """
        text = self._dec.decode(data)
        submits: List[str] = []
        stop = False
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            if ch == '\x1b':
                kind, payload, i = self._parse_escape(text, i, n)
                if kind == 'paste_start':
                    self._in_paste = True
                elif kind == 'paste_end':
                    self._in_paste = False
                elif kind == 'csi':
                    self._handle_csi(payload)
                elif kind == 'esc':
                    self._comp = []  # Esc closes the completion menu
                continue
            if ch in ('\r', '\n'):
                if self._in_paste:
                    self._insert('\n')  # a pasted newline is content, not submit
                else:
                    submits.extend(self._take_submits())
                i += 1
                continue
            if ch in ('\x7f', '\x08'):  # backspace
                self._backspace()
                i += 1
                continue
            if ch == '\x03':  # Ctrl-C → interrupt the turn
                stop = True
                self._safe(self._on_interrupt)
                break
            if ch == '\x04':  # Ctrl-D → end capture
                stop = True
                self._safe(self._on_eof)
                break
            if ch == '\t':  # Tab → accept the highlighted completion
                self._accept_completion()
                i += 1
                continue
            if ch == '\x01':  # Ctrl-A → start of the logical line
                self._home()
                i += 1
                continue
            if ch == '\x05':  # Ctrl-E → end of the logical line
                self._end()
                i += 1
                continue
            if ch == '\x17':  # Ctrl-W → delete the word before the cursor
                self._delete_word()
                i += 1
                continue
            if ch == '\x15':  # Ctrl-U → delete to the start of the line
                self._delete_to_start()
                i += 1
                continue
            if ch == '\x0b':  # Ctrl-K → delete to the end of the line
                self._delete_to_end()
                i += 1
                continue
            if ord(ch) >= 0x20:
                self._insert(ch)
            i += 1
        self._update_completions()
        self._redraw()
        for line in submits:
            self._safe(lambda l=line: self._on_submit(l))
        if stop:
            self._stop_event.set()

    @staticmethod
    def _parse_escape(text: str, i: int, n: int):
        """Decode one escape sequence starting at ``i``.

        Returns ``(kind, payload, next_i)`` where kind is one of ``paste_start``,
        ``paste_end``, ``csi`` (payload = the single final byte), ``ss3``
        (payload = the final byte) or ``esc`` (a bare Escape).
        """
        j = i + 1
        if j < n and text[j] == '[':
            j += 1
            body_start = j
            while j < n and ord(text[j]) not in _CSI_FINAL:
                j += 1
            if j >= n:  # truncated mid-sequence; drop what we have
                return 'esc', '', n
            final = text[j]
            body = text[body_start:j]
            j += 1
            if body == '200' and final == '~':
                return 'paste_start', '', j
            if body == '201' and final == '~':
                return 'paste_end', '', j
            return 'csi', final, j
        if j < n and text[j] == 'O':
            j += 1
            if j >= n:
                return 'esc', '', n
            final = text[j]
            return 'ss3', final, j + 1
        return 'esc', '', min(n, i + 1)

    def _handle_csi(self, final: str) -> None:
        """Apply an arrow-key final byte (Up/Down/Left/Right)."""
        menu = bool(self._comp)
        if final == 'A':  # Up
            if menu:
                self._comp_sel = (self._comp_sel - 1) % len(self._comp)
            else:
                self._history_prev()
        elif final == 'B':  # Down
            if menu:
                self._comp_sel = (self._comp_sel + 1) % len(self._comp)
            else:
                self._history_next()
        elif final == 'C':  # Right
            if menu:
                self._accept_completion()
            else:
                self._move_right()
        elif final == 'D':  # Left
            self._move_left()

    # ── buffer editing ─────────────────────────────────────────────────────

    def _reset_history_nav(self) -> None:
        self._hist_idx = -1
        self._hist_stash = ''

    def _insert(self, s: str) -> None:
        self._buf = self._buf[:self._cur] + s + self._buf[self._cur:]
        self._cur += len(s)
        self._reset_history_nav()

    def _backspace(self) -> None:
        if self._cur > 0:
            self._buf = self._buf[:self._cur - 1] + self._buf[self._cur:]
            self._cur -= 1
            self._reset_history_nav()

    def _move_left(self) -> None:
        self._cur = max(0, self._cur - 1)

    def _move_right(self) -> None:
        self._cur = min(len(self._buf), self._cur + 1)

    def _line_bounds(self) -> Tuple[int, int]:
        """(start, end) indices of the logical line containing the cursor."""
        start = self._buf.rfind('\n', 0, self._cur) + 1
        end = self._buf.find('\n', self._cur)
        return start, (len(self._buf) if end == -1 else end)

    def _home(self) -> None:
        self._cur = self._line_bounds()[0]

    def _end(self) -> None:
        self._cur = self._line_bounds()[1]

    def _delete_word(self) -> None:
        if self._cur == 0:
            return
        i = self._cur
        while i > 0 and self._buf[i - 1].isspace():
            i -= 1
        while i > 0 and not self._buf[i - 1].isspace():
            i -= 1
        self._buf = self._buf[:i] + self._buf[self._cur:]
        self._cur = i
        self._reset_history_nav()

    def _delete_to_start(self) -> None:
        start = self._line_bounds()[0]
        self._buf = self._buf[:start] + self._buf[self._cur:]
        self._cur = start
        self._reset_history_nav()

    def _delete_to_end(self) -> None:
        end = self._line_bounds()[1]
        self._buf = self._buf[:self._cur] + self._buf[end:]
        self._reset_history_nav()

    def _take_submits(self) -> List[str]:
        """Submit the buffer: split hard newlines like idle, record history."""
        buf = self._buf
        self._buf = ''
        self._cur = 0
        self._in_paste = False
        self._comp = []
        self._comp_sel = 0
        self._reset_history_nav()
        lines = buf.split('\n')
        if buf.strip():
            self._history.append(buf)
        return [ln for ln in lines]

    # ── history ────────────────────────────────────────────────────────────

    def _history_prev(self) -> None:
        if not self._history:
            return
        if self._hist_idx == -1:
            self._hist_stash = self._buf
            self._hist_idx = len(self._history) - 1
        elif self._hist_idx > 0:
            self._hist_idx -= 1
        else:
            return
        self._buf = self._history[self._hist_idx]
        self._cur = len(self._buf)

    def _history_next(self) -> None:
        if self._hist_idx == -1:
            return
        if self._hist_idx < len(self._history) - 1:
            self._hist_idx += 1
            self._buf = self._history[self._hist_idx]
            self._cur = len(self._buf)
        else:
            self._buf = self._hist_stash
            self._cur = len(self._buf)
            self._reset_history_nav()

    # ── completion ─────────────────────────────────────────────────────────

    def _update_completions(self) -> None:
        if self._completions is None or not self._buf.startswith('/'):
            self._comp = []
            self._comp_sel = 0
            return
        try:
            raw = self._completions(self._buf) or []
        except Exception:  # noqa: BLE001 — a bad completer must not break input
            raw = []
        comp = []
        for item in raw:
            if isinstance(item, (tuple, list)) and len(item) >= 1:
                name = str(item[0])
                desc = str(item[1]) if len(item) > 1 else ''
                comp.append((name if name.startswith('/') else '/' + name, desc))
        # Do not re-offer a command that is already fully typed (with a space).
        if ' ' in self._buf:
            comp = []
        if comp != self._comp:
            self._comp_sel = 0
        self._comp = comp

    def _accept_completion(self) -> None:
        if not self._comp:
            return
        name = self._comp[self._comp_sel][0]
        self._buf = name + ' '
        self._cur = len(self._buf)
        self._reset_history_nav()
        self._update_completions()
