# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio

from omegaconf import OmegaConf

from ms_agent.agent.runtime import Runtime
from ms_agent.agent.templates.harness.loop_guard import LoopGuardCallback
from ms_agent.llm.utils import Message


def _run(c):
    return asyncio.run(c)


def _step(cb, rt, tc):
    """One round: assistant emits `tc`; run detect (on_tool_call) then
    inject (after_tool_call). Returns the round's messages."""
    msgs = [Message(role='assistant', tool_calls=[tc])]
    _run(cb.on_tool_call(rt, msgs))
    injected_before = len(msgs)
    _run(cb.after_tool_call(rt, msgs))
    return msgs, injected_before


def _tc(name, args):
    return {'tool_name': name, 'arguments': args}


def test_repeated_signature_warns_then_hard_stops():
    cb = LoopGuardCallback(
        OmegaConf.create({'loop_guard': {'warn': 3, 'hard': 5}}))
    rt = Runtime()
    tc = _tc('file_system---read_file', '{"path": "a.py"}')
    # rounds 1,2: nothing
    for _ in range(2):
        msgs, _ = _step(cb, rt, tc)
        assert len(msgs) == 1
    # round 3: warn injected (in after_tool_call, not before)
    msgs, before = _step(cb, rt, tc)
    assert before == 1                      # nothing added during on_tool_call
    assert any('[LOOP_GUARD]' in m.content for m in msgs if m.role == 'user')
    assert rt.should_stop is False
    # round 5: hard stop
    _step(cb, rt, tc)
    msgs, _ = _step(cb, rt, tc)
    assert rt.should_stop is True
    assert any('stopped' in m.content for m in msgs if m.role == 'user')


def test_distinct_calls_do_not_trip():
    cb = LoopGuardCallback(
        OmegaConf.create({'loop_guard': {'warn': 3, 'hard': 5}}))
    rt = Runtime()
    for i in range(6):
        msgs, _ = _step(cb, rt,
                        _tc('file_system---grep', '{"pattern": "x%d"}' % i))
        assert len(msgs) == 1            # all different -> no loop
    assert rt.should_stop is False


def test_read_file_line_bucketing_counts_as_repeat():
    cb = LoopGuardCallback(
        OmegaConf.create({'loop_guard': {'warn': 3, 'hard': 99}}))
    rt = Runtime()
    # same file, small line drift within the same 200-line bucket -> same sig
    for start in (0, 10, 20):
        msgs, _ = _step(
            cb, rt,
            _tc('file_system---read_file',
                '{"path": "a.py", "start": %d}' % start))
    assert any('[LOOP_GUARD]' in m.content for m in msgs if m.role == 'user')


def test_frequency_hard_stop():
    cb = LoopGuardCallback(
        OmegaConf.create({
            'loop_guard': {
                'warn': 99,
                'hard': 99,
                'freq_warn': 99,
                'freq_hard': 4
            }
        }))
    rt = Runtime()
    for i in range(4):
        msgs, _ = _step(cb, rt,
                        _tc('web_search---exa_search', '{"q": "x%d"}' % i))
    assert rt.should_stop is True


def test_disabled():
    cb = LoopGuardCallback(
        OmegaConf.create({'loop_guard': {'enabled': False}}))
    rt = Runtime()
    tc = _tc('file_system---read_file', '{"path": "a.py"}')
    for _ in range(10):
        msgs, _ = _step(cb, rt, tc)
    assert rt.should_stop is False
    assert all(len(m.content) == 0 or '[LOOP_GUARD]' not in m.content
               for m in msgs if m.role == 'user')
