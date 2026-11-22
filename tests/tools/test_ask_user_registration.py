# Copyright (c) ModelScope Contributors. All rights reserved.
"""用户提问能力及其回归测试。"""
import asyncio
import os
import sys

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from ms_agent.agent.llm_agent import LLMAgent  # noqa: F401 — breaks a cycle

from ms_agent.tools.ask_user_tool import AskUserTool
from ms_agent.tools.base import SELF_MANAGED_TIMEOUT, ToolBase
from ms_agent.tools.tool_manager import ToolManager
from ms_agent.ui.interaction import AnswerStatus, QuestionReply
from omegaconf import OmegaConf


class _CanAsk:
    supports_questions = True

    async def ask(self, questions, call_id=''):
        return QuestionReply(status=AnswerStatus.SKIPPED, note='skipped')


class _CannotAsk:
    supports_questions = False

    async def ask(self, questions, call_id=''):  # pragma: no cover
        raise AssertionError('must not be consulted')


def _manager(question_handler, ask_user_cfg={'mcp': False}):
    tools = {}
    if ask_user_cfg is not None:
        tools['ask_user'] = ask_user_cfg
    config = OmegaConf.create({'tools': tools})
    return ToolManager(config, question_handler=question_handler)


def _has_ask_tool(manager):
    return any(isinstance(t, AskUserTool) for t in manager.extra_tools)


# ── registration ──────────────────────────────────────────────────────────


def test_the_tool_exists_only_where_a_person_can_be_reached():
    assert _has_ask_tool(_manager(_CanAsk())) is True


def test_no_channel_means_the_model_never_sees_the_tool():
    """Stronger than failing the call on purpose: a tool the model cannot see
    costs no round trip to discover, and an agent that cannot ask has to
    decide — which is what a headless run wants anyway."""
    assert _has_ask_tool(_manager(_CannotAsk())) is False
    assert _has_ask_tool(_manager(None)) is False


def test_config_can_withhold_it_even_where_asking_is_possible():
    assert _has_ask_tool(
        _manager(_CanAsk(), ask_user_cfg={
            'mcp': False,
            'enabled': False
        })) is False
    # Absent from `tools` entirely — the ordinary opt-out.
    assert _has_ask_tool(_manager(_CanAsk(), ask_user_cfg=None)) is False


def test_the_handler_is_handed_to_the_tool_that_needs_it():
    manager = _manager(_CanAsk())
    tool = next(t for t in manager.extra_tools if isinstance(t, AskUserTool))
    assert tool._handler is manager._question_handler


# ── the generic wait ──────────────────────────────────────────────────────


class _SlowSelfManaged(ToolBase):
    """Takes longer than any generic budget, and says it owns its own."""

    SERVER_NAME = 'slow'

    def __init__(self, config, delay):
        super().__init__(config)
        self._delay = delay
        self.finished = False

    @property
    def call_timeout(self):
        return SELF_MANAGED_TIMEOUT

    async def connect(self):
        pass

    async def _get_tools_inner(self):
        return {}

    async def call_tool(self, server_name, *, tool_name, tool_args):
        await asyncio.sleep(self._delay)
        self.finished = True
        return 'done waiting'


class _SlowOrdinary(_SlowSelfManaged):
    """The same tool without the declaration — the control case."""

    @property
    def call_timeout(self):
        return None


def _run_one(tool_cls, delay, timeout):
    """Drive one call of a fake tool through single_call_tool."""
    config = OmegaConf.create({'tools': {}, 'tool_call_timeout': timeout})
    manager = ToolManager(config)
    tool = tool_cls(config, delay)
    manager._tool_index = {'slow---go': (tool, 'slow', {})}
    result = asyncio.run(
        manager.single_call_tool({
            'tool_name': 'slow---go',
            'arguments': {},
            'id': 'call-1',
        }))
    return tool, result


def test_a_self_managed_tool_is_not_cut_off_by_the_generic_budget():
    tool, result = _run_one(_SlowSelfManaged, delay=1.1, timeout=1)
    # Its own timeout would have expired several times over.
    assert tool.finished is True
    assert result == 'done waiting'


def test_an_ordinary_tool_still_obeys_the_budget():
    """The exemption must be opt-in; nothing else may drift into it."""
    tool, result = _run_one(_SlowOrdinary, delay=5, timeout=1)
    assert tool.finished is False
    assert isinstance(result, dict) and result['is_error'] is True
    assert 'timed out' in result['result']


def test_subagent_cannot_use_an_injected_question_handler():
    agent = LLMAgent.__new__(LLMAgent)
    agent.config = OmegaConf.create({'ms_agent_subagent': True})
    agent._question_handler = _CanAsk()
    assert agent._select_question_handler().supports_questions is False


def test_subagent_config_removes_the_question_tool():
    from types import SimpleNamespace
    from ms_agent.tools.agent_tool import _withhold_ask_user
    agent = SimpleNamespace(config=OmegaConf.create({
        'tools': {'ask_user': {'mcp': False}, 'file_system': {'mcp': False}}}))
    _withhold_ask_user(agent)
    assert 'ask_user' not in agent.config.tools
    assert 'file_system' in agent.config.tools
