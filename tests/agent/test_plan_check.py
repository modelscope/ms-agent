# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import json

from omegaconf import OmegaConf

from ms_agent.agent.runtime import Runtime
from ms_agent.agent.templates.harness import plan_check as plan_check_mod
from ms_agent.agent.templates.harness.plan_check import PlanCheckCallback
from ms_agent.llm.utils import Message


def _run(c):
    return asyncio.run(c)


class _FakeChecker:
    """Stand-in for LLMQualityChecker: returns a preset verdict, no network."""
    verdict = None

    def __init__(self, *a, **k):
        pass

    def check(self, content):
        return _FakeChecker.verdict


def _cfg(tmp_path):
    return OmegaConf.create({
        'output_dir': str(tmp_path),
        'llm': {'model': 'fake', 'openai_api_key': 'k', 'openai_base_url': 'u'},
    })


def _plan(tmp_path):
    (tmp_path / 'plan.json').write_text(
        json.dumps({'todos': [{'content': 'step 1', 'status': 'pending'}]}),
        encoding='utf-8')


def _todo_write_msgs():
    return [
        Message(role='user', content='Add subtraction to the calculator'),
        Message(role='assistant',
                tool_calls=[{'tool_name': 'todo_list---todo_write',
                             'arguments': '{}'}]),
        Message(role='tool', content='ok'),
    ]


def test_injects_feedback_when_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_check_mod, 'LLMQualityChecker', _FakeChecker)
    _FakeChecker.verdict = 'missing the division requirement'
    _plan(tmp_path)
    cb = PlanCheckCallback(_cfg(tmp_path))
    msgs = _todo_write_msgs()
    _run(cb.on_task_begin(Runtime(), msgs))
    _run(cb.after_tool_call(Runtime(), msgs))
    assert any('[PLAN_CHECK]' in m.content for m in msgs if m.role == 'user'
               and 'missing the division' in m.content)


def test_no_feedback_when_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_check_mod, 'LLMQualityChecker', _FakeChecker)
    _FakeChecker.verdict = None      # plan judged complete
    _plan(tmp_path)
    cb = PlanCheckCallback(_cfg(tmp_path))
    msgs = _todo_write_msgs()
    _run(cb.on_task_begin(Runtime(), msgs))
    _run(cb.after_tool_call(Runtime(), msgs))
    assert not any('[PLAN_CHECK]' in m.content for m in msgs
                   if m.role == 'user')


def test_ignores_non_plan_tool_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_check_mod, 'LLMQualityChecker', _FakeChecker)
    _FakeChecker.verdict = 'should not be called'
    _plan(tmp_path)
    cb = PlanCheckCallback(_cfg(tmp_path))
    msgs = [
        Message(role='user', content='find X'),
        Message(role='assistant',
                tool_calls=[{'tool_name': 'file_system---grep',
                             'arguments': '{}'}]),
        Message(role='tool', content='ok'),
    ]
    _run(cb.on_task_begin(Runtime(), msgs))
    _run(cb.after_tool_call(Runtime(), msgs))
    assert not any('[PLAN_CHECK]' in m.content for m in msgs
                   if m.role == 'user')


def test_only_first_plan_creation_is_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_check_mod, 'LLMQualityChecker', _FakeChecker)
    _FakeChecker.verdict = 'gap'
    _plan(tmp_path)
    cb = PlanCheckCallback(_cfg(tmp_path))
    msgs = _todo_write_msgs()
    _run(cb.on_task_begin(Runtime(), msgs))
    _run(cb.after_tool_call(Runtime(), msgs))
    first = sum(1 for m in msgs if m.role == 'user' and '[PLAN_CHECK]' in m.content)
    # a second plan write should NOT trigger another check
    msgs2 = _todo_write_msgs()
    _run(cb.after_tool_call(Runtime(), msgs2))
    second = sum(1 for m in msgs2 if m.role == 'user' and '[PLAN_CHECK]' in m.content)
    assert first == 1 and second == 0
