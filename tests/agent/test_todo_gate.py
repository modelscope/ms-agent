# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import json

from omegaconf import OmegaConf

from ms_agent.agent.runtime import Runtime
from ms_agent.agent.templates.harness.todo_gate import TodoGateCallback
from ms_agent.llm.utils import Message


def _run(c):
    return asyncio.run(c)


def _write_plan(tmp_path, todos):
    (tmp_path / 'plan.json').write_text(
        json.dumps({'todos': todos}), encoding='utf-8')


def test_blocks_stop_when_incomplete(tmp_path):
    _write_plan(tmp_path, [
        {'id': '1', 'content': 'a', 'status': 'completed'},
        {'id': '2', 'content': 'b', 'status': 'in_progress'},
    ])
    cb = TodoGateCallback(OmegaConf.create({'output_dir': str(tmp_path)}))
    rt = Runtime(should_stop=True)
    msgs = [Message(role='assistant', content='done')]
    _run(cb.after_tool_call(rt, msgs))
    assert rt.should_stop is False
    assert any('[TODO_GATE]' in m.content for m in msgs if m.role == 'user')


def test_allows_stop_when_all_done(tmp_path):
    _write_plan(tmp_path, [
        {'id': '1', 'content': 'a', 'status': 'completed'},
        {'id': '2', 'content': 'b', 'status': 'cancelled'},
    ])
    cb = TodoGateCallback(OmegaConf.create({'output_dir': str(tmp_path)}))
    rt = Runtime(should_stop=True)
    _run(cb.after_tool_call(rt, [Message(role='assistant', content='done')]))
    assert rt.should_stop is True


def test_no_plan_file_allows_stop(tmp_path):
    cb = TodoGateCallback(OmegaConf.create({'output_dir': str(tmp_path)}))
    rt = Runtime(should_stop=True)
    _run(cb.after_tool_call(rt, [Message(role='assistant', content='done')]))
    assert rt.should_stop is True


def test_respects_max_reminders(tmp_path):
    _write_plan(tmp_path,
                [{'id': '1', 'content': 'a', 'status': 'pending'}])
    cb = TodoGateCallback(
        OmegaConf.create({'output_dir': str(tmp_path),
                          'todo_gate': {'max_reminders': 1}}))
    rt1 = Runtime(should_stop=True)
    _run(cb.after_tool_call(rt1, [Message(role='assistant', content='x')]))
    assert rt1.should_stop is False              # blocked once
    rt2 = Runtime(should_stop=True)
    _run(cb.after_tool_call(rt2, [Message(role='assistant', content='x')]))
    assert rt2.should_stop is True               # budget spent -> allowed
