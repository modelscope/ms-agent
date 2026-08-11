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
from rich.console import Console
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

    # ── sink protocol ──────────────────────────────────────────────────────

    def emit(self, event: AgentEvent) -> None:
        handler = getattr(self, f'_on_{event.type}', None)
        if handler is not None:
            handler(event)

    def finalize(self) -> None:
        """Tear down any in-flight Live region (call on error / turn abort)."""
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None
        self._content_buf = ''
        self._label_shown = False

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
        if self.console.is_terminal:
            if self._live is None:
                from rich.live import Live
                self._live = Live(
                    console=self.console,
                    refresh_per_second=12,
                    vertical_overflow='visible')
                self._live.start()
            # Stream as plain Text (tolerant of half-formed markdown); the
            # final ContentEnd reflows once into formatted Markdown.
            self._live.update(Text(self._content_buf))
        else:
            # Non-terminal (piped / CI): write raw for clean, scriptable output.
            self.console.file.write(ev.text)
            self.console.file.flush()

    def _on_content_end(self, ev) -> None:
        buf = self._content_buf
        if self._live is not None:
            renderable = Markdown(buf) if buf.strip() else Text('')
            self._live.update(renderable)
            self._live.stop()
            self._live = None
        elif not self.console.is_terminal:
            self.console.file.write('\n')
            self.console.file.flush()
        self._content_buf = ''
        self._label_shown = False
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
            # Stream tokens as they arrive (dim), same as assistant content.
            self.console.print(
                Text(ev.text, style=self.theme.reasoning), end='')

    def _on_reasoning_ended(self, ev) -> None:
        if self._reasoning_active:
            self.console.print()  # close the streamed thinking block
            self._reasoning_active = False

    # ── tool calls ─────────────────────────────────────────────────────────

    def _on_tool_call_started(self, ev) -> None:
        # Compact action line (Codex style): "• Write path/to/file".
        if self._last_kind != 'tool':
            # Blank before a new tool group (turn start or after text), but keep
            # consecutive tool lines tight together.
            self.console.print()
        self._tool_started[ev.call_id] = time.monotonic()
        header = escape(tool_header(ev.name, ev.arguments))
        self.console.print(f'[{self.theme.tool_bullet}]•[/] {header}')
        self._last_kind = 'tool'

    def _on_tool_call_completed(self, ev) -> None:
        # Indented one-line summary: "  └ 42 lines · 1.2s".
        start = self._tool_started.pop(ev.call_id, None)
        dur = f' · {time.monotonic() - start:.1f}s' if start else ''
        if ev.error:
            summary = escape(tool_summary(ev.result, ev.error))
            self.console.print(
                f'  [{self.theme.tool_error_border}]└[/] '
                f'[{self.theme.tool_error_border}]{summary}[/][dim]{dur}[/]')
        else:
            summary = escape(tool_summary(ev.result))
            self.console.print(f'  [dim]└ {summary}{dur}[/]')

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
        self.console.print(
            Panel(
                '\n'.join(lines),
                title='plan',
                border_style='blue',
                expand=False))

    def _on_context_compacted(self, ev) -> None:
        detail = ''
        if ev.before_tokens and ev.after_tokens:
            detail = f' {ev.before_tokens}→{ev.after_tokens} tok'
        self.console.print(
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
                body = Text(ev.text)
            self.console.print(Panel(body, border_style='dim', expand=False))
            return
        style = {
            'success': self.theme.notice_success,
            'warning': self.theme.notice_warning
        }.get(ev.level, self.theme.notice_info)
        self.console.print(f'[{style}]{ev.text}[/]')

    def _on_error(self, ev) -> None:
        self.finalize()
        self.console.print(
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
