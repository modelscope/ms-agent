# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio

from omegaconf import OmegaConf

from ms_agent.agent.runtime import Runtime
from ms_agent.agent.templates.harness.subagent_limit import \
    SubagentLimitCallback
from ms_agent.llm.utils import Message


def _run(c):
    return asyncio.run(c)


def _deleg(i):
    return {'tool_name': f'agent_tools---research', 'arguments': '{"i": %d}' % i}


def test_truncates_excess_delegations():
    cb = SubagentLimitCallback(
        OmegaConf.create({'subagent_limit': {'max_parallel': 4}}))
    rt = Runtime()
    calls = [_deleg(i) for i in range(6)] + [{
        'tool_name': 'file_system---grep',
        'arguments': '{}'
    }]
    msgs = [Message(role='assistant', tool_calls=calls)]
    _run(cb.on_tool_call(rt, msgs))
    deleg = [tc for tc in msgs[0].tool_calls
             if tc['tool_name'].startswith('agent_tools---')]
    other = [tc for tc in msgs[0].tool_calls
             if not tc['tool_name'].startswith('agent_tools---')]
    assert len(deleg) == 4              # capped
    assert len(other) == 1              # non-delegation kept
    _run(cb.after_tool_call(rt, msgs))
    assert any('[SUBAGENT_LIMIT]' in m.content for m in msgs
               if m.role == 'user')


def test_under_limit_untouched():
    cb = SubagentLimitCallback(
        OmegaConf.create({'subagent_limit': {'max_parallel': 4}}))
    rt = Runtime()
    msgs = [Message(role='assistant', tool_calls=[_deleg(0), _deleg(1)])]
    _run(cb.on_tool_call(rt, msgs))
    assert len(msgs[0].tool_calls) == 2
    _run(cb.after_tool_call(rt, msgs))
    assert len(msgs) == 1               # no note injected


def test_non_delegation_unaffected():
    cb = SubagentLimitCallback(
        OmegaConf.create({'subagent_limit': {'max_parallel': 1}}))
    rt = Runtime()
    calls = [{'tool_name': 'file_system---grep', 'arguments': '{}'}
             for _ in range(5)]
    msgs = [Message(role='assistant', tool_calls=calls)]
    _run(cb.on_tool_call(rt, msgs))
    assert len(msgs[0].tool_calls) == 5     # non-delegation never capped
