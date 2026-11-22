# Copyright (c) ModelScope Contributors. All rights reserved.
"""InputCallback steering: inject queued plain messages at a safe mid-turn
boundary without interrupting the run, and never break tool_calls pairing."""
import asyncio
from types import SimpleNamespace

from omegaconf import OmegaConf

from ms_agent.callbacks.input_callback import InputCallback
from ms_agent.command import CommandRouter, register_builtin_commands
from ms_agent.llm.utils import Message


class FakeSource:
    """Minimal input source exposing only the steering poll."""

    def __init__(self, lines=None, mode='steer'):
        self._lines = list(lines or [])
        self._mode = mode

    def poll_steering(self):
        if self._mode != 'steer':
            return []
        out, self._lines = self._lines, []
        return out


def _cb(source):
    router = CommandRouter()
    register_builtin_commands(router)
    return InputCallback(
        OmegaConf.create({}), command_router=router, input_source=source)


def test_steering_injects_user_message_and_keeps_turn_running():
    src = FakeSource(['please also check the tests'])
    cb = _cb(src)
    rt = SimpleNamespace(should_stop=False)
    # A tool result is the last message: the legal boundary to append a user
    # message (assistant.tool_calls → tool results are already paired).
    msgs = [
        Message(role='assistant', content='', tool_calls=[{'id': '1'}]),
        Message(role='tool', content='result'),
    ]
    asyncio.run(cb.after_tool_call(rt, msgs))
    assert msgs[-1].role == 'user'
    assert msgs[-1].content == 'please also check the tests'
    # The turn is NOT stopped — steering folds into the running loop.
    assert rt.should_stop is False


def test_no_steering_when_tool_calls_are_pending():
    src = FakeSource(['x'])
    cb = _cb(src)
    rt = SimpleNamespace(should_stop=False)
    # Last message is an assistant with unresolved tool_calls: injecting here
    # would break the tool_calls → tool pairing, so nothing is appended.
    msgs = [Message(role='assistant', content='', tool_calls=[{'id': '1'}])]
    asyncio.run(cb.after_tool_call(rt, msgs))
    assert len(msgs) == 1
    assert src._lines == ['x']  # left for a later, safe boundary


def test_steering_noop_without_poll_source():
    # CLI / WebUI sources have no poll_steering → behavior is unchanged.
    cb = _cb(None)
    rt = SimpleNamespace(should_stop=True)
    msgs = [Message(role='tool', content='r')]
    asyncio.run(cb.after_tool_call(rt, msgs))
    assert len(msgs) == 1
    assert rt.should_stop is True  # untouched


def test_no_steering_in_queue_mode():
    src = FakeSource(['x'], mode='queue')
    cb = _cb(src)
    rt = SimpleNamespace(should_stop=False)
    msgs = [Message(role='tool', content='r')]
    asyncio.run(cb.after_tool_call(rt, msgs))
    assert len(msgs) == 1
    assert src._lines == ['x']  # waits for idle delivery, not mid-turn


class FakeSink:
    """Records emitted events so the steered echo can be asserted."""

    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


def test_steering_emits_user_message_echo():
    """A folded-in user turn is published as UserMessage(steered=True) so a
    frontend can place it in the timeline. An idle prompt echoes itself inline;
    a mid-turn injection has no other on-screen representation, so without this
    the assistant appears to answer a message the user never sees recorded."""
    from ms_agent.ui.events import UserMessage
    src = FakeSource(['also check the docs'])
    sink = FakeSink()
    router = CommandRouter()
    register_builtin_commands(router)
    cb = InputCallback(
        OmegaConf.create({}),
        command_router=router,
        input_source=src,
        event_sink=sink)
    rt = SimpleNamespace(should_stop=False)
    msgs = [Message(role='tool', content='result')]
    asyncio.run(cb.after_tool_call(rt, msgs))
    echoes = [e for e in sink.events if isinstance(e, UserMessage)]
    assert len(echoes) == 1
    assert echoes[0].text == 'also check the docs'
    assert echoes[0].steered is True


def test_steering_echo_skipped_without_sink():
    """No event_sink (CLI / standalone) → injection still works; the echo is
    simply skipped, so a missing sink never breaks the turn."""
    src = FakeSource(['x'])
    cb = _cb(src)  # constructed without an event_sink
    rt = SimpleNamespace(should_stop=False)
    msgs = [Message(role='tool', content='r')]
    asyncio.run(cb.after_tool_call(rt, msgs))
    assert msgs[-1].role == 'user' and msgs[-1].content == 'x'
