import asyncio
import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TEST_CONFIG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'test_openai_config.yaml')

sys.path.insert(0, _REPO_ROOT)

_HAS_API_KEY = bool(os.environ.get('OPENAI_API_KEY'))

try:
    from acp import spawn_agent_process, text_block
    from acp.interfaces import Client
    _HAS_ACP = True
except ImportError:
    _HAS_ACP = False


class _StreamingTestClient(Client):
    """Records all session updates from the ACP server."""

    def __init__(self):
        self.updates = []
        self.text_chunks = []
        self.thought_chunks = []
        self.tool_calls = []

    async def session_update(self, session_id, update, **kwargs):
        self.updates.append(update)
        update_type = getattr(update, 'session_update', None)
        if update_type == 'agent_message_chunk':
            content = getattr(update, 'content', None)
            if content:
                text = getattr(content, 'text', None) or str(content)
                self.text_chunks.append(text)
        elif update_type == 'agent_thought_chunk':
            content = getattr(update, 'content', None)
            if content:
                text = getattr(content, 'text', None) or str(content)
                self.thought_chunks.append(text)
        elif update_type == 'tool_call_start':
            self.tool_calls.append(update)

    async def request_permission(self, options, session_id, tool_call, **kwargs):
        allow = next(
            (o for o in options if 'allow' in (getattr(o, 'kind', '') or '')),
            None,
        )
        if allow:
            return {'outcome': {'outcome': 'selected', 'id': getattr(allow, 'option_id', 'allow_once')}}
        return {'outcome': {'outcome': 'cancelled'}}

    @property
    def full_text(self):
        return ''.join(self.text_chunks)


@pytest.mark.skipif(not _HAS_ACP, reason='agent-client-protocol not installed')
@pytest.mark.skipif(not _HAS_API_KEY, reason='OPENAI_API_KEY not set')
@pytest.mark.skipif(not os.path.isfile(_TEST_CONFIG), reason='Test config not found')
class TestACPE2ERealLLM:

    @pytest.mark.asyncio
    async def test_full_prompt_with_real_llm(self):
        """Complete flow: initialize -> new_session -> prompt with real LLM."""
        client = _StreamingTestClient()

        async with spawn_agent_process(
            client,
            sys.executable,
            '-m', 'ms_agent.cli.cli',
            'acp',
            '--config', _TEST_CONFIG,
        ) as (conn, proc):
            init_resp = await conn.initialize(protocol_version=1)
            assert init_resp.protocol_version == 1
            assert init_resp.agent_info.name == 'ms-agent'

            session = await conn.new_session(cwd='/tmp', mcp_servers=[])
            sid = session.session_id
            assert sid.startswith('ses_')

            prompt_resp = await conn.prompt(
                session_id=sid,
                prompt=[text_block('What is 2 + 3? Answer with just the number.')],
            )

            assert prompt_resp.stop_reason in ('end_turn', 'max_turn_requests')

            full_text = client.full_text
            print(f'\n[LLM Response] "{full_text}"')
            assert len(full_text) > 0, 'Expected non-empty response'
            assert '5' in full_text, f'Expected "5" in response, got: {full_text}'

    @pytest.mark.asyncio
    async def test_streaming_produces_multiple_chunks(self):
        """Verify that the streaming produces incremental updates."""
        client = _StreamingTestClient()

        async with spawn_agent_process(
            client,
            sys.executable,
            '-m', 'ms_agent.cli.cli',
            'acp',
            '--config', _TEST_CONFIG,
        ) as (conn, proc):
            await conn.initialize(protocol_version=1)
            session = await conn.new_session(cwd='/tmp', mcp_servers=[])

            await conn.prompt(
                session_id=sid if (sid := session.session_id) else '',
                prompt=[text_block(
                    'List the first 5 prime numbers, one per line.'
                )],
            )

            assert len(client.updates) > 0, 'Expected at least one update'
            print(f'\n[Streaming] Got {len(client.updates)} updates, '
                  f'{len(client.text_chunks)} text chunks')
            assert '2' in client.full_text
            assert '3' in client.full_text
            assert '5' in client.full_text

    @pytest.mark.asyncio
    async def test_multi_turn_conversation(self):
        """Verify multi-turn works: send two prompts in the same session."""
        client = _StreamingTestClient()

        async with spawn_agent_process(
            client,
            sys.executable,
            '-m', 'ms_agent.cli.cli',
            'acp',
            '--config', _TEST_CONFIG,
        ) as (conn, proc):
            await conn.initialize(protocol_version=1)
            session = await conn.new_session(cwd='/tmp', mcp_servers=[])
            sid = session.session_id

            await conn.prompt(
                session_id=sid,
                prompt=[text_block('Remember the number 42.')],
            )
            turn1_text = client.full_text
            print(f'\n[Turn 1] "{turn1_text}"')

            client.text_chunks.clear()
            client.updates.clear()

            await conn.prompt(
                session_id=sid,
                prompt=[text_block('What number did I just ask you to remember?')],
            )
            turn2_text = client.full_text
            print(f'[Turn 2] "{turn2_text}"')
            assert '42' in turn2_text, f'Expected "42" in turn 2 response: {turn2_text}'

    @pytest.mark.asyncio
    async def test_config_options_returned(self):
        """Verify new_session returns config options with model selector."""
        client = _StreamingTestClient()

        async with spawn_agent_process(
            client,
            sys.executable,
            '-m', 'ms_agent.cli.cli',
            'acp',
            '--config', _TEST_CONFIG,
        ) as (conn, proc):
            await conn.initialize(protocol_version=1)
            session = await conn.new_session(cwd='/tmp', mcp_servers=[])

            assert session.config_options is not None
            model_opt = next(
                (o for o in session.config_options if o.id == 'model'), None)
            assert model_opt is not None, 'Expected model config option'
            assert model_opt.current_value == 'qwen-plus'
            print(f'\n[Config] Model option: {model_opt.current_value}')

    @pytest.mark.asyncio
    async def test_session_modes_returned(self):
        """Verify new_session returns session modes."""
        client = _StreamingTestClient()

        async with spawn_agent_process(
            client,
            sys.executable,
            '-m', 'ms_agent.cli.cli',
            'acp',
            '--config', _TEST_CONFIG,
        ) as (conn, proc):
            await conn.initialize(protocol_version=1)
            session = await conn.new_session(cwd='/tmp', mcp_servers=[])

            assert session.modes is not None
            assert session.modes.current_mode_id == 'agent'


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short', '-s'])
