# Copyright (c) ModelScope Contributors. All rights reserved.
"""RichEventSink: renders the AgentEvent stream and tracks status state."""
from io import StringIO

from rich.console import Console

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
    assert 'Hello world' in _out(console)


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
