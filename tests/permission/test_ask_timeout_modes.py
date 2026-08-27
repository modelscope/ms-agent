"""How long an approval waits, and what happens when it does not arrive.

Expiring an approval answers it as a refusal — an answer the user never gave.
So the wait is unbounded wherever a person intends to answer, and the message
on the bounded path says plainly that nobody refused anything.
"""
import asyncio

import pytest

from ms_agent.permission.handler import (PermissionAction, PermissionResponse,
                                         WebPermissionHandler)


class _Emitter:

    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


@pytest.mark.asyncio
async def test_default_wait_is_unbounded():
    handler = WebPermissionHandler(_Emitter())
    assert handler._timeout is None

    task = asyncio.create_task(handler.ask('tool', {}, '', call_id='c1'))
    await asyncio.sleep(0.05)
    assert not task.done(), 'an unbounded ask must not resolve itself'

    request_id = handler._event_emitter.events[0]['request_id']
    handler.resolve(request_id,
                    PermissionResponse(action=PermissionAction.ALLOW_ONCE))
    assert (await task).action is PermissionAction.ALLOW_ONCE


@pytest.mark.asyncio
async def test_bounded_wait_denies_but_says_it_was_a_timeout():
    handler = WebPermissionHandler(_Emitter(), timeout=0.05)
    response = await handler.ask('tool', {}, '', call_id='c1')

    assert response.action is PermissionAction.DENY
    # The model has to be able to tell these apart: a refusal is a decision to
    # work around, a timeout is nobody having looked.
    assert 'TIMEOUT' in response.feedback
    assert 'not a refusal' in response.feedback
    assert 'Do not re-request' in response.feedback


@pytest.mark.asyncio
async def test_pending_asks_are_answered_when_the_session_closes():
    """An unbounded ask holds its turn open; an abandoned prompt would pin its
    session for the life of the process unless something answers it."""
    handler = WebPermissionHandler(_Emitter())
    first = asyncio.create_task(handler.ask('a', {}, '', call_id='c1'))
    second = asyncio.create_task(handler.ask('b', {}, '', call_id='c2'))
    await asyncio.sleep(0.05)

    assert handler.cancel_pending('Session closed') == 2
    assert handler.cancel_pending() == 0  # idempotent

    for task in (first, second):
        response = await task
        assert response.action is PermissionAction.DENY
        assert response.feedback == 'Session closed'
    assert handler._pending == {}


@pytest.mark.asyncio
async def test_answering_one_card_releases_the_ones_it_covers():
    """"Always allow" is a statement about a pattern; a sibling card the
    pattern covers must not be left holding the turn open indefinitely."""
    from ms_agent.permission.config import PermissionConfig
    from ms_agent.permission.enforcer import PermissionEnforcer

    emitter = _Emitter()
    handler = WebPermissionHandler(emitter)
    enforcer = PermissionEnforcer(
        config=PermissionConfig(mode='interactive'), handler=handler)
    tool = 'code_executor---shell_executor'

    calls = [
        asyncio.create_task(
            enforcer.check(tool, {'command': f'git status {i}'}))
        for i in range(3)
    ]
    await asyncio.sleep(0.05)
    assert len(handler._pending) == 3

    handler.resolve(
        emitter.events[0]['request_id'],
        PermissionResponse(
            action=PermissionAction.ALLOW_ALWAYS, pattern=f'{tool}:git *'))
    await asyncio.sleep(0.05)

    assert all(c.done() for c in calls), 'siblings left waiting'
    assert handler._pending == {}
    decisions = await asyncio.gather(*calls)
    assert [d.action for d in decisions] == ['allow'] * 3


@pytest.mark.asyncio
async def test_a_remembered_answer_never_releases_a_safety_confirmation():
    """The forced path exists so a remembered answer cannot stand in for
    looking at this particular call. Releasing siblings must not create a way
    around it."""
    from ms_agent.permission.config import PermissionConfig
    from ms_agent.permission.enforcer import (PermissionDecision,
                                              PermissionEnforcer)

    emitter = _Emitter()
    handler = WebPermissionHandler(emitter)
    enforcer = PermissionEnforcer(
        config=PermissionConfig(mode='interactive'), handler=handler)
    tool = 'code_executor---shell_executor'
    forced = PermissionDecision(action='ask', reason='reads outside workspace')

    calls = [
        asyncio.create_task(
            enforcer.check(
                tool, {'command': f'cat /etc/hosts {i}'},
                force_decision=forced)) for i in range(3)
    ]
    await asyncio.sleep(0.05)

    handler.resolve(
        emitter.events[0]['request_id'],
        PermissionResponse(
            action=PermissionAction.ALLOW_ALWAYS, pattern=f'{tool}:cat *'))
    await asyncio.sleep(0.05)

    assert sum(c.done() for c in calls) == 1, 'a safety ask was auto-released'
    assert len(handler._pending) == 2
    for call in calls:
        if not call.done():
            call.cancel()
    await asyncio.gather(*calls, return_exceptions=True)
