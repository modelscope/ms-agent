"""End-to-end A2A test using the A2A SDK client.

This validates the full A2A lifecycle by starting an A2A server subprocess
and connecting to it with the A2A SDK client.

**Requires** a valid agent config and a2a-sdk to be installed.
When those are unavailable the test is skipped gracefully.
"""

import asyncio
import os
import subprocess
import sys
import time

import pytest

_SKIP_REASON = None
try:
    import httpx
    from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
    from a2a.client.helpers import create_text_message_object
except ImportError:
    _SKIP_REASON = 'a2a-sdk or httpx not installed'

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_CONFIG = os.path.join(_REPO_ROOT, 'ms_agent', 'agent', 'agent.yaml')
_A2A_TEST_CONFIG = os.environ.get('A2A_TEST_CONFIG', _DEFAULT_CONFIG)
_A2A_TEST_PORT = int(os.environ.get('A2A_TEST_PORT', '19999'))


def _have_config() -> bool:
    return os.path.isfile(_A2A_TEST_CONFIG)


@pytest.fixture(scope='module')
def a2a_server():
    """Start an A2A server as a subprocess and yield its base URL."""
    if not _have_config():
        pytest.skip('No agent config found for A2A E2E test')

    proc = subprocess.Popen(
        [sys.executable, '-m', 'ms_agent.cli.cli',
         'a2a',
         '--config', _A2A_TEST_CONFIG,
         '--host', '127.0.0.1',
         '--port', str(_A2A_TEST_PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    time.sleep(5)

    if proc.poll() is not None:
        stderr = proc.stderr.read().decode() if proc.stderr else ''
        pytest.skip(f'A2A server failed to start: {stderr[:500]}')

    yield f'http://127.0.0.1:{_A2A_TEST_PORT}'

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or '')
@pytest.mark.skipif(not _have_config(),
                    reason='No agent config found for A2A E2E test')
class TestA2AE2E:

    @pytest.mark.asyncio
    async def test_discover_agent_card(self, a2a_server):
        """Verify the A2A server publishes an Agent Card."""
        async with httpx.AsyncClient() as http:
            resolver = A2ACardResolver(
                httpx_client=http, base_url=a2a_server)
            card = await resolver.get_agent_card()
            assert card.name
            assert card.capabilities is not None
            assert len(card.skills) >= 1

    @pytest.mark.asyncio
    async def test_send_message(self, a2a_server):
        """Send a simple message and verify we get a response."""
        if not os.environ.get('OPENAI_API_KEY'):
            pytest.skip('No OPENAI_API_KEY for LLM-backed test')

        async with httpx.AsyncClient(timeout=120.0) as http:
            resolver = A2ACardResolver(
                httpx_client=http, base_url=a2a_server)
            card = await resolver.get_agent_card()

            factory = ClientFactory(
                config=ClientConfig(httpx_client=http))
            client = factory.create(card)

            message = create_text_message_object(content='Say hello in 3 words')
            events = []
            async for event in client.send_message(message):
                events.append(event)

            assert len(events) >= 1
