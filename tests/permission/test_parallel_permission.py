# Copyright (c) ModelScope Contributors. All rights reserved.
"""Parallel tool calls (ToolManager.parallel_call_tool → asyncio.gather) reach
the permission handler concurrently. Whether that is safe is the handler's
property: a terminal-bound one deadlocks with N prompts fighting over one
stdin, so the enforcer serializes it; a handler that declares
``supports_concurrent_asks`` gets them all at once (a web UI renders each
pending ask as its own card)."""
import asyncio

import pytest

from ms_agent.permission.config import PermissionConfig
from ms_agent.permission.enforcer import PermissionEnforcer
from ms_agent.permission.handler import PermissionAction, PermissionResponse
from ms_agent.permission.memory import PermissionMemory


class _ConcurrencyProbe:
    def __init__(self):
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = 0

    async def ask(self, tool_name, tool_args, context, suggestions=None):
        self.in_flight += 1
        self.calls += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.02)  # simulate a human deciding
        self.in_flight -= 1
        return PermissionResponse(action=PermissionAction.ALLOW_ONCE)


@pytest.mark.asyncio
async def test_parallel_asks_are_serialized(tmp_path):
    cfg = PermissionConfig.from_dict({'mode': 'restricted'})  # empty wl -> ask
    handler = _ConcurrencyProbe()
    enf = PermissionEnforcer(
        config=cfg, handler=handler,
        memory=PermissionMemory(project_path=str(tmp_path)))

    # 5 concurrent checks, like 5 parallel tool calls in one round.
    results = await asyncio.gather(
        *[enf.check('some_tool', {'i': i}) for i in range(5)])

    assert all(r.action == 'allow' for r in results)
    assert handler.calls == 5
    # The decisive assertion: asks never overlapped (was 5 before the fix).
    assert handler.max_in_flight == 1


class _ConcurrentProbe(_ConcurrencyProbe):
    """Same probe, but declaring it can service several asks at once."""
    supports_concurrent_asks = True


@pytest.mark.asyncio
async def test_concurrent_handler_asks_overlap(tmp_path):
    """A handler that opts in sees the whole round's asks at once, instead of
    one-at-a-time behind whichever the user answers first."""
    cfg = PermissionConfig.from_dict({'mode': 'restricted'})
    handler = _ConcurrentProbe()
    enf = PermissionEnforcer(
        config=cfg, handler=handler,
        memory=PermissionMemory(project_path=str(tmp_path)))

    results = await asyncio.gather(
        *[enf.check('some_tool', {'i': i}) for i in range(5)])

    assert all(r.action == 'allow' for r in results)
    assert handler.calls == 5
    assert handler.max_in_flight == 5


class _AlwaysAllowOnce:
    """Serialized handler whose FIRST answer is allow_always; later asks should
    never reach it — memory now covers them."""

    def __init__(self):
        self.calls = 0

    async def ask(self, tool_name, tool_args, context, suggestions=None,
                  call_id=''):
        self.calls += 1
        await asyncio.sleep(0.01)
        return PermissionResponse(
            action=PermissionAction.ALLOW_ALWAYS, pattern=tool_name)


@pytest.mark.asyncio
async def test_queued_ask_skipped_once_memory_covers_it(tmp_path):
    """A serialized ask waiting its turn re-checks memory before prompting: the
    user already answered "always allow" for this exact pattern on the sibling
    ahead of it in the queue."""
    cfg = PermissionConfig.from_dict({'mode': 'restricted'})
    handler = _AlwaysAllowOnce()
    enf = PermissionEnforcer(
        config=cfg, handler=handler,
        memory=PermissionMemory(project_path=str(tmp_path)))

    results = await asyncio.gather(
        *[enf.check('some_tool', {'i': i}) for i in range(4)])

    assert all(r.action == 'allow' for r in results)
    assert handler.calls == 1  # the other three were covered by memory


class _CallIdCapture:
    """Handler that records the call_id it was asked with (and tolerates
    handlers that don't accept it — see enforcer._ask_user)."""
    def __init__(self):
        self.seen = []

    async def ask(self, tool_name, tool_args, context, suggestions=None,
                  call_id=''):
        self.seen.append(call_id)
        return PermissionResponse(action=PermissionAction.ALLOW_ONCE)


@pytest.mark.asyncio
async def test_call_id_threaded_to_handler(tmp_path):
    """enforcer.check(call_id=...) reaches handler.ask so a UI can correlate the
    decision to the exact tool_call (parallel identical calls)."""
    cfg = PermissionConfig.from_dict({'mode': 'restricted'})
    handler = _CallIdCapture()
    enf = PermissionEnforcer(
        config=cfg, handler=handler,
        memory=PermissionMemory(project_path=str(tmp_path)))

    await enf.check('some_tool', {'a': 1}, call_id='call-abc')
    assert handler.seen == ['call-abc']


@pytest.mark.asyncio
async def test_legacy_handler_without_call_id_still_works(tmp_path):
    """A handler whose ask() predates call_id (fixed signature) is not broken —
    the enforcer strips the unknown kwarg."""
    cfg = PermissionConfig.from_dict({'mode': 'restricted'})
    handler = _ConcurrencyProbe()  # ask() has no call_id param
    enf = PermissionEnforcer(
        config=cfg, handler=handler,
        memory=PermissionMemory(project_path=str(tmp_path)))

    r = await enf.check('some_tool', {'a': 1}, call_id='call-xyz')
    assert r.action == 'allow' and handler.calls == 1
