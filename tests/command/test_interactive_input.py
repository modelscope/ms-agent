"""Tests for the unified interactive command layer.

`InteractiveSession.run_turn` owns the `>>>` read loop for both the initial
prompt and mid-conversation re-prompts: informational commands re-prompt,
`/quit` and EOF end the turn, and a plain line (or an unrecognized command)
is submitted as the task. `LLMAgent._resolve_interactive` decides when that
loop runs at all.
"""
import sys
import pytest
from unittest.mock import patch

from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.command import CommandRouter, register_builtin_commands
from ms_agent.command.interactive import InteractiveSession
from ms_agent.command.types import (
    CommandDef,
    CommandResult,
    CommandResultType,
)


def _make_session():
    router = CommandRouter()
    register_builtin_commands(router)
    return InteractiveSession(router)


class TestInteractiveSession:
    @pytest.mark.asyncio
    async def test_plain_prompt_submitted(self):
        session = _make_session()
        with patch('builtins.input', side_effect=['research quantum computing']):
            turn = await session.run_turn()
        assert turn.action == 'submit'
        assert turn.text == 'research quantum computing'

    @pytest.mark.asyncio
    async def test_info_command_then_prompt(self):
        # /help shows output and re-prompts; the next plain line is the task.
        session = _make_session()
        inputs = iter(['/help', 'do the task'])
        with patch('builtins.input', lambda *a: next(inputs)):
            turn = await session.run_turn()
        assert turn.action == 'submit'
        assert turn.text == 'do the task'

    @pytest.mark.asyncio
    async def test_quit(self):
        session = _make_session()
        with patch('builtins.input', side_effect=['/quit']):
            turn = await session.run_turn()
        assert turn.action == 'quit'

    @pytest.mark.asyncio
    async def test_empty_lines_skipped(self):
        session = _make_session()
        inputs = iter(['', '   ', 'real task'])
        with patch('builtins.input', lambda *a: next(inputs)):
            turn = await session.run_turn()
        assert turn.action == 'submit'
        assert turn.text == 'real task'

    @pytest.mark.asyncio
    async def test_eof_quits(self):
        session = _make_session()
        with patch('builtins.input', side_effect=EOFError):
            turn = await session.run_turn()
        assert turn.action == 'quit'

    @pytest.mark.asyncio
    async def test_unknown_command_treated_as_prompt(self):
        # An unregistered /foo is not a known command -> becomes the prompt.
        session = _make_session()
        with patch('builtins.input', side_effect=['/foo bar baz']):
            turn = await session.run_turn()
        assert turn.action == 'submit'
        assert turn.text == '/foo bar baz'

    @pytest.mark.asyncio
    async def test_root_path_treated_as_prompt(self):
        # /tmp is a filesystem path, not a command (router.is_command guard).
        session = _make_session()
        with patch('builtins.input', side_effect=['/tmp']):
            turn = await session.run_turn()
        assert turn.action == 'submit'
        assert turn.text == '/tmp'

    @pytest.mark.asyncio
    async def test_extra_messages_is_always_a_list(self):
        # The extra contract: messages is [] (never None) at the initial prompt.
        seen = {}

        async def spy(ctx):
            seen['messages'] = ctx.extra.get('messages')
            seen['router'] = ctx.extra.get('router')
            return CommandResult(type=CommandResultType.MESSAGE, content='ok')

        router = CommandRouter()
        router.register(CommandDef(name='spy', description='x'), spy)
        session = InteractiveSession(router)
        inputs = iter(['/spy', 'task'])
        with patch('builtins.input', lambda *a: next(inputs)):
            turn = await session.run_turn(messages=None)
        assert seen['messages'] == []
        assert seen['router'] is router
        assert turn.text == 'task'

    @pytest.mark.asyncio
    async def test_submit_prompt_command_returns_content(self):
        async def submit(ctx):
            return CommandResult(
                type=CommandResultType.SUBMIT_PROMPT, content='expanded prompt')

        router = CommandRouter()
        router.register(CommandDef(name='go', description='x'), submit)
        session = InteractiveSession(router)
        with patch('builtins.input', side_effect=['/go']):
            turn = await session.run_turn()
        assert turn.action == 'submit'
        assert turn.text == 'expanded prompt'


def _make_agent(config=None):
    """Build an LLMAgent without running its heavy __init__."""
    agent = LLMAgent.__new__(LLMAgent)
    agent.config = OmegaConf.create(config or {})
    return agent


class TestResolveInteractive:
    def test_interactive_when_no_task_and_tty(self):
        agent = _make_agent()
        with patch.object(sys.stdin, 'isatty', return_value=True):
            assert agent._resolve_interactive(None) is True

    def test_not_interactive_without_tty(self):
        # Piped / redirected stdin must never enter the blocking >>> loop.
        agent = _make_agent()
        with patch.object(sys.stdin, 'isatty', return_value=False):
            assert agent._resolve_interactive(None) is False

    def test_not_interactive_when_task_present(self):
        # SDK / sub-agent / workflow callers pass explicit messages.
        agent = _make_agent()
        with patch.object(sys.stdin, 'isatty', return_value=True):
            assert agent._resolve_interactive('a task') is False

    def test_configured_query_is_single_shot(self):
        agent = _make_agent({'prompt': {'query': 'preset task'}})
        with patch.object(sys.stdin, 'isatty', return_value=True):
            assert agent._resolve_interactive(None) is False

    def test_explicit_override_true(self):
        agent = _make_agent({'interactive': True})
        with patch.object(sys.stdin, 'isatty', return_value=False):
            assert agent._resolve_interactive('a task') is True

    def test_explicit_override_false(self):
        agent = _make_agent({'interactive': False})
        with patch.object(sys.stdin, 'isatty', return_value=True):
            assert agent._resolve_interactive(None) is False


def _make_callback_agent(config):
    agent = LLMAgent.__new__(LLMAgent)
    agent.config = OmegaConf.create(config)
    agent.callbacks = []
    agent.trust_remote_code = False
    agent._command_router = None
    return agent


class TestCallbackWiring:
    """InputCallback is gated by _interactive and shares the agent's router."""

    def _input_callbacks(self, agent):
        from ms_agent.callbacks.input_callback import InputCallback
        return [c for c in agent.callbacks if isinstance(c, InputCallback)]

    def test_interactive_injects_shared_router(self):
        agent = _make_callback_agent(
            {'callbacks': ['input_callback'], 'local_dir': '/tmp'})
        agent._interactive = True
        agent.register_callback_from_config()
        cbs = self._input_callbacks(agent)
        assert len(cbs) == 1
        # The callback drives the SAME router instance the agent owns.
        assert cbs[0]._session._router is agent._get_command_router()

    def test_non_interactive_skips_input_callback(self):
        # Listed but not interactive -> must not register (would block input()).
        agent = _make_callback_agent(
            {'callbacks': ['input_callback'], 'local_dir': '/tmp'})
        agent._interactive = False
        agent.register_callback_from_config()
        assert self._input_callbacks(agent) == []

    def test_interactive_auto_adds_when_not_listed(self):
        # Interactive session gets InputCallback even if config omits it.
        agent = _make_callback_agent({'callbacks': []})
        agent._interactive = True
        agent.register_callback_from_config()
        cbs = self._input_callbacks(agent)
        assert len(cbs) == 1
        assert cbs[0]._session._router is agent._get_command_router()
