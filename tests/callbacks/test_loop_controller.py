"""Tests for the in-session /loop controller.

The controller rides the same after_tool_call fork as InputCallback: at the
"would stop" point it either re-injects the next iteration (append a user
message + clear should_stop) or trips a guardrail and lets the loop end.
"""
import time

import pytest
from omegaconf import OmegaConf

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks.loop_controller import (
    MAX_DELAY,
    MIN_DELAY,
    NO_PROGRESS_LIMIT,
    SELF_PACED_SUFFIX,
    LoopController,
)
from ms_agent.command.router import CommandRouter
from ms_agent.command.types import CommandDef, CommandResult, CommandResultType
from ms_agent.llm.utils import Message


def _controller(router=None):
    ctrl = LoopController(OmegaConf.create({}), command_router=router)

    async def _no_sleep(delay):
        return None

    # Avoid real wall-clock waits in tests.
    ctrl._sleep = _no_sleep
    return ctrl


def _final(content='answer'):
    return [Message(role='assistant', content=content)]


def _interval_runtime(**over):
    r = Runtime()
    r.loop_active = True
    r.loop_mode = 'interval'
    r.loop_prompt = 'check ci'
    r.loop_interval = 300
    r.loop_max = 50
    r.loop_deadline = time.time() + 3600
    for k, v in over.items():
        setattr(r, k, v)
    return r


class TestReinjection:
    @pytest.mark.asyncio
    async def test_interval_reinjects_and_continues(self):
        ctrl = _controller()
        rt = _interval_runtime()
        msgs = _final('round 1 done')
        await ctrl.after_tool_call(rt, msgs)
        assert rt.loop_active is True
        assert rt.loop_iteration == 1
        assert rt.should_stop is False
        assert msgs[-1].role == 'user'
        assert msgs[-1].content == 'check ci'

    @pytest.mark.asyncio
    async def test_noop_when_not_active(self):
        ctrl = _controller()
        rt = _interval_runtime(loop_active=False)
        msgs = _final()
        await ctrl.after_tool_call(rt, msgs)
        assert len(msgs) == 1
        assert rt.loop_iteration == 0

    @pytest.mark.asyncio
    async def test_noop_when_last_is_user(self):
        # Mid tool-call / pending user turn: the fork hasn't been reached.
        ctrl = _controller()
        rt = _interval_runtime()
        msgs = [Message(role='user', content='hi')]
        await ctrl.after_tool_call(rt, msgs)
        assert len(msgs) == 1
        assert rt.loop_iteration == 0

    @pytest.mark.asyncio
    async def test_noop_when_pending_tool_calls(self):
        ctrl = _controller()
        rt = _interval_runtime()
        msg = Message(role='assistant', content='calling')
        msg.tool_calls = [object()]
        msgs = [msg]
        await ctrl.after_tool_call(rt, msgs)
        assert len(msgs) == 1
        assert rt.loop_iteration == 0

    @pytest.mark.asyncio
    async def test_slash_body_expanded_each_iteration(self):
        router = CommandRouter()

        async def go(ctx):
            return CommandResult(
                type=CommandResultType.SUBMIT_PROMPT, content='EXPANDED')

        router.register(CommandDef(name='go', description='x'), go)
        ctrl = _controller(router=router)
        rt = _interval_runtime(loop_prompt='/go')
        msgs = _final()
        await ctrl.after_tool_call(rt, msgs)
        assert msgs[-1].content == 'EXPANDED'


class TestGuardrails:
    @pytest.mark.asyncio
    async def test_max_iterations_stops(self):
        ctrl = _controller()
        rt = _interval_runtime(loop_iteration=50, loop_max=50)
        msgs = _final()
        await ctrl.after_tool_call(rt, msgs)
        assert rt.loop_active is False
        assert len(msgs) == 1  # no re-injection

    @pytest.mark.asyncio
    async def test_deadline_stops(self):
        ctrl = _controller()
        rt = _interval_runtime(loop_deadline=time.time() - 1)
        msgs = _final()
        await ctrl.after_tool_call(rt, msgs)
        assert rt.loop_active is False
        assert len(msgs) == 1

    @pytest.mark.asyncio
    async def test_token_budget_stops(self, monkeypatch):
        from ms_agent.agent.llm_agent import LLMAgent
        monkeypatch.setattr(LLMAgent, 'TOTAL_PROMPT_TOKENS', 1000)
        monkeypatch.setattr(LLMAgent, 'TOTAL_COMPLETION_TOKENS', 0)
        ctrl = _controller()
        rt = _interval_runtime(loop_token_budget=500, loop_token_start=0)
        msgs = _final()
        await ctrl.after_tool_call(rt, msgs)
        assert rt.loop_active is False
        assert len(msgs) == 1

    @pytest.mark.asyncio
    async def test_no_progress_stops(self):
        ctrl = _controller()
        rt = _interval_runtime(loop_max=999)
        # Identical final answers trip the no-progress breaker.
        for _ in range(NO_PROGRESS_LIMIT):
            assert rt.loop_active is True
            await ctrl.after_tool_call(rt, _final('same'))
        assert rt.loop_active is False


class TestSelfPaced:
    @pytest.mark.asyncio
    async def test_schedule_wakeup_sets_delay_and_continues(self):
        ctrl = _controller()
        rt = _interval_runtime(loop_mode='self_paced', loop_prompt='watch ci')
        # Model called schedule_wakeup during the turn.
        recorded = ctrl.request_wakeup(120, 'build in progress')
        assert recorded == 120
        msgs = _final()
        await ctrl.after_tool_call(rt, msgs)
        assert rt.loop_iteration == 1
        assert msgs[-1].role == 'user'
        assert msgs[-1].content.startswith('watch ci')
        # Self-paced iterations carry the schedule_wakeup guidance.
        assert SELF_PACED_SUFFIX.strip()[:20] in msgs[-1].content

    @pytest.mark.asyncio
    async def test_no_wakeup_ends_loop(self):
        ctrl = _controller()
        rt = _interval_runtime(loop_mode='self_paced', loop_prompt='watch ci')
        ctrl.start_iteration_window()  # no schedule_wakeup this turn
        msgs = _final()
        await ctrl.after_tool_call(rt, msgs)
        assert rt.loop_active is False
        assert len(msgs) == 1

    @pytest.mark.asyncio
    async def test_delay_is_clamped(self):
        ctrl = _controller()
        assert ctrl.request_wakeup(5, 'too short') == MIN_DELAY
        assert ctrl.request_wakeup(999999, 'too long') == MAX_DELAY

    @pytest.mark.asyncio
    async def test_window_reset_after_iteration(self):
        # After one self-paced iteration the wakeup signal is cleared, so the
        # next turn must call schedule_wakeup again or the loop ends.
        ctrl = _controller()
        rt = _interval_runtime(loop_mode='self_paced', loop_prompt='watch')
        ctrl.request_wakeup(120, 'go')
        await ctrl.after_tool_call(rt, _final('a'))
        assert rt.loop_active is True
        # No new wakeup -> loop ends on the next fork.
        await ctrl.after_tool_call(rt, _final('b'))
        assert rt.loop_active is False


def _wiring_agent(config):
    from ms_agent.agent.llm_agent import LLMAgent
    agent = LLMAgent.__new__(LLMAgent)
    agent.config = OmegaConf.create(config)
    agent.callbacks = []
    agent.trust_remote_code = False
    agent._command_router = None
    agent._plugin_runtime = None
    agent._event_sink = None
    agent._input_source = None
    agent._loop_controller = None
    return agent


class TestRegistration:
    """LoopController must sit before InputCallback so its re-injection wins."""

    def test_registered_before_input_callback(self):
        agent = _wiring_agent(
            {'callbacks': ['input_callback'], 'local_dir': '/tmp'})
        agent._interactive = True
        agent.register_callback_from_config()
        names = [type(c).__name__ for c in agent.callbacks]
        assert 'LoopController' in names
        assert 'InputCallback' in names
        assert names.index('LoopController') < names.index('InputCallback')
        assert agent._loop_controller is agent.callbacks[0]

    def test_auto_added_even_when_not_listed(self):
        agent = _wiring_agent({'callbacks': []})
        agent._interactive = True
        agent.register_callback_from_config()
        names = [type(c).__name__ for c in agent.callbacks]
        assert 'LoopController' in names

    def test_absent_when_not_interactive(self):
        agent = _wiring_agent({'callbacks': []})
        agent._interactive = False
        agent.register_callback_from_config()
        names = [type(c).__name__ for c in agent.callbacks]
        assert 'LoopController' not in names
        assert agent._loop_controller is None

    def test_idempotent_across_calls(self):
        # TUI route-A calls run_loop (and this) once per session; the
        # controller must not be duplicated on re-registration.
        agent = _wiring_agent(
            {'callbacks': ['input_callback'], 'local_dir': '/tmp'})
        agent._interactive = True
        agent.register_callback_from_config()
        agent.register_callback_from_config()
        loops = [c for c in agent.callbacks
                 if type(c).__name__ == 'LoopController']
        assert len(loops) == 1
