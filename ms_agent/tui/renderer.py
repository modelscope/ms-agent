# Copyright (c) ModelScope Contributors. All rights reserved.
"""Rich renderer: turns the agent's structured :class:`AgentEvent` stream into
a scrolling terminal transcript.

This is a pure consumer of the ``ms_agent.ui`` event contract — it knows
nothing about the agent internals, only how to *draw* each semantic event. The
same event stream a WebUI backend forwards to a browser is what this renders to
a terminal, which is why the TUI validates that contract.

Dispatch is open/closed: ``emit`` looks up ``_on_<event_type>``; adding a new
event only needs a new handler method, never a change here.
"""
from __future__ import annotations

import json
import re
import time
from contextlib import contextmanager
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from typing import Optional

from ms_agent.tui.state import TuiState
from ms_agent.tui.theme import DEFAULT_THEME, Theme
from ms_agent.tui.tool_view import tool_header, tool_summary
from ms_agent.ui.events import AgentEvent

_UNAVAILABLE = 'UNAVAILABLE'

# Minimum interval between raw flushes while the busy input line is up (append
# mode). The input line lives on a reserved bottom row behind a DECSTBM scroll
# region (see busy_input.BusyLineInput), so output physically cannot redraw it —
# flicker is structurally impossible. Batching tokens to ~30fps is now purely a
# smoothness/syscall win: fewer, larger writes scroll the region in even steps
# instead of one tiny scroll per token.
_APPEND_FLUSH_INTERVAL = 1.0 / 30.0


def _bold_unavailable(text: str) -> Text:
    """Bold the word UNAVAILABLE. The rest of a command panel stays plain.

    Command text is not markup, so a ``[bold]`` tag would print literally.
    """
    body = Text()
    parts = re.split(f'({_UNAVAILABLE})', text or '')
    for part in parts:
        if part == _UNAVAILABLE:
            body.append(part, style='bold')
        else:
            body.append(part)
    return body

_KEY_LINE = re.compile(r'^\s*[\w.\-]+:(\s|$)')


def _looks_texty(s: str) -> bool:
    t = s.lstrip()
    return not (t.startswith('{') or t.startswith('['))


def _guess_syntax(text: str) -> Optional[str]:
    """Best-effort lexer for command output so /config etc. render nicely."""
    t = text.strip()
    if not t:
        return None
    if t[0] in '{[':
        try:
            json.loads(t)
            return 'json'
        except (json.JSONDecodeError, ValueError):
            pass
    if sum(1 for ln in text.splitlines() if _KEY_LINE.match(ln)) >= 3:
        return 'yaml'
    return None


class RichEventSink:
    """An :class:`~ms_agent.ui.events.AgentEventSink` that renders with rich."""

    def __init__(self,
                 console: Console,
                 state: TuiState,
                 theme: Theme = DEFAULT_THEME) -> None:
        self.console = console
        self.state = state
        self.theme = theme
        self._live = None
        self._content_buf = ''
        self._label_shown = False
        self._reasoning_active = False
        self._tool_started: dict = {}  # call_id -> monotonic_start
        # Kind of the last block rendered ('tool' | 'content' | None), used to
        # add a blank line between sections (tools ↔ assistant) for breathing
        # room without spacing tightly-grouped tool lines apart.
        self._last_kind: Optional[str] = None
        # Buffered draws while something else owns the screen (see hold_output).
        # None = draw straight through.
        self._held: Optional[list] = None
        # Type-ahead capture mode (see set_append_mode). While the busy input
        # line is pinned at the bottom behind a scroll region
        # (busy_input.BusyLineInput), the transient Live region's cursor-up
        # redraws would fight the reserved rows, so streamed assistant text is
        # appended as raw output instead — it scrolls in the region above the
        # input line, Claude Code style.
        self._append_mode = False
        # Throttled raw-write buffers for append mode (see _append_write). Tokens
        # accumulate and flush at most ~30fps so the region scrolls in even steps
        # and syscalls stay low (the reserved input line is never redrawn).
        self._append_buf = ''
        self._last_append_flush = 0.0
        self._reasoning_buf = ''
        self._last_reasoning_flush = 0.0

    # ── sink protocol ──────────────────────────────────────────────────────

    def emit(self, event: AgentEvent) -> None:
        handler = getattr(self, f'_on_{event.type}', None)
        if handler is not None:
            handler(event)

    # ── screen ownership ───────────────────────────────────────────────────

    @contextmanager
    def hold_output(self):
        """Buffer this sink's draws while a modal owns the terminal.

        A permission menu (``tui.select.select_async``) is a prompt_toolkit
        Application rendered inline on the SAME event loop this sink draws from,
        so any print landing mid-menu corrupts what the user is reading. Tool
        completions now arrive as each call finishes rather than after the whole
        round (``LLMAgent.parallel_tool_call``), which is exactly when that can
        happen: approving one call lets the next one's menu open while the first
        is still executing, and its result lands underneath.

        Events are still HANDLED immediately — only the drawing waits — so
        durations and internal state stay measured at the true moment.

        Nested holds share the outermost buffer; the flush happens once, when
        the screen is actually released.
        """
        if self._held is not None:
            yield  # already held by an outer scope — it owns the flush
            return
        self._held = []
        try:
            yield
        finally:
            held, self._held = self._held, None
            for args, kwargs in held:
                self.console.print(*args, **kwargs)

    def _print(self, *args, **kwargs) -> None:
        """Draw now, or queue it if a modal currently owns the screen."""
        if self._held is not None:
            self._held.append((args, kwargs))
            return
        self.console.print(*args, **kwargs)

    def finalize(self) -> None:
        """Stop any in-flight Live region (call on error / turn abort)."""
        self.release_terminal()

    def set_append_mode(self, on: bool) -> None:
        """Suspend the transient Live region while the busy input line is up.

        With ``on=True`` streamed assistant text is appended as raw output that
        scrolls in the region above the reserved input line (see
        busy_input.BusyLineInput) instead of being redrawn in a single-screen Live
        window. Any Live already running is stopped first so the two rendering
        strategies never overlap.
        """
        on = bool(on)
        if on == self._append_mode:
            return
        if on:
            self._stop_live()
        else:
            # Leaving append mode: land any batched text before the rendering
            # strategy switches back to the transient Live region.
            self._flush_append()
        self._append_mode = on

    def _flush_append(self) -> None:
        """Write any batched append-mode assistant text now."""
        if self._append_buf:
            self.console.file.write(self._append_buf)
            self.console.file.flush()
            self._append_buf = ''
        self._last_append_flush = time.monotonic()

    def _append_write(self, text: str) -> None:
        """Batch a streamed token, flushing at most ~30fps.

        The input line is on a reserved row output cannot touch, so this is not a
        flicker fix — it batches many tiny per-token writes into fewer, larger
        ones so the region scrolls in even steps and syscalls stay low. The buffer
        is always drained by ``release_terminal`` / ``set_append_mode(False)``, so
        no text is lost.
        """
        self._append_buf += text
        if time.monotonic() - self._last_append_flush >= _APPEND_FLUSH_INTERVAL:
            self._flush_append()

    def _flush_reasoning(self) -> None:
        """Write any batched append-mode reasoning text now (dim, as one run)."""
        if self._reasoning_buf:
            self.console.print(
                Text(self._reasoning_buf, style=self.theme.reasoning), end='')
            self._reasoning_buf = ''
        self._last_reasoning_flush = time.monotonic()

    def release_terminal(self) -> None:
        """Stop the streaming region and wait until it can no longer write.

        ``Live.stop`` only signals the refresh thread; it does not join it.
        Joining here means the next owner of the terminal (the input prompt)
        is the only writer. A reply that was still streaming is typeset once
        below the title line already printed above the region.
        """
        self._flush_append()
        buf = self._content_buf
        self._content_buf = ''
        self._label_shown = False
        terminal = bool(self.console.is_terminal)
        self._stop_live()
        # In append mode the reply already streamed to the transcript verbatim,
        # so re-typesetting it as Markdown would print the whole thing twice.
        if terminal and not self._append_mode and buf.strip():
            self.console.print(Markdown(buf))

    def _stop_live(self) -> None:
        live = self._live
        if live is None:
            return
        self._live = None
        # Grab the thread first: stop() drops the reference without joining.
        thread = getattr(live, '_refresh_thread', None)
        try:
            live.stop()
        except Exception:
            pass
        if thread is not None:
            try:
                thread.join()
            except RuntimeError:
                pass

    def _stream_window(self, text: str):
        """The last screen of ``text``.

        Live's ``crop`` keeps the top of a renderable, so the renderable
        itself has to be the tail. One screen (minus a row, so the refresh
        does not scroll) is all that gets redrawn each frame.
        """
        width = max(1, self.console.size.width)
        height = max(1, self.console.size.height - 1)
        lines = list(Text(text).wrap(self.console, width))
        tail = lines[-height:] if lines else []
        if not tail:
            return Text('')
        if len(tail) == 1:
            return tail[0]
        return Group(*tail)

    # ── user turn (steered echo) ───────────────────────────────────────────

    def _on_user_message(self, ev) -> None:
        """Draw a user turn the terminal did not echo inline.

        An idle prompt is echoed by prompt_toolkit (the typed line stays on
        screen), so this stays quiet for it. A steered interjection is folded
        into the running turn with no prompt echo — without drawing it here the
        timeline would show the assistant answering a message the user never sees
        recorded. Rendered as ``❯ <text>`` to match the live prompt's look.
        """
        if not getattr(ev, 'steered', False):
            return
        # A gap before the user turn, mirroring the assistant header's spacing.
        self._print()
        self._print(
            f'[{self.theme.user}]{self.theme.user_symbol}[/] {escape(ev.text)}')
        self._last_kind = None

    # ── assistant content (streamed) ───────────────────────────────────────

    def _on_content_delta(self, ev) -> None:
        if not self._label_shown:
            # Always a blank line before the assistant reply — a clear gap after
            # the user prompt (or the preceding tools/thinking).
            self.console.print()
            self.console.print(
                f'[{self.theme.assistant}]{self.theme.assistant_symbol} '
                f'Assistant[/]')
            self._label_shown = True
            self._last_kind = 'content'
        self._content_buf += ev.text
        if self.console.is_terminal and not self._append_mode:
            if self._live is None:
                from rich.live import Live
                # One screen, erased when the reply finishes. stdout stays
                # ours so this thread cannot still be writing when the prompt
                # switches the terminal into raw / bracketed-paste mode.
                self._live = Live(
                    console=self.console,
                    refresh_per_second=12,
                    transient=True,
                    vertical_overflow='crop',
                    redirect_stdout=False,
                    redirect_stderr=False)
                self._live.start()
            # Plain text while tokens are still arriving; ContentEnd typesets
            # the whole reply once, after this region has stopped.
            self._live.update(self._stream_window(self._content_buf))
        else:
            # Non-terminal (piped / CI) writes raw for clean, scriptable output.
            # Type-ahead capture mode does the same on a terminal, batched to
            # ~30fps (see _append_write); the raw text scrolls in the region above
            # the reserved input line, which it never redraws.
            self._append_write(ev.text)

    def _on_content_end(self, ev) -> None:
        terminal = bool(self.console.is_terminal)
        append_mode = self._append_mode
        self.release_terminal()
        if not terminal or append_mode:
            # Raw-streamed text carried no trailing newline; close the line so
            # the next block starts on a fresh row.
            self.console.file.write('\n')
            self.console.file.flush()
        self._last_kind = None  # next turn starts fresh (input divider spaces it)

    # ── reasoning (collapsed dim block) ─────────────────────────────────────

    def _on_reasoning_started(self, ev) -> None:
        # A gap + header, then the reasoning streams dim below it (always spaced
        # off whatever preceded — a tool result, the prompt, etc.).
        self.console.print()
        self.console.print(f'[{self.theme.reasoning}]✻ Thinking[/]')
        self._reasoning_active = True
        self._last_kind = 'content'

    def _on_reasoning_delta(self, ev) -> None:
        if self._reasoning_active and ev.text:
            if self._append_mode:
                # Batch dim reasoning tokens too, so thinking scrolls the region
                # in even steps like content does (see _append_write).
                self._reasoning_buf += ev.text
                if (time.monotonic() - self._last_reasoning_flush
                        >= _APPEND_FLUSH_INTERVAL):
                    self._flush_reasoning()
            else:
                # Stream tokens as they arrive (dim), same as assistant content.
                self.console.print(
                    Text(ev.text, style=self.theme.reasoning), end='')

    def _on_reasoning_ended(self, ev) -> None:
        if self._reasoning_active:
            self._flush_reasoning()
            self.console.print()  # close the streamed thinking block
            self._reasoning_active = False

    # ── tool calls ─────────────────────────────────────────────────────────

    def _on_tool_call_started(self, ev) -> None:
        # Compact action line (Codex style): "• Write path/to/file".
        if self._last_kind != 'tool':
            # Blank before a new tool group (turn start or after text), but keep
            # consecutive tool lines tight together.
            self._print()
        self._tool_started[ev.call_id] = time.monotonic()
        header = escape(tool_header(ev.name, ev.arguments))
        self._print(f'[{self.theme.tool_bullet}]•[/] {header}')
        self._last_kind = 'tool'

    def _on_tool_call_completed(self, ev) -> None:
        # Indented one-line summary: "  └ 42 lines · 1.2s". Measured HERE even
        # when the draw is held back for a permission menu — the elapsed time is
        # the tool's, not the user's deliberation.
        start = self._tool_started.pop(ev.call_id, None)
        dur = f' · {time.monotonic() - start:.1f}s' if start else ''
        if ev.error:
            summary = escape(tool_summary(ev.result, ev.error))
            self._print(
                f'  [{self.theme.tool_error_border}]└[/] '
                f'[{self.theme.tool_error_border}]{summary}[/][dim]{dur}[/]')
        else:
            summary = escape(tool_summary(ev.result))
            self._print(f'  [dim]└ {summary}{dur}[/]')

    # ── plan / notices / context / errors ──────────────────────────────────

    def _on_plan_updated(self, ev) -> None:
        if not ev.entries:
            return
        mark = {'completed': '[green]✔[/]', 'in_progress': '[yellow]▸[/]'}
        lines = []
        for e in ev.entries:
            # entries may be PlanEntry objects (live) or dicts (deserialized).
            status = (
                e.get('status', 'pending') if isinstance(e, dict) else getattr(
                    e, 'status', 'pending'))
            content = (
                e.get('content', '') if isinstance(e, dict) else getattr(
                    e, 'content', ''))
            lines.append(f'{mark.get(status, "○")} {content}')
        self._print(
            Panel(
                '\n'.join(lines),
                title='plan',
                border_style='blue',
                expand=False))

    def _on_context_compacted(self, ev) -> None:
        detail = ''
        if ev.before_tokens and ev.after_tokens:
            detail = f' {ev.before_tokens}→{ev.after_tokens} tok'
        self._print(
            f'[{self.theme.notice_info}]· context compacted{detail} ·[/]')

    def _on_notice(self, ev) -> None:
        if ev.level == 'info':
            # Command output (/help, /model, /config …): a subtle panel; when
            # the content is structured (YAML/JSON, e.g. /config) syntax-
            # highlight it, else render as markup-safe text.
            lexer = _guess_syntax(ev.text)
            if lexer:
                body = Syntax(
                    ev.text,
                    lexer,
                    theme='ansi_dark',
                    word_wrap=True,
                    background_color='default')
            else:
                body = _bold_unavailable(ev.text)
            self._print(Panel(body, border_style='dim', expand=False))
            return
        style = {
            'success': self.theme.notice_success,
            'warning': self.theme.notice_warning
        }.get(ev.level, self.theme.notice_info)
        self._print(f'[{style}]{ev.text}[/]')

    def _on_error(self, ev) -> None:
        self.finalize()
        self._print(
            Panel(
                f'[bold]{ev.message}[/]',
                title='error',
                border_style=self.theme.error_border,
                expand=False))

    def _on_turn_completed(self, ev) -> None:
        if ev.usage is not None:
            self.state.total_prompt_tokens = ev.usage.total_prompt_tokens
            self.state.total_completion_tokens = ev.usage.total_completion_tokens

    # ── display helpers (called directly by the app, not via events) ────────

    def rule(self, text: str, style: Optional[str] = None) -> None:
        self.console.rule(f'[{style or self.theme.rule}]{text}[/]')

    def notice(self, text: str, level: str = 'info') -> None:
        self._on_notice(type('N', (), {'text': text, 'level': level})())
