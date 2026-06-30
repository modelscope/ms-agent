# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio

from omegaconf import OmegaConf

from ms_agent.agent.runtime import Runtime
from ms_agent.agent.templates.harness.round_reminder import \
    RoundReminderCallback
from ms_agent.agent.templates.harness.stop_gate import StopGateCallback
from ms_agent.llm.utils import Message


def _run(coro):
    return asyncio.run(coro)


def test_harness_self_registered():
    import ms_agent.agent.templates  # noqa: F401  (import triggers registration)
    from ms_agent.callbacks import callbacks_mapping
    assert 'round_reminder' in callbacks_mapping
    assert 'stop_gate' in callbacks_mapping


def test_round_reminder_triggers_then_dedups():
    cfg = OmegaConf.create({
        'max_chat_round': 30,
        'round_reminder': {
            'enabled': True,
            'remind_before_max_round': 2
        },
    })
    cb = RoundReminderCallback(cfg)
    msgs = []
    rt = Runtime(round=28)  # 30 - 2
    _run(cb.on_generate_response(rt, msgs))
    assert len(msgs) == 1
    assert '[ROUND_REMINDER]' in msgs[0].content
    # de-dup: a second call on the same round must not add another reminder
    _run(cb.on_generate_response(rt, msgs))
    assert len(msgs) == 1


def test_round_reminder_silent_off_threshold():
    cfg = OmegaConf.create({
        'max_chat_round': 30,
        'round_reminder': {
            'enabled': True,
            'remind_before_max_round': 2
        },
    })
    cb = RoundReminderCallback(cfg)
    msgs = []
    _run(cb.on_generate_response(Runtime(round=10), msgs))
    assert msgs == []


def test_round_reminder_disabled_by_default():
    cb = RoundReminderCallback(OmegaConf.create({'max_chat_round': 30}))
    msgs = []
    _run(cb.on_generate_response(Runtime(round=28), msgs))
    assert msgs == []


def test_stop_gate_blocks_stop_when_artifact_missing(tmp_path):
    cfg = OmegaConf.create({
        'output_dir': str(tmp_path),
        'stop_gate': {
            'enabled': True,
            'max_retries': 2,
            'checks': [{
                'type': 'artifact_exists',
                'path': 'report.md'
            }],
        },
    })
    cb = StopGateCallback(cfg)
    rt = Runtime(should_stop=True)
    msgs = [Message(role='assistant', content='done')]
    _run(cb.after_tool_call(rt, msgs))
    assert rt.should_stop is False        # gate blocked the stop
    assert len(msgs) == 2                  # reflection message injected


def test_stop_gate_allows_stop_when_artifact_present(tmp_path):
    (tmp_path / 'report.md').write_text('hello world')
    cfg = OmegaConf.create({
        'output_dir': str(tmp_path),
        'stop_gate': {
            'enabled': True,
            'checks': [{
                'type': 'artifact_exists',
                'path': 'report.md'
            }],
        },
    })
    cb = StopGateCallback(cfg)
    rt = Runtime(should_stop=True)
    msgs = [Message(role='assistant', content='done')]
    _run(cb.after_tool_call(rt, msgs))
    assert rt.should_stop is True          # gate let it stop


def test_stop_gate_respects_max_retries(tmp_path):
    cfg = OmegaConf.create({
        'output_dir': str(tmp_path),
        'stop_gate': {
            'enabled': True,
            'max_retries': 1,
            'checks': [{
                'type': 'artifact_exists',
                'path': 'nope.md'
            }],
        },
    })
    cb = StopGateCallback(cfg)
    rt1 = Runtime(should_stop=True)
    _run(cb.after_tool_call(rt1, [Message(role='assistant', content='x')]))
    assert rt1.should_stop is False        # blocked once
    rt2 = Runtime(should_stop=True)
    _run(cb.after_tool_call(rt2, [Message(role='assistant', content='x')]))
    assert rt2.should_stop is True         # retries exhausted -> allowed
