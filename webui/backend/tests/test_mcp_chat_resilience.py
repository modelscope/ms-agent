"""Full WebUI -> SDK -> model-boundary regression, including same-session recovery."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

from app.backends.ms_agent import chat, common, model_link, mcps, projects, sessions
from app.backends.ms_agent.runtime import registry
from app.schemas.chat import ChatMessage, ChatRequest
from app.schemas.mcp import McpCreate
from app.schemas.project import ProjectCreate
from app.schemas.session import SessionCreate


@pytest.mark.parametrize('transport', ['legacy', 'session'])
async def test_first_token_notice_replay_and_same_session_reconnect(tmp_path, monkeypatch, transport):
    from ms_agent.agent.llm_agent import LLMAgent
    from ms_agent.llm.utils import Message

    model_link._save({'llm': {'provider': 'openai', 'model': 'mcp-fixture',
                             'api_key': 'test', 'base_url': 'http://127.0.0.1:1/v1'},
                      'providers': {'openai': {'api_key': 'test', 'models': ['mcp-fixture']}}})
    common.pm().initialize()
    project = projects.create_project(ProjectCreate(name='mcp-recovery'))
    session = sessions.create_session(SessionCreate(title='same session', project_id=project.id))
    peer = tmp_path / 'peer.py'
    ready = tmp_path / 'ready'
    secret = 'peer-output-diagnostic-test-secret'
    fixture = Path(__file__).resolve().parents[3] / 'tests/mcp/fixtures/stdio_server.py'
    peer.write_text('import sys\nfrom pathlib import Path\n'
                   f'if not Path({str(ready)!r}).exists(): print("HTTP 403: {secret}", file=sys.stderr)\n'
                   f'sys.argv = ["fixture", "ok" if Path({str(ready)!r}).exists() else "exit", {str(tmp_path / "child.pid")!r}]\n'
                   f'exec(Path({str(fixture)!r}).read_text())\n')
    row = mcps.create_mcp(McpCreate(name='recoverable', transport='stdio',
        endpoint=f'{sys.executable} {peer}', scope=f'project:{project.id}'))
    observed = []

    async def generate(self, messages, tools):
        observed.append(([m.content for m in messages], [t['tool_name'] for t in tools]))
        return iter([Message(role='assistant', content='answer')])
    monkeypatch.setattr(LLMAgent, '_generate_response', generate)

    async def turn(text):
        req = ChatRequest(session_id=session.id, project_id=project.id,
                          message=ChatMessage(role='user', content=text))
        if transport == 'session':
            from app.backends.ms_agent import conversations
            conversation = conversations.get(session.id)
            previous = conversation.sequence
            await conversations.submit(req)
            await conversation.worker
            events = [event for event in conversation.events
                      if int(event['cursor'].rsplit(':', 1)[1]) > previous]
            assert not any(event['type'] == 'failure' for event in events), events
            chunks = [event['chunk'] for event in events if event['type'] == 'chunk']
            delivered = [chunk for chunk in chunks if chunk['type'] == 'input']
            assert len(delivered) == 1
            assert delivered[0]['meta']['message']['content'] == text
            return chunks
        frames = [frame async for frame in chat.stream(req)]
        return [json.loads(f['data']) for f in frames if f.get('data') and f['data'] != '[DONE]']

    try:
        first = await asyncio.wait_for(turn('first question'), 15)
        assert any(f.get('type') == 'text' and f['content'] == 'answer' for f in first), first
        assert any(f.get('type') == 'notice' for f in first)
        assert not any(f.get('type') == 'error' for f in first)
        before = registry._runtimes[session.id]
        history = sessions.list_messages(session.id)
        assert any(p.kind == 'notice' for m in history for p in m.parts)
        assert any('optional MCP servers are unavailable' in (c or '') for c in observed[0][0])
        assert secret not in json.dumps(first)
        assert secret not in str(history)
        assert secret not in str(observed)
        assert not any('403' in (c or '') for c in observed[0][0])
        ready.touch()
        reply = await mcps.reconnect(row.id)
        assert reply.scheduled == 1
        assert registry._runtimes[session.id] is before
        second = await asyncio.wait_for(turn('second question'), 15)
        assert registry._runtimes[session.id] is not before
        assert any(f.get('type') == 'text' for f in second)
        assert 'recoverable---demo' in observed[-1][1]
        assert 'first question' in observed[-1][0]
        assert 'second question' in observed[-1][0]
        assert not any('optional MCP servers are unavailable' in (c or '') for c in observed[-1][0])
    finally:
        await registry.close_all()
        mcps.delete_mcp(row.id)
        projects.delete_project(project.id)
