"""Exercise the SDK boundaries, including arrivals during asynchronous hooks/tools."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.hooks.events import HookResult
from ms_agent.llm.utils import Message
from ms_agent.session.input_controller import SessionInputController
from ms_agent.session.session_log import SessionLog


async def agent_for(tmp_path):
    c = SessionInputController(SessionLog(tmp_path, session_key='boundaries'))
    async def prepare(request):
        return {'prompt': request['message']['content'], 'attachments': []}
    async def send(text, mode='steer'):
        return await c.accept(text, {'message': {'role': 'user', 'content': text}},
                              prepare, mode, c.active_turn)
    await send('initial', 'queue')
    c.start_next()
    c.append_message({'role': 'user', 'content': 'initial'})
    agent = LLMAgent.__new__(LLMAgent)
    agent._input_controller = c
    agent.session_log = c.log
    agent.runtime = SimpleNamespace(should_stop=False, round=1)
    agent.config = OmegaConf.create({'generation_config': {'stream': False, 'stream_output': False}})
    agent._event_sink = SimpleNamespace(emit=Mock())
    agent._hook_runtime = None
    agent._attach_memory_recall = AsyncMock()
    agent.loop_callback = AsyncMock()
    agent.add_memory = AsyncMock()
    agent._checkpoint_state = Mock(return_value={})
    agent.task_manager = None
    agent.load_cache = False
    agent.tool_manager = SimpleNamespace(get_tools=AsyncMock(return_value=[]))
    agent.on_generate_response = AsyncMock()
    agent.on_tool_call = AsyncMock()
    agent.save_history = Mock()
    agent.log_output = Mock()
    agent._record_image_deliveries = Mock()
    agent.handle_new_response = lambda messages, response: messages.append(response)
    return agent, c, send


@pytest.mark.asyncio
async def test_steer_during_stop_hook_keeps_same_task_open(tmp_path):
    agent, c, send = await agent_for(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    async def stop(**kwargs):
        entered.set()
        await release.wait()
        return HookResult(action='allow')
    agent._hook_runtime = SimpleNamespace(is_empty=False, run_stop=stop)
    rows = [Message(role='assistant', content='old final')]
    turn = c.active_turn
    task = asyncio.create_task(agent.after_tool_call(rows))
    await entered.wait()
    await send('correction')
    release.set()
    await task
    assert rows[-1].content == 'correction'
    assert c.active_turn == turn and not agent.runtime.should_stop
    agent.loop_callback.assert_awaited_once_with('after_tool_call', rows)
    agent.add_memory.assert_not_called()
    rows.append(Message(role='assistant', content='revised final'))
    await agent.after_tool_call(rows)
    assert c.active_turn is None and agent.runtime.should_stop
    agent.add_memory.assert_awaited_once()


@pytest.mark.asyncio
async def test_steer_during_decision_review_supersedes_old_feedback(tmp_path):
    agent, controller, send = await agent_for(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()

    async def review(**kwargs):
        entered.set()
        await release.wait()
        return 'Feedback on the old objective'

    agent.callbacks = []
    agent.max_chat_round = 10
    agent._decision_supervisor = SimpleNamespace(check=review)
    rows = [Message(role='assistant', content='old final')]
    turn = controller.active_turn
    task = asyncio.create_task(agent.after_tool_call(rows))
    await entered.wait()
    await send('Corrected objective')
    release.set()
    await task
    assert rows[-1].content == 'Corrected objective'
    assert not getattr(rows[-1], '_decision_feedback', False)
    assert controller.active_turn == turn and not agent.runtime.should_stop
    agent.add_memory.assert_not_called()


@pytest.mark.asyncio
async def test_steer_skips_declared_but_unstarted_calls_with_balanced_results(tmp_path):
    agent, c, send = await agent_for(tmp_path)
    response = Message(role='assistant', tool_calls=[
        {'id': f'write-{i}', 'tool_name': 'write_file', 'arguments': '{}'} for i in range(2)])
    async def generate(*args):
        await send('do not write')
        return response
    agent._generate_response = generate
    agent.parallel_tool_call = AsyncMock()
    rows = [Message(role='user', content='initial')]
    outputs = [part async for part in LLMAgent.step.__wrapped__(agent, rows)]
    rows = outputs[-1]
    agent.parallel_tool_call.assert_not_called()
    results = [row for row in rows if row.role == 'tool']
    assert [row.tool_call_id for row in results] == ['write-0', 'write-1']
    assert all(row.is_error and row.execution_status == 'skipped' for row in results)
    await agent.after_tool_call(rows)
    assert rows[-1].content == 'do not write'
    assert c.active_turn is not None


@pytest.mark.asyncio
async def test_started_tool_batch_finishes_before_multiple_steers(tmp_path):
    agent, c, send = await agent_for(tmp_path)
    agent._generate_response = AsyncMock(return_value=Message(role='assistant', tool_calls=[
        {'id': 'started', 'tool_name': 'shell', 'arguments': '{}'}]))
    entered, release = asyncio.Event(), asyncio.Event()
    async def tools(rows):
        entered.set()
        await release.wait()
        rows.append(Message(role='tool', tool_call_id='started', content='real output'))
        return rows
    agent.parallel_tool_call = tools
    async def step():
        return [part async for part in LLMAgent.step.__wrapped__(
            agent, [Message(role='user', content='initial')])][-1]
    task = asyncio.create_task(step())
    await entered.wait()
    await send('first update')
    await send('second update')
    assert not task.done()
    release.set()
    rows = await task
    await agent.after_tool_call(rows)
    assert [row.content for row in rows[-3:]] == ['real output', 'first update', 'second update']
    assert [row['content'] for row in c.log.get_all_messages() if row['role'] == 'user'] == [
        'initial', 'first update', 'second update']
