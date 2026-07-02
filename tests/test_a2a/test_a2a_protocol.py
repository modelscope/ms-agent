"""Protocol-level tests for A2A components.

Tests the full A2A protocol flow using mock agents and the A2A SDK types.
Skipped if a2a-sdk is not installed.
"""

from __future__ import annotations

import asyncio
import io
import sys
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from ms_agent.llm.utils import Message

_SKIP_REASON = None
try:
    from a2a.types import (
        AgentCapabilities,
        AgentCard,
        AgentSkill,
        Part,
        TaskState,
        TextPart,
    )
    from a2a.server.agent_execution import AgentExecutor, RequestContext
    from a2a.server.events import EventQueue
    from a2a.server.tasks import TaskUpdater, InMemoryTaskStore
    from a2a.utils import new_agent_text_message, new_task
except ImportError:
    _SKIP_REASON = 'a2a-sdk not installed'


pytestmark = pytest.mark.skipif(
    _SKIP_REASON is not None, reason=_SKIP_REASON or '')


# ======================================================================
# Agent Card tests
# ======================================================================

class TestAgentCard:

    def test_build_agent_card_defaults(self):
        from ms_agent.a2a.agent_card import build_agent_card
        card = build_agent_card()
        assert card.name == 'ms-agent'
        assert card.url == 'http://localhost:5000/'
        assert card.capabilities.streaming is True
        assert len(card.skills) >= 1

    def test_build_agent_card_custom_host_port(self):
        from ms_agent.a2a.agent_card import build_agent_card
        card = build_agent_card(host='myhost', port=8080)
        assert card.url == 'http://myhost:8080/'

    def test_build_agent_card_with_skills(self):
        from ms_agent.a2a.agent_card import build_agent_card
        skills = [
            {'id': 'research', 'name': 'Deep Research',
             'description': 'Research topics'},
        ]
        card = build_agent_card(skills=skills)
        assert len(card.skills) == 1
        assert card.skills[0].id == 'research'

    def test_generate_agent_card_json(self, tmp_path):
        from ms_agent.a2a.agent_card import generate_agent_card_json
        import json
        out = tmp_path / 'card.json'
        card_dict = generate_agent_card_json(output_path=str(out))
        assert out.exists()
        with open(out) as f:
            data = json.load(f)
        assert data['name'] == 'ms-agent'
        assert 'capabilities' in data


# ======================================================================
# Executor tests with mock agent
# ======================================================================

class TestExecutor:

    @pytest.mark.asyncio
    async def test_executor_cancel_unknown_task(self):
        from ms_agent.a2a.executor import MSAgentA2AExecutor
        executor = MSAgentA2AExecutor(
            config_path='/tmp/nonexistent.yaml',
            max_tasks=2,
        )
        event_queue = EventQueue()

        context = RequestContext(
            task_id='task_unknown',
            context_id='ctx_1',
        )
        await executor.cancel(context, event_queue)

    @pytest.mark.asyncio
    async def test_executor_cleanup(self):
        from ms_agent.a2a.executor import MSAgentA2AExecutor
        executor = MSAgentA2AExecutor(
            config_path='/tmp/nonexistent.yaml',
        )
        await executor.cleanup()

    @pytest.mark.asyncio
    async def test_concurrent_execute_keeps_stdout_open(self, monkeypatch):
        from ms_agent.a2a.executor import MSAgentA2AExecutor

        class FakeAgent:

            async def run(self, messages, **kwargs):

                async def chunks():
                    await asyncio.sleep(0)
                    yield [Message(role='assistant', content='hello')]
                    await asyncio.sleep(0)
                    yield [Message(role='assistant', content='hello done')]

                return chunks()

        entries = {
            'task_1':
            SimpleNamespace(
                agent=FakeAgent(),
                messages=[],
                cancelled=False,
                is_running=False,
            ),
            'task_2':
            SimpleNamespace(
                agent=FakeAgent(),
                messages=[],
                cancelled=False,
                is_running=False,
            ),
        }

        async def get_or_create(task_id):
            return entries[task_id]

        def make_context(task_id):
            context = MagicMock()
            context.get_user_input.return_value = 'hi'
            context.current_task = SimpleNamespace(
                id=task_id,
                context_id=f'ctx_{task_id}',
            )
            context.message = None
            return context

        executor = MSAgentA2AExecutor(config_path='/tmp/agent.yaml')
        executor._store.get_or_create = AsyncMock(side_effect=get_or_create)

        stdout = io.StringIO()
        monkeypatch.setattr(sys, 'stdout', stdout)

        await asyncio.gather(
            executor.execute(make_context('task_1'), EventQueue()),
            executor.execute(make_context('task_2'), EventQueue()),
        )

        assert sys.stdout is stdout
        assert not stdout.closed


# ======================================================================
# TaskUpdater integration tests
# ======================================================================

class TestTaskUpdater:

    @staticmethod
    async def _drain_queue(event_queue: EventQueue) -> list:
        """Drain all events from the queue without blocking."""
        events = []
        while True:
            try:
                event = await event_queue.dequeue_event(no_wait=True)
                events.append(event)
                event_queue.task_done()
            except (asyncio.QueueEmpty, Exception):
                break
        return events

    @pytest.mark.asyncio
    async def test_updater_lifecycle(self):
        """Test the basic submit -> working -> complete lifecycle."""
        event_queue = EventQueue()
        updater = TaskUpdater(event_queue, 'task_1', 'ctx_1')

        await updater.submit()
        await updater.start_work()
        await updater.add_artifact(
            [Part(root=TextPart(text='result'))],
            name='response',
        )
        await updater.complete()

        events = await self._drain_queue(event_queue)
        assert len(events) >= 3

    @pytest.mark.asyncio
    async def test_updater_failed(self):
        event_queue = EventQueue()
        updater = TaskUpdater(event_queue, 'task_2', 'ctx_2')

        await updater.submit()
        await updater.start_work()
        await updater.failed(
            new_agent_text_message('something broke', 'ctx_2', 'task_2'))

        events = await self._drain_queue(event_queue)
        assert len(events) >= 3

    @pytest.mark.asyncio
    async def test_updater_cancel(self):
        event_queue = EventQueue()
        updater = TaskUpdater(event_queue, 'task_3', 'ctx_3')

        await updater.submit()
        await updater.cancel()

        events = await self._drain_queue(event_queue)
        assert len(events) >= 2


# ======================================================================
# InMemoryTaskStore tests
# ======================================================================

class TestTaskStore:

    @pytest.mark.asyncio
    async def test_in_memory_task_store_get_none(self):
        store = InMemoryTaskStore()
        result = await store.get('nonexistent')
        assert result is None
