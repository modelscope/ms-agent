# Copyright (c) ModelScope Contributors. All rights reserved.
"""LLMAgent output seam: emit helpers route to the event sink or stdout.

Pins the seam contract: with an event sink the agent emits semantic
AgentEvents; with no sink the code path is byte-identical to the pre-change
stdout behavior (CLI zero-regression).
"""
from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.ui.events import (ContentDelta, ContentEnd, ReasoningDelta,
                                ReasoningEnded, ReasoningStarted, RecordingSink)


def _agent(event_sink=None, reasoning_output='stdout'):
    """Partially construct an agent (bypass __init__) with just the seam deps."""
    a = LLMAgent.__new__(LLMAgent)
    a._event_sink = event_sink
    a.config = OmegaConf.create(
        {'generation_config': {'reasoning_output': reasoning_output}})
    return a


# ── sink path: structured events ──────────────────────────────────────────


def test_sink_receives_content_events():
    sink = RecordingSink()
    a = _agent(event_sink=sink)
    a._emit_content('hel')
    a._emit_content('lo')
    a._emit_content_end()
    assert sink.events == [ContentDelta('hel'), ContentDelta('lo'), ContentEnd()]


def test_sink_receives_reasoning_events():
    sink = RecordingSink()
    a = _agent(event_sink=sink)
    a._emit_reasoning_start()
    a._emit_reasoning_delta('thinking...')
    a._emit_reasoning_end()
    assert sink.events == [
        ReasoningStarted(), ReasoningDelta('thinking...'), ReasoningEnded()]


# ── no-sink path: byte-identical to current CLI behavior ──────────────────


def test_no_sink_content_goes_to_stdout(capsys):
    a = _agent()  # no sink -> stdout
    a._emit_content('hello')
    a._emit_content_end()
    assert capsys.readouterr().out == 'hello\n'  # exact legacy output


def test_no_sink_reasoning_goes_to_stdout(capsys):
    a = _agent(reasoning_output='stdout')
    a._emit_reasoning_start()
    a._emit_reasoning_delta('mulling')
    a._emit_reasoning_end()
    out = capsys.readouterr().out
    assert 'thinking' in out and 'mulling' in out
