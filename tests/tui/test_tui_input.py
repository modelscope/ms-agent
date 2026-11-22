# Copyright (c) ModelScope Contributors. All rights reserved.
"""PromptToolkitInput: status bar formatting + non-tty fallback."""
import asyncio
from unittest.mock import patch

from ms_agent.command import CommandRouter, register_builtin_commands
from ms_agent.tui.input import (PromptToolkitInput, slash_matches,
                                 split_prompt_lines)
from ms_agent.tui.state import TuiState
from ms_agent.ui.input import InputSource


def _router():
    r = CommandRouter()
    register_builtin_commands(r)
    return r


def test_slash_matches_prefix():
    names = [n for n, _ in slash_matches(_router(), '/mod')]
    assert 'model' in names


def test_slash_matches_bare_slash_lists_all():
    names = [n for n, _ in slash_matches(_router(), '/')]
    assert 'help' in names and 'model' in names


def test_slash_no_match_for_plain_text():
    assert list(slash_matches(_router(), 'hello world')) == []


def test_slash_completion_carries_description():
    desc = dict(slash_matches(_router(), '/model')).get('model')
    assert desc  # non-empty description shown as menu meta


def test_satisfies_input_source_protocol():
    assert isinstance(PromptToolkitInput(TuiState()), InputSource)


def test_toolbar_shows_state():
    state = TuiState(model='qwen3.7-plus', perm='ask',
                     session_name='my-session')
    state.total_prompt_tokens = 100
    state.total_completion_tokens = 20
    tb = PromptToolkitInput(state)._toolbar()
    assert 'qwen3.7-plus' in tb
    assert '120 tok' in tb
    assert 'ask' in tb
    assert 'my-session' in tb


def test_read_prompt_falls_back_when_not_tty():
    inp = PromptToolkitInput(TuiState())
    with patch('ms_agent.tui.input.sys.stdin') as stdin, \
            patch('builtins.input', return_value='hello'):
        stdin.isatty.return_value = False
        result = asyncio.run(inp.read_prompt('> '))
    assert result == 'hello'


def test_split_prompt_lines_keeps_each_pasted_line():
    assert split_prompt_lines('/model qwen\nhello') == ['/model qwen', 'hello']
    # A trailing Enter is not an extra blank command.
    assert split_prompt_lines('/model qwen\nhello\n') == ['/model qwen', 'hello']
    assert split_prompt_lines('/model a\r\nsecond\r\n') == ['/model a', 'second']
    assert split_prompt_lines('just one') == ['just one']
    assert split_prompt_lines('\x1b[200~/model qwen\nhello\x1b[201~') == [
        '/model qwen', 'hello'
    ]
    assert split_prompt_lines('^[[200~hello^[[201~') == ['hello']


def test_cursor_report_does_not_become_the_command():
    # Cooked echo and the raw CSI both have to come off the command.
    assert split_prompt_lines('^[[8;8R/mcp list') == ['/mcp list']
    assert split_prompt_lines('\x1b[8;8R/mcp list') == ['/mcp list']
    assert split_prompt_lines('^[[8;8R\n/mcp list') == ['/mcp list']
    assert split_prompt_lines('\x1b[200~^[[8;8R/mcp list\x1b[201~') == [
        '/mcp list'
    ]
    # A report by itself is not a message. A real blank line in a paste stays.
    assert split_prompt_lines('^[[8;8R') == ['']
    assert split_prompt_lines('keep\n\nstill') == ['keep', '', 'still']


def test_multiline_paste_is_one_prompt_then_queued_lines():
    """The second line of a paste must come back as its own read, so /model
    cannot swallow it into the model id. Live is released before the prompt
    draws, and a queued line does not draw another divider."""
    from io import StringIO

    from rich.console import Console

    order = []

    class _Renderer:
        def release_terminal(self):
            order.append('release')

    class _Session:
        calls = 0

        async def prompt_async(self, *args, **kwargs):
            order.append('prompt')
            _Session.calls += 1
            return '/model qwen\nhello\n'

    with patch('ms_agent.tui.input.sys.stdin') as stdin:
        stdin.isatty.return_value = False
        console = Console(file=StringIO(), force_terminal=False, width=40)
        prints = []
        original = console.print

        def _spy(*args, **kwargs):
            prints.append(args)
            return original(*args, **kwargs)

        console.print = _spy
        inp = PromptToolkitInput(TuiState(), console=console, renderer=_Renderer())
    inp._session = _Session()

    with patch('ms_agent.tui.input.sys.stdin') as stdin:
        stdin.isatty.return_value = True
        first = asyncio.run(inp.read_prompt())
        second = asyncio.run(inp.read_prompt())

    assert first == '/model qwen'
    assert second == 'hello'
    assert _Session.calls == 1
    assert order == ['release', 'prompt', 'release']
    assert len(prints) == 1  # divider only for the real prompt


def test_typeahead_disabled_by_default():
    """A directly-constructed input never spawns a background reader, so the
    unit tests and the non-interactive path are unaffected until the app opts
    in via enable_typeahead()."""
    inp = PromptToolkitInput(TuiState())
    assert inp._typeahead is False
    assert inp._capture_enabled() is False
    inp.enable_typeahead()
    assert inp._typeahead is True


def test_busy_line_input_parses_keys_into_submits():
    """The busy line's raw key parser: Enter submits the buffer, backspace edits
    it, escape sequences (arrows / bracketed-paste markers) are consumed and
    ignored, a paste submits each line in order, and Ctrl-C / Ctrl-D signal
    interrupt / eof. ``draw=False`` so this needs no terminal."""
    from ms_agent.tui.busy_input import BusyLineInput

    submits = []
    flags = {'int': 0, 'eof': 0}
    busy = BusyLineInput(
        on_submit=submits.append,
        on_interrupt=lambda: flags.__setitem__('int', flags['int'] + 1),
        on_eof=lambda: flags.__setitem__('eof', flags['eof'] + 1),
        placeholder=lambda: '',
        status=lambda: '',
        draw=False)
    busy._feed(b'hello\r')
    busy._feed(b'/model q\r')
    busy._feed(b'bye\r')
    assert submits == ['hello', '/model q', 'bye']
    # Backspace edits the buffer before the submit.
    busy._feed(b'abc\x7f\r')
    assert submits[-1] == 'ab'
    # A CSI escape sequence is consumed by the parser, never inserted as literal
    # text (Right arrow is a no-op at the end of an empty buffer).
    busy._feed(b'\x1b[C/model list\r')
    assert submits[-1] == '/model list'
    assert '\x1b' not in submits[-1]
    # A multi-line paste submits each line in order.
    busy._feed(b'one\rtwo\r')
    assert submits[-2:] == ['one', 'two']
    # Ctrl-C interrupts the turn; Ctrl-D ends capture.
    busy._feed(b'\x03')
    assert flags['int'] == 1
    busy._feed(b'\x04')
    assert flags['eof'] == 1


def test_busy_line_input_up_down_walk_history():
    """Up/Down recall the shared history list (feature parity with the idle
    prompt); editing the recalled text breaks navigation back to the stash."""
    from ms_agent.tui.busy_input import BusyLineInput

    submits = []
    hist = ['first line', 'second line']
    busy = BusyLineInput(
        on_submit=submits.append,
        on_interrupt=lambda: None,
        on_eof=lambda: None,
        placeholder=lambda: '',
        status=lambda: '',
        history=hist,
        draw=False)
    busy._rows, busy._cols = 24, 60
    busy._feed(b'\x1b[A')  # Up → most recent entry
    assert busy._buf == 'second line'
    busy._feed(b'\x1b[A')  # Up again → older entry
    assert busy._buf == 'first line'
    busy._feed(b'\x1b[B')  # Down → back to the newer entry
    assert busy._buf == 'second line'
    busy._feed(b'\r')
    assert submits[-1] == 'second line'
    # A submitted line is appended to the shared history.
    busy._feed(b'brand new\r')
    assert hist[-1] == 'brand new'


def test_busy_line_input_paste_inserts_newlines_then_enter_splits():
    """A bracketed paste inserts its newlines into the buffer (so the block can
    be edited before sending); a real Enter then submits it split per line —
    exactly like the idle prompt's split_prompt_lines."""
    from ms_agent.tui.busy_input import BusyLineInput

    submits = []
    busy = BusyLineInput(
        on_submit=submits.append,
        on_interrupt=lambda: None,
        on_eof=lambda: None,
        placeholder=lambda: '',
        status=lambda: '',
        draw=False)
    busy._rows, busy._cols = 24, 60
    busy._feed(b'\x1b[200~alpha\nbeta\x1b[201~')
    assert submits == []  # paste does not submit
    assert busy._buf == 'alpha\nbeta'
    busy._feed(b'\r')  # real Enter submits the whole buffer, split per line
    assert submits == ['alpha', 'beta']


def test_busy_line_input_wraps_and_grows_the_region():
    """A long buffer wraps to multiple visual rows and the reserved block grows
    to fit (up to the cap), mirroring the idle prompt's dynamic height."""
    from ms_agent.tui.busy_input import BusyLineInput

    busy = BusyLineInput(
        on_submit=lambda l: None,
        on_interrupt=lambda: None,
        on_eof=lambda: None,
        placeholder=lambda: '',
        status=lambda: '',
        prompt_symbol='>',
        draw=False)
    busy._rows, busy._cols = 24, 20
    one_row = busy._block_height()
    busy._buf = 'x' * 80  # far wider than one 20-col row
    busy._cur = len(busy._buf)
    wrapped = busy._wrapped()
    assert len(wrapped) > 1  # it wrapped
    assert busy._block_height() > one_row  # the region grew
    # The editing area is capped so a huge paste cannot eat the whole screen.
    busy._buf = 'y' * 5000
    busy._cur = len(busy._buf)
    assert busy._input_height() <= 12
    # The cursor row stays visible: it is within the scrolled window.
    crow, _ = busy._cursor_rc()
    assert crow == len(busy._wrapped()) - 1


def test_busy_line_input_completion_menu_opens_and_accepts():
    """Typing '/' opens the slash menu from the injected completions callable;
    Tab (or Right) accepts the highlighted entry into the buffer."""
    from ms_agent.tui.busy_input import BusyLineInput

    def comps(text):
        if text == '/':
            return [('model', 'show/set model'), ('quit', 'exit')]
        if text.startswith('/mo'):
            return [('model', 'show/set model')]
        return []

    busy = BusyLineInput(
        on_submit=lambda l: None,
        on_interrupt=lambda: None,
        on_eof=lambda: None,
        placeholder=lambda: '',
        status=lambda: '',
        completions=comps,
        draw=False)
    busy._rows, busy._cols = 24, 60
    busy._feed(b'/')
    assert [n for n, _ in busy._comp] == ['/model', '/quit']
    assert busy._menu_height() == 2
    busy._feed(b'\x1b[B')  # Down → highlight /quit
    assert busy._comp_sel == 1
    busy._feed(b'\t')  # Tab accepts
    assert busy._buf == '/quit '
    assert busy._comp == []  # a trailing space closes the menu
    # Narrowing by typing more.
    busy._feed(b'\x15')  # Ctrl-U clears the line
    busy._feed(b'/mo')
    assert [n for n, _ in busy._comp] == ['/model']


def test_enqueue_busy_line_skips_blanks():
    """Blank/whitespace interjections are dropped, so an idle Enter while busy
    does not inject an empty message; real lines queue in order."""
    inp = PromptToolkitInput(TuiState())
    inp._mode = 'steer'
    inp._enqueue_busy_line('hello')
    inp._enqueue_busy_line('')
    inp._enqueue_busy_line('   ')
    inp._enqueue_busy_line('/model q')
    assert inp._queued == ['hello', '/model q']


def test_read_prompt_drains_queued_typeahead_fifo():
    """On going idle, read_prompt returns queued type-ahead lines in order
    without drawing a fresh prompt (session is None → capture stays off)."""

    async def run():
        inp = PromptToolkitInput(TuiState())
        inp._session = None
        inp._typeahead = True
        inp._queued = ['first', 'second']
        a = await inp.read_prompt()
        b = await inp.read_prompt()
        return a, b, inp._queued

    a, b, rest = asyncio.run(run())
    assert (a, b) == ('first', 'second')
    assert rest == []


def test_busy_line_input_draws_buffer_and_simulated_cursor():
    """With drawing on (to a buffer), the reserved input line shows the prompt
    symbol, the typed text and a reverse-video block cursor; the placeholder is
    shown only while the buffer is empty and clears once the user types."""
    from io import StringIO

    from ms_agent.tui.busy_input import BusyLineInput

    out = StringIO()
    busy = BusyLineInput(
        on_submit=lambda l: None,
        on_interrupt=lambda: None,
        on_eof=lambda: None,
        placeholder=lambda: 'HINT',
        status=lambda: 'ST',
        prompt_symbol='>',
        out=out,
        fd=0)
    busy._rows, busy._cols = 24, 40
    busy._draw_input()
    drawn = out.getvalue()
    assert '>' in drawn and 'HINT' in drawn  # empty buffer → placeholder + caret
    assert '\x1b[7m' in drawn  # reverse-video simulated cursor

    out.truncate(0)
    out.seek(0)
    busy._buf = 'hello'
    busy._cur = len(busy._buf)  # as if typed: caret sits at the end
    busy._draw_input()
    drawn = out.getvalue()
    assert 'hello' in drawn
    assert 'HINT' not in drawn  # placeholder gone once typing
    assert '\x1b[7m' in drawn

    # The divider is a full-width rule ABOVE the box; the status toolbar is a
    # plain dim line BELOW it with no rule characters — mirroring the idle
    # prompt (Rule on top, bottom_toolbar underneath).
    out.truncate(0)
    out.seek(0)
    busy._reserved = busy._block_height()
    busy._draw_divider()
    div = out.getvalue()
    assert '─' in div  # full-width rule
    assert 'ST' not in div  # status is no longer fused into the divider

    out.truncate(0)
    out.seek(0)
    busy._draw_toolbar()
    tb = out.getvalue()
    assert 'ST' in tb  # status text on the bottom toolbar row
    assert '─' not in tb  # the toolbar carries no rule characters


# ── interjection mode + steering poll ────────────────────────────────────────


def test_interject_mode_defaults_to_steer():
    assert PromptToolkitInput(TuiState()).interject_mode == 'steer'


def test_set_and_toggle_interject_mode():
    inp = PromptToolkitInput(TuiState())
    assert inp.set_interject_mode('queue') == 'queue'
    assert inp.interject_mode == 'queue'
    assert inp.toggle_interject_mode() == 'steer'
    # 's*' → steer, anything else → queue
    assert inp.set_interject_mode('steer') == 'steer'
    assert inp.set_interject_mode('nonsense') == 'queue'


def test_poll_steering_drains_plain_and_stops_at_command():
    inp = PromptToolkitInput(TuiState())
    inp._mode = 'steer'
    inp._queued = ['a', 'b', '/model q', 'c']
    assert inp.poll_steering() == ['a', 'b']
    # The command stays at the head and 'c' waits behind it: a message never
    # jumps ahead of an earlier command (order the user typed is preserved).
    assert inp._queued == ['/model q', 'c']


def test_poll_steering_noop_in_queue_mode():
    inp = PromptToolkitInput(TuiState())
    inp._mode = 'queue'
    inp._queued = ['a', 'b']
    assert inp.poll_steering() == []
    assert inp._queued == ['a', 'b']


def test_busy_placeholder_states_mode():
    inp = PromptToolkitInput(TuiState())
    inp._mode = 'steer'
    val = inp._busy_placeholder().value
    assert 'interject without interrupting' in val
    inp._mode = 'queue'
    val = inp._busy_placeholder().value
    assert 'queue until this turn ends' in val
    # Both modes tell the user how to stop the turn (ctrl+c is the reliable,
    # advertised stop key; a bare esc is ambiguous under prompt_toolkit).
    assert 'ctrl+c stops this turn' in val
    # It is a greyed placeholder, not a prompt prefix: no prompt symbol embedded,
    # so the cursor stays at the left edge and the hint clears on typing.
    assert inp._theme.prompt_symbol not in val
    assert 'ansibrightblack' in val


def test_busy_prompt_uses_short_message_not_long_prefix():
    # The busy input must reuse the same short prompt symbol as idle (cursor at
    # the left edge); the long hint lives in the placeholder, never the prefix.
    inp = PromptToolkitInput(TuiState())
    msg = inp._message().value
    assert inp._theme.prompt_symbol in msg
    assert 'ctrl+c' not in msg
    assert 'interject' not in msg


def test_toolbar_shows_queued_count_and_mode():
    inp = PromptToolkitInput(TuiState())
    inp._mode = 'steer'
    inp._queued = ['x', 'y']
    tb = inp._toolbar()
    assert '2 queued' in tb
    assert 'interject: steer' in tb


def test_capture_receipt_prints_disposition():
    class FakeConsole:

        def __init__(self):
            self.lines = []

        def print(self, s):
            self.lines.append(s)

    con = FakeConsole()
    inp = PromptToolkitInput(TuiState(), console=con)
    inp._mode = 'steer'
    inp._capture_receipt('hello')
    inp._capture_receipt('/model q')
    inp._mode = 'queue'
    inp._capture_receipt('world')
    joined = '\n'.join(con.lines)
    assert 'interject without interrupting' in joined  # steer + plain
    assert 'runs after this turn ends' in joined  # command always queues
    assert 'send after this turn ends' in joined  # queue + plain


# ── /stop: busy-only interrupt (same as ctrl+c) ──────────────────────────────


def test_stop_while_busy_interrupts_instead_of_queuing():
    """/stop typed while busy fires the same interrupt as ctrl+c immediately and
    is NOT queued — queueing would only run it after the turn it stops."""
    inp = PromptToolkitInput(TuiState())
    inp._mode = 'steer'
    calls = []
    inp._interrupt_turn = lambda: calls.append('interrupt')
    inp._enqueue_busy_line('/stop')
    assert calls == ['interrupt']
    assert inp._queued == []


def test_stop_alias_stops_and_other_commands_still_queue():
    inp = PromptToolkitInput(TuiState())
    calls = []
    inp._interrupt_turn = lambda: calls.append('interrupt')
    inp._enqueue_busy_line('/cancel')  # alias also stops
    assert calls == ['interrupt'] and inp._queued == []
    inp._enqueue_busy_line('/model q')  # a normal command still queues
    inp._enqueue_busy_line('hello')  # a plain message still queues
    assert calls == ['interrupt']  # no extra interrupt fired
    assert inp._queued == ['/model q', 'hello']


def test_is_stop_command_matching():
    f = PromptToolkitInput._is_stop_command
    assert f('/stop') and f('/STOP') and f('/stop now') and f('/cancel')
    assert f('  /stop  ')
    assert not f('/stopped') and not f('stop') and not f('/model')
    assert not f('') and not f(None)


def _app_router():
    from ms_agent.command import CommandRouter
    from ms_agent.tui.app import TuiApp
    app = TuiApp.__new__(TuiApp)
    app.router = CommandRouter()
    app._register_session_commands()
    return app


def test_stop_registered_as_priority_tui_command():
    """/stop is on the app router as a priority command (the router's "instant
    # /stop" tier) visible in the tui slash menu, so it is discoverable."""
    app = _app_router()
    assert app.router.is_command('/stop')
    assert app.router.is_priority('/stop')
    assert 'tui' in app.router.resolve('stop').ui_scope
    assert 'stop' in [n for n, _ in slash_matches(app.router, '/sto')]
    # the /cancel alias resolves to the same command
    assert app.router.resolve('cancel').name == 'stop'


def test_stop_at_idle_reports_nothing_running():
    import asyncio

    from ms_agent.command import CommandContext
    app = _app_router()
    app._streaming = False
    ctx = CommandContext(
        raw_input='/stop', command_name='stop', args='', source='tui')
    res = asyncio.run(app.router.dispatch(ctx))
    assert res is not None and 'nothing is running' in res.content


def test_stop_while_streaming_calls_turn_sigint():
    """Reaching the handler while streaming (e.g. the mid-turn blocking prompt)
    cancels the turn — the same action ctrl+c takes."""
    import asyncio

    from ms_agent.command import CommandContext
    app = _app_router()
    app._streaming = True
    called = []
    app._on_turn_sigint = lambda: called.append(1)
    ctx = CommandContext(
        raw_input='/stop', command_name='stop', args='', source='tui')
    res = asyncio.run(app.router.dispatch(ctx))
    assert called == [1]
    assert 'stopping this turn' in res.content

