"""The adapter owns one operation and delegates all compaction to the SDK."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from app.backends.errors import Conflict
from app.backends.ms_agent import context


@pytest.mark.asyncio
async def test_manual_compaction_ownership_cancel_and_completion(monkeypatch):
    ready = asyncio.Event()
    ready.set()
    entered = asyncio.Event()
    release = asyncio.Event()
    async def compact(**kwargs):
        assert kwargs == {'force': True, 'trigger': 'manual'}
        entered.set()
        await release.wait()
        return {'status': 'completed', 'messages': []}
    driver = asyncio.create_task(asyncio.Event().wait())
    rt = NS(turn_lock=asyncio.Lock(), run_task=driver,
            input_source=NS(waiting=ready), agent=NS(
                compact_context=compact, condense_memory=AsyncMock(return_value=[]),
                update_context_snapshot=AsyncMock()), needs_rebuild=False)
    monkeypatch.setattr(context, 'find_session', lambda sid: (None, None, None))
    monkeypatch.setattr(context.registry, 'is_running', lambda sid: False)
    monkeypatch.setattr(context.registry, 'get', AsyncMock(return_value=rt))
    try:
        assert (await context.start('sid'))['status'] == 'running'
        await asyncio.wait_for(entered.wait(), 1)
        with pytest.raises(Conflict):
            await context.start('sid')
        rt.context_task.cancel()
        await asyncio.gather(rt.context_task, return_exceptions=True)
        assert rt.context_state['status'] == 'cancelled'
        assert rt.needs_rebuild and not rt.turn_lock.locked()
        rt.agent.update_context_snapshot.assert_not_called()
        release.set()
        await context.start('sid')
        await rt.context_task
        assert rt.context_state['status'] == 'completed'
        rt.agent.update_context_snapshot.assert_awaited_once_with([])
        assert not rt.turn_lock.locked()
    finally:
        driver.cancel()
        await asyncio.gather(driver, return_exceptions=True)
