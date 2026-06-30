"""End-to-end ACP test using ``spawn_agent_process``.

This validates the full ACP lifecycle (initialize -> new_session -> prompt)
without depending on an external client like Zed.

**Requires** a valid agent config and LLM API key in the environment to
actually run prompts.  When those are unavailable the test is skipped
gracefully so CI stays green.
"""

import asyncio
import os
import sys
from typing import Any

import pytest

_SKIP_REASON = None
try:
    from acp import spawn_agent_process, text_block
    from acp.interfaces import Client
except ImportError:
    _SKIP_REASON = 'agent-client-protocol not installed'

# Best-effort: find a usable agent config for the test.
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_CONFIG = os.path.join(_REPO_ROOT, 'ms_agent', 'agent', 'agent.yaml')
_ACP_TEST_CONFIG = os.environ.get('ACP_TEST_CONFIG', _DEFAULT_CONFIG)


def _have_config() -> bool:
    return os.path.isfile(_ACP_TEST_CONFIG)


class _TestClient(Client):
    """Minimal ACP client that records every session update."""

    def __init__(self):
        self.updates: list = []

    async def session_update(self, session_id, update, **kwargs):
        self.updates.append(update)

    async def request_permission(self, options, session_id, tool_call,
                                 **kwargs):
        allow = next((o for o in options if 'allow' in (o.kind or '')), None)
        if allow:
            return {'outcome': {'outcome': 'selected', 'id': allow.option_id}}
        return {'outcome': {'outcome': 'cancelled'}}


@pytest.mark.skipif(not _have_config(),
                    reason='No agent config found for ACP E2E test')
@pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or '')
@pytest.mark.asyncio
async def test_acp_initialize_and_new_session():
    """Verify the server boots, negotiates protocol, and creates a session."""
    client = _TestClient()
    async with spawn_agent_process(
            client,
            sys.executable,
            '-m', 'ms_agent.cli.cli',
            'acp',
            '--config', _ACP_TEST_CONFIG,
    ) as (conn, _proc):
        resp = await conn.initialize(protocol_version=1)
        assert resp.protocol_version == 1
        assert resp.agent_info is not None
        assert resp.agent_info.name == 'ms-agent'

        session = await conn.new_session(cwd='/tmp', mcp_servers=[])
        assert session.session_id
        assert session.session_id.startswith('ses_')
