"""End-to-end test for the ACP proxy with a real opencode backend.

Spawns the ms-agent ACP proxy process over stdio, which in turn spawns
opencode as a backend ACP agent.  Validates the full lifecycle:
  initialize -> new_session -> prompt -> response streaming

Requires ``opencode`` to be installed and available in PATH.
"""

import asyncio
import os
import shutil
import sys
import tempfile
from typing import Any

import pytest

_SKIP_REASON = None
try:
    from acp import spawn_agent_process, text_block
    from acp.interfaces import Client
    from acp.schema import (
        AllowedOutcome,
        DeniedOutcome,
        RequestPermissionResponse,
    )
except ImportError:
    _SKIP_REASON = 'agent-client-protocol not installed'

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROXY_CONFIG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'proxy_opencode.yaml')


def _have_opencode() -> bool:
    return shutil.which('opencode') is not None


class _TestClient(Client):
    """ACP client that collects all streamed updates for assertion."""

    def __init__(self):
        self.updates: list = []
        self.text_chunks: list[str] = []
        self.thought_chunks: list[str] = []
        self.tool_calls: list = []
        self.tool_results: list = []
        self.permission_requests: list = []
        self.update_types: list[str] = []

    async def session_update(self, session_id: str, update: Any,
                             **kwargs: Any) -> None:
        self.updates.append(update)
        update_type = getattr(update, 'session_update', None)
        if update_type:
            self.update_types.append(update_type)

        if update_type == 'agent_message_chunk':
            content = getattr(update, 'content', None)
            if content is not None:
                text = getattr(content, 'text', None) or str(content)
                self.text_chunks.append(text)
        elif update_type == 'agent_thought_chunk':
            content = getattr(update, 'content', None)
            if content is not None:
                text = getattr(content, 'text', None) or str(content)
                self.thought_chunks.append(text)
        elif update_type == 'tool_call_start':
            self.tool_calls.append(update)
        elif update_type == 'tool_call_update':
            self.tool_results.append(update)

    async def request_permission(self, options: list, session_id: str,
                                 tool_call: Any, **kwargs: Any) -> Any:
        self.permission_requests.append({
            'session_id': session_id,
            'tool_call': tool_call,
        })
        allow = next(
            (o for o in options
             if 'allow' in (getattr(o, 'kind', '') or '')),
            None,
        )
        if allow:
            return RequestPermissionResponse(
                outcome=AllowedOutcome(
                    outcome='selected',
                    option_id=getattr(allow, 'option_id', 'allow_once'),
                )
            )
        return RequestPermissionResponse(
            outcome=DeniedOutcome(outcome='cancelled')
        )

    @property
    def collected_text(self) -> str:
        return ''.join(self.text_chunks)

    @property
    def collected_thought(self) -> str:
        return ''.join(self.thought_chunks)


async def _spawn_proxy(client):
    """Spawn the proxy process, yielding (conn, proc).

    Wraps ``spawn_agent_process`` so that the SDK's queue-closed race
    during teardown does not fail the test.
    """
    ctx = spawn_agent_process(
        client,
        sys.executable,
        '-m', 'ms_agent.cli.cli',
        'acp-proxy',
        '--config', _PROXY_CONFIG,
    )
    conn, proc = await ctx.__aenter__()
    try:
        yield conn, proc
    finally:
        try:
            await ctx.__aexit__(None, None, None)
        except RuntimeError:
            pass


@pytest.mark.skipif(
    _SKIP_REASON is not None, reason=_SKIP_REASON or '')
@pytest.mark.skipif(
    not _have_opencode(), reason='opencode not installed')
@pytest.mark.asyncio
async def test_proxy_initialize_and_new_session():
    """Proxy boots, negotiates protocol, and creates a session via opencode."""
    client = _TestClient()
    async for conn, _proc in _spawn_proxy(client):
        resp = await conn.initialize(protocol_version=1)
        assert resp.protocol_version >= 1
        assert resp.agent_info is not None
        assert resp.agent_info.name == 'ms-agent-proxy'

        session = await conn.new_session(cwd=os.getcwd(), mcp_servers=[])
        assert session.session_id
        assert session.session_id.startswith('pxy_')
        break


@pytest.mark.skipif(
    _SKIP_REASON is not None, reason=_SKIP_REASON or '')
@pytest.mark.skipif(
    not _have_opencode(), reason='opencode not installed')
@pytest.mark.asyncio
async def test_proxy_prompt_streaming():
    """Send a trivial prompt through the proxy to opencode and verify
    that streamed text is relayed back."""
    client = _TestClient()
    async for conn, _proc in _spawn_proxy(client):
        await conn.initialize(protocol_version=1)
        session = await conn.new_session(cwd=os.getcwd(), mcp_servers=[])
        sid = session.session_id

        prompt_resp = await asyncio.wait_for(
            conn.prompt(
                session_id=sid,
                prompt=[text_block(
                    'Reply with exactly: PROXY_TEST_OK. '
                    'Do not include any other text.'
                )],
            ),
            timeout=120,
        )

        assert prompt_resp is not None
        assert len(client.updates) > 0, 'No session updates received'
        assert len(client.text_chunks) > 0, 'No text chunks relayed'
        assert len(client.collected_text) > 0, 'Collected text is empty'
        print(f'\n--- Proxy E2E (simple) ---')
        print(f'Updates received: {len(client.updates)}')
        print(f'Text chunks: {len(client.text_chunks)}')
        print(f'Collected text: {client.collected_text[:200]}')
        print(f'Stop reason: {prompt_resp.stop_reason}')
        break


@pytest.mark.skipif(
    _SKIP_REASON is not None, reason=_SKIP_REASON or '')
@pytest.mark.skipif(
    not _have_opencode(), reason='opencode not installed')
@pytest.mark.asyncio
async def test_proxy_real_task_with_tools():
    """Give opencode a real task that requires tool use (reading a file
    and analyzing its content), then verify that tool_call events are
    properly relayed through the proxy."""

    with tempfile.TemporaryDirectory() as tmpdir:
        target_file = os.path.join(tmpdir, 'data.csv')
        with open(target_file, 'w') as f:
            f.write('name,score\n')
            f.write('Alice,92\n')
            f.write('Bob,85\n')
            f.write('Charlie,78\n')
            f.write('Diana,95\n')
            f.write('Eve,88\n')

        client = _TestClient()
        async for conn, _proc in _spawn_proxy(client):
            await conn.initialize(protocol_version=1)
            session = await conn.new_session(
                cwd=tmpdir, mcp_servers=[])
            sid = session.session_id

            prompt_resp = await asyncio.wait_for(
                conn.prompt(
                    session_id=sid,
                    prompt=[text_block(
                        f'Read the file {target_file} and tell me: '
                        f'who has the highest score? '
                        f'Reply with just the name and score.'
                    )],
                ),
                timeout=120,
            )

            assert prompt_resp is not None

            unique_types = set(client.update_types)
            print(f'\n--- Proxy E2E (real task) ---')
            print(f'Total updates: {len(client.updates)}')
            print(f'Update types seen: {sorted(unique_types)}')
            print(f'Tool calls started: {len(client.tool_calls)}')
            print(f'Tool results: {len(client.tool_results)}')
            print(f'Permission requests: {len(client.permission_requests)}')
            print(f'Thought chunks: {len(client.thought_chunks)}')
            print(f'Text chunks: {len(client.text_chunks)}')
            print(f'Response text: {client.collected_text[:300]}')
            print(f'Stop reason: {prompt_resp.stop_reason}')

            print(f'\n--- Raw updates dump ---')
            for i, u in enumerate(client.updates):
                utype = getattr(u, 'session_update', '?')
                content = getattr(u, 'content', None)
                text = None
                if content is not None:
                    text = getattr(content, 'text', None)
                    if text is None:
                        text = str(content)[:200]
                print(f'  [{i}] type={utype}')
                print(f'       content_text={text[:200] if text else None}')
                for attr in ('tool_call_id', 'call_id', 'name',
                             'tool_name', 'arguments'):
                    val = getattr(u, attr, None)
                    if val is not None:
                        print(f'       {attr}={str(val)[:100]}')

            assert len(client.updates) > 0, 'No updates received'

            all_text = []
            for u in client.updates:
                utype = getattr(u, 'session_update', None)
                if utype in ('agent_message_chunk', 'user_message_chunk'):
                    content = getattr(u, 'content', None)
                    if content is not None:
                        t = getattr(content, 'text', None) or str(content)
                        all_text.append(t)
            full_response = ''.join(all_text)
            print(f'\nFull response (agent+user chunks): '
                  f'{full_response[:300]}')

            assert len(full_response) > 0, (
                f'No response text in any chunk type. '
                f'Types: {sorted(unique_types)}'
            )

            response_lower = full_response.lower()
            assert 'diana' in response_lower or '95' in response_lower, (
                f'Expected Diana/95 in response, got: '
                f'{full_response[:200]}'
            )

            has_tool_activity = (
                len(client.tool_calls) > 0
                or len(client.tool_results) > 0
                or 'tool_call' in unique_types
                or 'tool_call_update' in unique_types
            )
            assert has_tool_activity, (
                f'Expected tool use for file reading, but got none. '
                f'Update types: {sorted(unique_types)}'
            )
            break
