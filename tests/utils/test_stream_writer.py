# Copyright (c) ModelScope Contributors. All rights reserved.
"""Sub-agent traces must retain completed messages, not first-token snapshots."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from omegaconf import OmegaConf

from ms_agent.llm.utils import Message
from ms_agent.tools.agent_tool import AgentTool
from ms_agent.utils.stream_writer import SubAgentStreamWriter


def records(writer):
    return [json.loads(line) for line in
            Path(writer.stream_path).read_text(encoding='utf-8').splitlines()]


@pytest.mark.parametrize('mutate', [False, True])
def test_cumulative_tail_is_written_once_when_complete(tmp_path, mutate):
    writer = SubAgentStreamWriter(str(tmp_path), 'call', 'worker')
    writer.on_start('worker')
    history = [Message(role='user', content='question'),
               Message(role='assistant', content='H')]
    writer.on_chunk(history)
    if mutate:
        history[-1].content = 'Hello'
    else:
        history[-1] = Message(role='assistant', content='Hello')
    writer.on_chunk(history)
    writer.on_end(history)
    writer.on_end(history)
    rows = records(writer)
    messages = [row for row in rows if row['type'] == 'message']
    assert [row['index'] for row in messages] == [0, 1]
    assert [row['message']['content'] for row in messages] == ['question', 'Hello']
    assert rows[-1]['total_messages'] == 2
    assert len([row for row in rows if row['type'] == 'footer']) == 1


def test_tool_arguments_finalized_before_next_message(tmp_path):
    writer = SubAgentStreamWriter(str(tmp_path), 'call', 'worker')
    writer.on_start('worker')
    history = [{'role': 'assistant', 'content': '', 'tool_calls': [
        {'id': 'call1', 'arguments': '{"path":'}]}]
    writer.on_chunk(history)
    history[0]['tool_calls'][0]['arguments'] = '{"path":"report.md"}'
    history.append({'role': 'tool', 'content': 'written'})
    writer.on_chunk(history)
    # The completed tool call is available before the agent finishes.
    assert records(writer)[1]['message']['tool_calls'][0]['arguments'] == (
        '{"path":"report.md"}')
    writer.on_end(history)
    assert records(writer)[-1]['total_messages'] == 2


@pytest.mark.parametrize('enable_stats', [False, True])
@pytest.mark.parametrize('failure', [None, RuntimeError('model disconnected'),
                                   asyncio.CancelledError()])
def test_agent_tool_stream_file_tracks_final_or_interrupted_text(
        tmp_path, failure, enable_stats):
    class StreamingAgent:
        tag = 'worker'

        async def run(self, payload, stream):
            assert stream

            async def chunks():
                history = [Message(role='assistant', content='H')]
                yield history
                history[-1] = Message(role='assistant', content='Hello')
                yield history
                if failure is not None:
                    raise failure
            return chunks()

    tool = AgentTool(OmegaConf.create({
        'output_dir': str(tmp_path), 'agent_stream_file': True, 'tools': {}}))
    tool._enable_stats = enable_stats
    spec = SimpleNamespace(tool_name='worker', server_name='agents', run_in_thread=False,
                           run_in_process=False)
    call = tool._run_agent(StreamingAgent(), 'question', spec, call_id='call')
    if failure is None:
        asyncio.run(call)
    else:
        with pytest.raises(type(failure)):
            asyncio.run(call)
    path = tmp_path / '.ms_agent/subagents/call.stream.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[1]['message']['content'] == 'Hello'
    assert rows[-1]['type'] == 'footer'
    assert rows[-1]['status'] == ('complete' if failure is None else 'error')
