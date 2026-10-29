# Copyright (c) ModelScope Contributors. All rights reserved.
"""RichEventSink: renders the AgentEvent stream and tracks status state."""
from io import StringIO

import rich.live
from rich.console import Console
from rich.markdown import Markdown

from ms_agent.tui.renderer import RichEventSink
from ms_agent.tui.state import TuiState
from ms_agent.ui.events import (ContentDelta, ContentEnd, ErrorRaised, Notice,
                                PlanEntry, PlanUpdated, ReasoningDelta,
                                ReasoningEnded, ReasoningStarted,
                                ToolCallCompleted, ToolCallStarted, TurnCompleted,
                                TurnStarted, UsageInfo)


def _sink():
    console = Console(file=StringIO(), force_terminal=False, width=80)
    state = TuiState()
    return RichEventSink(console, state), console, state


def _out(console) -> str:
    return console.file.getvalue()


def test_content_stream_renders_text():
    sink, console, _ = _sink()
    sink.emit(ContentDelta('Hello '))
    sink.emit(ContentDelta('world'))
    sink.emit(ContentEnd())
    assert _out(console).count('Hello world') == 1


def test_tool_call_and_result_render():
    # Compact Codex-style lines: "• Search modelscope" then "  └ found it".
    sink, console, _ = _sink()
    sink.emit(ToolCallStarted(call_id='c1', name='web_search---exa_search',
                              arguments={'query': 'modelscope'}))
    sink.emit(ToolCallCompleted(call_id='c1', name='web_search---exa_search',
                                result='found it'))
    out = _out(console)
    assert '•' in out and 'Search' in out and 'modelscope' in out
    assert '└' in out and 'found it' in out


def test_tool_error_render():
    sink, console, _ = _sink()
    sink.emit(ToolCallStarted(call_id='c2', name='code_executor---shell',
                              arguments={'command': 'bad'}))
    sink.emit(ToolCallCompleted(call_id='c2', name='code_executor---shell',
                                result='', error='command not found'))
    assert 'error' in _out(console) and 'command not found' in _out(console)


def test_config_output_syntax_highlighted():
    # /config-style YAML notice renders (no crash; content present).
    sink, console, _ = _sink()
    sink.emit(Notice(level='info',
                     text='llm:\n  model: qwen\n  service: openai\ntag: x'))
    out = _out(console)
    assert 'model' in out and 'qwen' in out


def test_turn_completed_updates_status_state():
    sink, _, state = _sink()
    sink.emit(TurnCompleted(usage=UsageInfo(
        total_prompt_tokens=100, total_completion_tokens=50)))
    assert state.total_prompt_tokens == 100
    assert state.total_completion_tokens == 50
    assert state.total_tokens == 150


def test_reasoning_renders_thinking_block():
    sink, console, _ = _sink()
    sink.emit(ReasoningStarted())
    sink.emit(ReasoningDelta('let me consider'))
    sink.emit(ReasoningEnded())
    out = _out(console)
    assert 'Thinking' in out and 'let me consider' in out


def test_gap_between_tool_and_thinking():
    # A blank line must separate a tool result from a following Thinking block.
    sink, console, _ = _sink()
    sink.emit(ToolCallStarted(call_id='c', name='skills---skill_view',
                              arguments={}))
    sink.emit(ToolCallCompleted(call_id='c', name='skills---skill_view',
                                result='done'))
    sink.emit(ReasoningStarted())
    sink.emit(ReasoningDelta('hmm'))
    sink.emit(ReasoningEnded())
    lines = _out(console).split('\n')
    ti = next(i for i, ln in enumerate(lines) if '└' in ln)
    thi = next(i for i, ln in enumerate(lines) if 'Thinking' in ln)
    assert any(lines[j].strip() == '' for j in range(ti + 1, thi))


def test_error_renders_message():
    sink, console, _ = _sink()
    sink.emit(ErrorRaised(message='boom'))
    assert 'boom' in _out(console)


def test_notice_and_plan_render():
    sink, console, _ = _sink()
    sink.emit(Notice(level='success', text='saved'))
    sink.emit(PlanUpdated(entries=[PlanEntry('do X', 'completed')]))
    out = _out(console)
    assert 'saved' in out and 'do X' in out


def test_unhandled_event_is_ignored():
    sink, console, _ = _sink()
    # No _on_turn_started handler exists — emit must be a safe no-op.
    sink.emit(TurnStarted(turn_id='t1'))
    assert _out(console) == ''


def test_finalize_is_safe_without_live():
    sink, _, _ = _sink()
    sink.finalize()  # no active Live — must not raise


def test_hold_output_defers_draws_until_the_screen_is_released():
    """A permission menu owns the terminal while it is up; a sibling tool call
    finishing mid-menu must not print into it. Tool completions arrive per call
    now (LLMAgent.parallel_tool_call), so that overlap is reachable."""
    sink, console, _ = _sink()
    sink.emit(ToolCallStarted(call_id='c1', name='file_system---read_file',
                              arguments={'path': 'a.txt'}))
    with sink.hold_output():
        sink.emit(ToolCallCompleted(call_id='c1',
                                    name='file_system---read_file',
                                    result='aaa'))
        sink.emit(PlanUpdated(entries=[PlanEntry('do X', 'completed')]))
        held = _out(console)
        assert 'aaa' not in held and 'do X' not in held
    out = _out(console)
    assert 'aaa' in out and 'do X' in out  # flushed on release, in order
    assert out.index('aaa') < out.index('do X')


def test_hold_output_flushes_even_if_the_menu_raises():
    sink, console, _ = _sink()
    try:
        with sink.hold_output():
            sink.emit(Notice(level='success', text='saved'))
            raise KeyboardInterrupt  # user hit Ctrl-C in the menu
    except KeyboardInterrupt:
        pass
    assert 'saved' in _out(console)


def test_nested_holds_flush_once_at_the_outermost_release():
    sink, console, _ = _sink()
    with sink.hold_output():
        with sink.hold_output():
            sink.emit(Notice(level='success', text='inner'))
        assert 'inner' not in _out(console)  # inner exit must NOT flush
    assert 'inner' in _out(console)


def _rendered(renderable, width: int) -> str:
    buf = StringIO()
    Console(file=buf, force_terminal=False, width=width, height=50).print(
        renderable)
    return buf.getvalue()


def test_unavailable_label_is_bold_and_the_rest_is_plain():
    sink, console, _ = _sink()
    captured = {}
    original = console.print

    def _spy(*args, **kwargs):
        captured['args'] = args
        return original(*args, **kwargs)

    console.print = _spy
    sink.emit(
        Notice(
            level='info',
            text=('API key: not required\n'
                  'UNAVAILABLE: Package `arxiv` is not installed.')))
    body = captured['args'][0].renderable
    assert body.plain.startswith('API key: not required')
    assert '[bold]' not in body.plain
    bold = [
        span for span in body.spans
        if getattr(span.style, 'bold', None) or span.style == 'bold'
    ]
    assert len(bold) == 1
    assert body.plain[bold[0].start:bold[0].end] == 'UNAVAILABLE'


def test_stream_window_is_only_the_last_screen():
    console = Console(file=StringIO(), force_terminal=True, width=10, height=5)
    sink = RichEventSink(console, TuiState())
    window = sink._stream_window('HEAD' + ('x' * 200) + 'TAIL')
    body = _rendered(window, 10).rstrip('\n')
    assert 'TAIL' in body
    assert 'HEAD' not in body
    assert len(body.split('\n')) <= 4  # height - 1


def test_live_refreshes_one_screen_then_typesets_once():
    """A tall reply must not be the Live renderable, and the title is printed
    once, after the refresh thread has been joined."""
    events = []

    class _Thread:
        def join(self, timeout=None):
            events.append('join')

    class _Live:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs
            self.updates = []
            self._refresh_thread = _Thread()
            events.append(('live', kwargs))

        def start(self):
            events.append('start')

        def update(self, renderable):
            self.updates.append(renderable)
            events.append(('update', renderable))

        def stop(self):
            events.append('stop')

    console = Console(file=StringIO(), force_terminal=True, width=10, height=5)
    sink = RichEventSink(console, TuiState())
    original = console.print

    def _spy(*args, **kwargs):
        events.append(('print', args[0] if args else None))
        return original(*args, **kwargs)

    console.print = _spy
    real = rich.live.Live
    rich.live.Live = _Live
    try:
        sink.emit(ContentDelta('HEAD' + ('y' * 200) + 'TAIL'))
        sink.emit(ContentEnd())
    finally:
        rich.live.Live = real

    live = next(item[1] for item in events if item[0] == 'live')
    assert live['vertical_overflow'] == 'crop'
    assert live['transient'] is True
    assert live['redirect_stdout'] is False
    assert live['redirect_stderr'] is False
    updated = next(item[1] for item in events if item[0] == 'update')
    shown = _rendered(updated, 10)
    assert 'TAIL' in shown and 'HEAD' not in shown
    assert events.index('stop') < events.index('join')
    markdown_at = next(
        i for i, item in enumerate(events)
        if item[0] == 'print' and isinstance(item[1], Markdown))
    assert events.index('join') < markdown_at
    titles = [
        item[1] for item in events
        if item[0] == 'print' and isinstance(item[1], str) and 'Assistant' in item[1]
    ]
    assert len(titles) == 1
    assert sink._live is None


def test_release_joins_refresh_thread_before_returning():
    import sys
    console = Console(file=StringIO(), force_terminal=True, width=20, height=8)
    sink = RichEventSink(console, TuiState())
    stdout = sys.stdout
    try:
        sink.emit(ContentDelta('partial reply'))
        live = sink._live
        thread = live._refresh_thread
        assert thread is not None and thread.is_alive()
        assert sys.stdout is stdout  # Live must not steal stdout
        sink.release_terminal()
        assert not thread.is_alive()
        assert sink._live is None
        assert sys.stdout is stdout
    finally:
        sink.release_terminal()
    out = _out(console)
    assert out.count('Assistant') == 1
    assert 'partial reply' in out
