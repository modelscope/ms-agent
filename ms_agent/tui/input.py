# Copyright (c) ModelScope Contributors. All rights reserved.
"""prompt_toolkit-backed async input for the TUI.

Implements the ``ms_agent.ui.InputSource`` contract: an awaitable
``read_prompt`` that reads a line via ``PromptSession.prompt_async`` so the
native agent loop can await input without blocking the event loop. Adds a
persistent bottom status bar (model · tokens · perm · session) and slash-command
completion sourced from the agent's ``CommandRouter`` (scoped to ``tui``).

Degrades gracefully: when prompt_toolkit or a TTY is unavailable (pipes, CI),
falls back to blocking ``input()`` in an executor, so the TUI stays scriptable.
"""
from __future__ import annotations

import asyncio
import re
import sys
from typing import TYPE_CHECKING, Optional

from ms_agent.tui.busy_input import MENU_RESERVE, BusyLineInput
from ms_agent.tui.state import TuiState
from ms_agent.tui.theme import DEFAULT_THEME, Theme

if TYPE_CHECKING:
    from ms_agent.command.router import CommandRouter

# Bracketed paste wraps the clipboard in these markers. If they leak into the
# line (the terminal was not in paste mode) they must not become part of the
# command. The caret form is how a cooked terminal echoes the same bytes.
_PASTE_MARKERS = (
    '\x1b[200~',
    '\x1b[201~',
    '^[[200~',
    '^[[201~',
)
# Cursor Position Report. A cooked terminal echoes it as text, so
# ``^[[8;8R/mcp list`` would otherwise be sent to the model.
_CPR_RE = re.compile(r'(?:\x1b\[\d+;\d+R|\^\[\[\d+;\d+R)')


def _strip_terminal_noise(line: str) -> str:
    for marker in _PASTE_MARKERS:
        line = line.replace(marker, '')
    return _CPR_RE.sub('', line)


def split_prompt_lines(text: str) -> list:
    """Split one paste into the lines the command loop should see.

    prompt_toolkit returns a multiline paste as a single string. Fed through
    whole, ``/model`` treats the next line as part of the model id. A trailing
    empty line (the paste ended on Enter) is not itself a command. A cursor
    position report (``^[[8;8R``) is terminal noise, not part of the command.
    """
    cleaned = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    if '\n' not in cleaned:
        return [_strip_terminal_noise(cleaned)]
    lines = cleaned.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    kept = []
    for line in lines:
        stripped = _strip_terminal_noise(line)
        # A line that was only a cursor report must not be sent.
        if stripped == '' and line != '':
            continue
        kept.append(stripped)
    return kept or ['']


def slash_matches(router, text: str):
    """Yield ``(name, description)`` for /command completions of ``text``.

    Only fires when the line starts with ``/`` (so file paths and normal text
    don't trigger a menu). Scoped to the ``tui`` command source; de-dupes names
    and aliases. Kept dependency-free so it's unit-testable without a terminal.
    """
    if router is None or not text.startswith('/'):
        return
    word = text[1:].lower()
    seen = set()
    for cmds in router.list_commands('tui').values():
        for c in cmds:
            for nm in (c.name, *getattr(c, 'aliases', ())):
                if nm.lower().startswith(word) and nm not in seen:
                    seen.add(nm)
                    yield nm, c.description


class PromptToolkitInput:
    """Async input source with a status bar and slash completion.

    ``supports_credential_prompt`` is true: the TUI can pause a turn and take
    ``/model provider key`` in place.
    """

    supports_credential_prompt = True

    def __init__(self,
                 state: TuiState,
                 router: Optional['CommandRouter'] = None,
                 theme: Theme = DEFAULT_THEME,
                 console: object = None,
                 renderer: object = None) -> None:
        self._state = state
        self._router = router
        self._theme = theme
        self._console = console  # rich Console, for the pre-prompt divider
        # RichEventSink. Released before prompt_toolkit draws, so Live's
        # refresh thread is not still writing when raw mode starts.
        self._renderer = renderer
        # Lines left over from a multiline paste, and messages typed while the
        # agent was busy (type-ahead). Each becomes its own prompt, drained in
        # order the next time the agent goes idle.
        self._queued: list = []
        # One history shared by the idle prompt_toolkit session and the busy
        # BusyLineInput, so ↑/↓ recalls the same lines in both states. The idle
        # session reads/writes it through _SharedHistory; the busy input takes it
        # directly as its ``history`` list.
        self._input_history: list = []
        # Type-ahead capture: a background prompt that keeps reading while the
        # agent works, so the user can queue messages at any time. Off unless
        # the app enables it, so unit tests that drive read_prompt directly
        # never spawn a background reader.
        self._typeahead = False
        self._capturing = False
        self._capture_task: Optional[asyncio.Task] = None
        # Set once the pinned prompt is actually drawn (patch_stdout active and
        # prompt_async rendering). ``_start_capture`` waits on it so a caller —
        # resume after a permission menu, or read_prompt before a turn — never
        # returns into a window where streamed output is not yet routed above the
        # input box (which is what made the prompt look like it vanished).
        self._capture_ready = asyncio.Event()
        # Set when a modal (permission menu) borrows the terminal mid-capture,
        # so capture resumes afterwards instead of staying stopped.
        self._resume_capture = False
        # Interjection mode for plain messages typed while busy:
        #   'steer' — inject into the running turn at the next tool boundary
        #             without interrupting it (the default).
        #   'queue' — hold until the turn finishes, then send.
        # Slash/bash commands ALWAYS queue regardless of mode (they must not
        # run mid-turn). Toggled with the /interject command.
        self._mode = 'steer'
        self._session = self._build_session()

    def _build_session(self):
        # Only build a prompt_toolkit session for a real terminal. Constructing
        # one under a pipe/CI emits a "not a terminal" warning; the executor
        # input() fallback in read_prompt handles those cases cleanly.
        if not sys.stdin.isatty():
            return None
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.completion import Completer, Completion
            from prompt_toolkit.history import History
            from prompt_toolkit.styles import Style

            router = self._router
            shared = self._input_history

            class _SharedHistory(History):
                """prompt_toolkit History backed by the shared list, so lines
                typed while busy also show up in the idle prompt's ↑/↓ (and vice
                versa). ``resync`` drops the loaded cache so a fresh idle prompt
                picks up entries the busy input appended since the last load."""

                def load_history_strings(self):
                    return reversed(shared)

                def store_string(self, string):  # noqa: D102 - persistence no-op
                    pass

                def append_string(self, string):
                    shared.append(string)
                    self._loaded_strings.insert(0, string)

                def resync(self):
                    self._loaded = False

            class _SlashCompleter(Completer):

                def get_completions(self, document, complete_event):
                    text = document.text_before_cursor
                    for name, desc in slash_matches(router, text):
                        yield Completion(
                            '/' + name,
                            start_position=-len(text),
                            display=f'/{name}',
                            display_meta=desc)

            from prompt_toolkit.formatted_text import HTML
            from prompt_toolkit.key_binding import KeyBindings

            kb = KeyBindings()

            @kb.add('escape')
            def _escape(event):  # noqa: ANN001
                sig = getattr(self, '_sigint', None)
                if sig is not None and getattr(sig, '_streaming', False):
                    # Busy: esc interrupts the running turn but keeps the
                    # session and the queued messages. Surfacing
                    # KeyboardInterrupt reuses the capture loop's cancel path.
                    event.app.exit(exception=KeyboardInterrupt)
                else:
                    # Idle: preserve the default escape (dismiss completion).
                    buf = event.app.current_buffer
                    if buf.complete_state is not None:
                        buf.cancel_completion()

            style = Style.from_dict({
                'completion-menu':
                'bg:#1c1c1c',
                'completion-menu.completion':
                'bg:#1c1c1c #d0d0d0',
                'completion-menu.completion.current':
                'bg:#00afd7 #000000 bold',
                'completion-menu.meta.completion':
                'bg:#1c1c1c #6c6c6c',
                'completion-menu.meta.completion.current':
                'bg:#0087af #e4e4e4',
                'scrollbar.background':
                'bg:#303030',
                'scrollbar.button':
                'bg:#00afd7',
                # a calm dim status line, not the default reversed bar
                'bottom-toolbar':
                'noreverse bg:default #808080',
                'bottom-toolbar.text':
                'noreverse bg:default #808080',
            })
            return PromptSession(
                history=_SharedHistory(),
                completer=_SlashCompleter(),
                key_bindings=kb,
                complete_while_typing=True,
                # Reserve the same menu space the busy box does, so an empty
                # idle prompt and an empty busy prompt are the same height.
                reserve_space_for_menu=MENU_RESERVE,
                # Up and down walk this history.
                bottom_toolbar=self._toolbar,
                placeholder=HTML(
                    '<ansibrightblack>Type a message'
                    '  ·  / for commands  ·  ↑ history</ansibrightblack>'),
                style=style)
        except Exception:
            return None

    def note_model(self, model: str) -> None:
        """Refresh the status-bar model after a command mutates it."""
        if model:
            self._state.model = str(model)

    def _toolbar(self):
        s = self._state
        parts = []
        if s.model:
            parts.append(s.model)
        parts.append(f'{s.total_tokens} tok')
        if s.perm:
            parts.append(s.perm)
        if s.session_name:
            parts.append(s.session_name)
        # Show the interjection mode + how many messages are waiting, so the
        # user always knows what Enter will do while the agent is busy.
        if self._queued:
            parts.append(f'{len(self._queued)} queued')
        parts.append('interject: ' + ('steer' if self._mode == 'steer'
                                      else 'queue'))
        return '  ' + ' · '.join(parts)

    def _message(self):
        from prompt_toolkit.formatted_text import HTML
        return HTML(
            f'<b><ansicyan>{self._theme.prompt_symbol}</ansicyan></b> ')

    def _busy_hint_text(self) -> str:
        """Plain mode-aware hint for the empty busy input.

        ``ctrl+c`` is the advertised stop key (a bare ``esc`` binding exists but
        prompt_toolkit's escape disambiguation makes it fire only intermittently,
        so we don't promise it). Kept as plain text because the busy line is
        drawn directly by :class:`~ms_agent.tui.busy_input.BusyLineInput`, not by
        a prompt_toolkit prompt.
        """
        if self._mode == 'steer':
            return ('Type to interject without interrupting'
                    '  ·  ctrl+c stops this turn')
        return ('Type to queue until this turn ends'
                '  ·  ctrl+c stops this turn')

    def _busy_placeholder(self):
        """The busy hint as greyed prompt_toolkit HTML (idle-style placeholder).

        Retained for the prompt_toolkit path / tests; the live busy line renders
        ``_busy_hint_text`` itself in dim. Either way the hint is a *placeholder*,
        never a prompt prefix — the cursor sits at the left edge and the hint
        clears on typing.
        """
        from prompt_toolkit.formatted_text import HTML
        return HTML(
            f'<ansibrightblack>{self._busy_hint_text()}</ansibrightblack>')

    def _capture_receipt(self, line: str) -> None:
        """Echo a captured type-ahead line and its disposition above the prompt.

        Printed through the Rich console so ``patch_stdout`` routes it above the
        pinned input prompt. Dims the preview so receipts never read as agent
        output.
        """
        console = self._console
        if console is None:
            return
        preview = line if len(line) <= 48 else line[:47] + '…'
        preview = preview.replace('[', '\\[')
        if self._is_command(line):
            note = 'queued — runs after this turn ends'
        elif self._mode == 'steer':
            note = 'received — will interject without interrupting'
        else:
            note = 'queued — will send after this turn ends'
        try:
            console.print(f'[dim]⤷ {note}: {preview}[/dim]')
        except Exception:
            pass

    # ── type-ahead capture ──────────────────────────────────────────────────

    def _capture_enabled(self) -> bool:
        return (self._typeahead and self._session is not None
                and sys.stdin.isatty())

    def enable_typeahead(self) -> None:
        """Turn on type-ahead capture (the app calls this once at startup)."""
        self._typeahead = True

    # ── interjection mode ───────────────────────────────────────────────────

    @property
    def interject_mode(self) -> str:
        return self._mode

    def set_interject_mode(self, mode: str) -> str:
        """Set 'steer' or 'queue'; returns the effective mode."""
        self._mode = 'steer' if str(mode).lower().startswith('s') else 'queue'
        return self._mode

    def toggle_interject_mode(self) -> str:
        return self.set_interject_mode(
            'queue' if self._mode == 'steer' else 'steer')

    @staticmethod
    def _is_command(line) -> bool:
        return isinstance(line, str) and line.lstrip().startswith('/')

    @staticmethod
    def _is_stop_command(line) -> bool:
        """True for the busy-only ``/stop`` (and its ``/cancel`` alias).

        Matched on the first word so ``/stop`` and ``/stop now`` both fire, but
        ``/stopped`` or a bare ``stop`` (no slash) do not.
        """
        if not isinstance(line, str):
            return False
        head = line.strip().split(' ', 1)[0].lower()
        return head in ('/stop', '/cancel')

    def poll_steering(self) -> list:
        """Non-blocking drain of plain messages to inject into the live turn.

        Returns [] unless in 'steer' mode. Stops at the first queued command so
        a command keeps its position (it must run at idle, never mid-turn);
        messages submitted after a command therefore also wait, preserving the
        order the user typed them in.
        """
        if self._mode != 'steer':
            return []
        out = []
        while self._queued and not self._is_command(self._queued[0]):
            out.append(self._queued.pop(0))
        return out

    async def _start_capture(self) -> None:
        """Begin reading input in the background while the agent is busy.

        No-ops when not on a TTY (pipes / CI) or when already capturing, so the
        non-interactive path and tests are untouched.
        """
        if self._capturing or not self._capture_enabled():
            return
        self._capturing = True
        self._capture_ready.clear()
        self._capture_task = asyncio.create_task(self._capture_loop())
        # Do not return until the pinned prompt is actually drawn (or the loop
        # bails early), so the caller — a permission-menu resume or a fresh turn —
        # never streams into a window where output is not yet routed above the
        # input box. The timeout is a safety net, not the normal path.
        try:
            await asyncio.wait_for(self._capture_ready.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass

    async def _stop_capture(self) -> None:
        """Stop the background reader and restore the normal render mode."""
        if not self._capturing:
            return
        self._capturing = False
        task = self._capture_task
        self._capture_task = None
        if task is None or task.done():
            return
        # A task left over from a closed loop (e.g. a prior asyncio.run in a
        # test) belongs to another loop; drop it rather than awaiting it here.
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if task.get_loop() is not running:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    async def suspend_capture(self) -> None:
        """Yield the terminal to a modal (permission menu) mid-turn."""
        self._resume_capture = self._capturing
        await self._stop_capture()

    async def resume_capture(self) -> None:
        """Re-arm type-ahead after a modal releases the terminal."""
        resume, self._resume_capture = self._resume_capture, False
        if resume:
            await self._start_capture()

    async def _capture_loop(self) -> None:
        """Read interjections while the agent is busy; queue each for the turn.

        The busy input is a fixed bottom line drawn by
        :class:`~ms_agent.tui.busy_input.BusyLineInput`, which reserves the last
        two terminal rows with a scroll region so streamed output scrolls above
        and never redraws the line the user is typing in (no flicker). The
        renderer stays in append mode so its text is plain output that scrolls in
        that region instead of a transient Live region fighting the reserved rows.
        """
        set_append = getattr(self._renderer, 'set_append_mode', None)
        busy = None
        try:
            if callable(set_append):
                set_append(True)
            busy = BusyLineInput(
                on_submit=self._enqueue_busy_line,
                on_interrupt=self._interrupt_turn,
                on_eof=lambda: None,
                placeholder=self._busy_hint_text,
                status=self._toolbar,
                prompt_symbol=self._theme.prompt_symbol,
                completions=lambda text: list(
                    slash_matches(self._router, text)),
                history=self._input_history,
                console=self._console,
            )
            await busy.start()
            # The reserved input line is genuinely drawn now: release
            # _start_capture so a permission-menu resume or a fresh turn never
            # returns into a window where output is not yet scrolling above it.
            self._capture_ready.set()
            await busy.wait_stopped()
        except asyncio.CancelledError:
            pass
        finally:
            # Release _start_capture even on an early error/cancel, so its wait
            # can never hang, and tear the reserved region down before the next
            # owner of the terminal (the idle prompt or a modal) takes over.
            self._capture_ready.set()
            if busy is not None:
                await busy.stop()
            if callable(set_append):
                set_append(False)

    def _enqueue_busy_line(self, line: str) -> None:
        """Queue one line typed while busy (blank lines are dropped).

        ``/stop`` is the one exception: like a busy Ctrl-C it interrupts the
        running turn immediately (keeping the output generated so far) instead of
        queueing until idle. Every other slash command must wait for the turn to
        end, but stopping *is* ending the turn — so it cannot wait for the very
        thing it is trying to stop.
        """
        line = _strip_terminal_noise(line)
        if not line.strip():
            return
        if self._is_stop_command(line):
            self._interrupt_turn()
            return
        self._queued.append(line)
        self._capture_receipt(line)

    def _interrupt_turn(self) -> None:
        """Forward a busy-state Ctrl-C to the app's turn cancel.

        While busy, Ctrl-C means "interrupt the turn", not "stop typing" — the
        raw reader surfaces the key here rather than as a SIGINT, so this matches
        the streaming-without-type-ahead behaviour.
        """
        on_turn = getattr(
            getattr(self, '_sigint', None), '_on_turn_sigint', None)
        if callable(on_turn):
            on_turn()

    def _release_terminal(self) -> None:
        renderer = self._renderer
        if renderer is None:
            return
        release = getattr(renderer, 'release_terminal', None)
        if release is not None:
            release()

    async def read_prompt(self, prompt: str = '❯ ') -> str:
        # The TUI owns its prompt presentation; the caller's ``prompt`` arg is
        # only a fallback hint for the non-interactive path.
        # The agent just went idle: stop the background type-ahead reader (which
        # releases the render mode it held) before drawing the interactive prompt.
        await self._stop_capture()
        # Live must be fully stopped before prompt_toolkit enables raw mode
        # and bracketed paste. A queued line skips the divider, but
        # still waits out a region left up by the turn that just finished.
        self._release_terminal()
        if self._queued:
            line = self._queued.pop(0)
            # Submitting a queued line starts another busy period — re-arm
            # type-ahead so the user can keep typing while the agent works.
            await self._start_capture()
            return line
        if self._session is not None and sys.stdin.isatty():
            # A subtle full-width divider separates the input from the
            # conversation above (Claude Code style).
            if self._console is not None:
                from rich.rule import Rule
                self._console.print(Rule(style='grey30'))
            # prompt_toolkit owns Ctrl-C while the line is being edited.
            # After it returns, the TUI handler covers the stream that follows.
            sigint = getattr(self, '_sigint', None)
            if sigint is not None:
                sigint._streaming = False
            # Pick up history entries the busy input appended since the last load.
            resync = getattr(
                getattr(self._session, 'history', None), 'resync', None)
            if callable(resync):
                resync()
            try:
                text = await self._session.prompt_async(self._message())
            finally:
                if sigint is not None:
                    sigint._arm_turn_sigint()
                    sigint._streaming = True
            lines = split_prompt_lines(text)
            if len(lines) > 1:
                self._queued.extend(lines[1:])
            # The submitted line starts a busy period — re-arm type-ahead.
            await self._start_capture()
            return lines[0] if lines else ''
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, input, prompt)
