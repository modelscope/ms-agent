import os
from typing import Any, Dict, List, Optional

import httpx
from ms_agent.utils.logger import get_logger

logger = get_logger()


class A2AClientManager:
    """Lifecycle manager for remote A2A agent connections.

    Each configured agent (from ``a2a_agents`` in the YAML config) is
    represented by its URL.  Connections use HTTP via ``httpx`` and the
    A2A SDK's ``ClientFactory``.
    """

    def __init__(self, a2a_agents_config: dict | None = None):
        self._config: Dict[str, dict] = a2a_agents_config or {}
        self._http_client: Optional[httpx.AsyncClient] = None

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=300.0)
        return self._http_client

    async def call_agent(
        self,
        agent_name: str,
        query: str,
    ) -> str:
        """Send a message to a remote A2A agent and return the text response.

        Discovers the agent via its Agent Card, then sends a message using
        the A2A SDK client.  Supports both streaming and non-streaming
        responses.
        """
        cfg = self._config.get(agent_name)
        if cfg is None:
            return f'Error: A2A agent "{agent_name}" not configured'

        url = cfg.get('url', '')
        if not url:
            return f'Error: A2A agent "{agent_name}" has no URL configured'

        try:
            from a2a.client import (
                A2ACardResolver,
                ClientConfig,
                ClientFactory,
            )
            from a2a.client.helpers import create_text_message_object

            http_client = self._get_http_client()

            auth_headers = self._build_auth_headers(cfg)
            if auth_headers:
                http_client = httpx.AsyncClient(
                    timeout=300.0, headers=auth_headers)

            resolver = A2ACardResolver(httpx_client=http_client, base_url=url)
            card = await resolver.get_agent_card()

            factory = ClientFactory(
                config=ClientConfig(httpx_client=http_client))
            client = factory.create(card)

            message = create_text_message_object(content=query)
            result_parts: list[str] = []

            async for event in client.send_message(message):
                if hasattr(event, 'parts'):
                    for part in event.parts:
                        part_obj = part
                        if hasattr(part, 'root'):
                            part_obj = part.root
                        if hasattr(part_obj, 'text'):
                            result_parts.append(part_obj.text)
                elif isinstance(event, tuple) and len(event) == 2:
                    task, update = event
                    if update and hasattr(update, 'status'):
                        status = update.status
                        msg = getattr(status, 'message', None)
                        if msg and hasattr(msg, 'parts'):
                            for part in msg.parts:
                                part_obj = part
                                if hasattr(part, 'root'):
                                    part_obj = part.root
                                if hasattr(part_obj, 'text'):
                                    result_parts.append(part_obj.text)
                    if task and hasattr(task, 'artifacts'):
                        for artifact in (task.artifacts or []):
                            for part in (artifact.parts or []):
                                part_obj = part
                                if hasattr(part, 'root'):
                                    part_obj = part.root
                                if hasattr(part_obj, 'text'):
                                    result_parts.append(part_obj.text)

            return '\n'.join(result_parts) if result_parts else '(no output)'

        except Exception as e:
            logger.error(
                'A2A call to %s failed: %s', agent_name, e, exc_info=True)
            return f'Error calling A2A agent "{agent_name}": {e}'

    @staticmethod
    def _build_auth_headers(cfg: dict) -> dict[str, str]:
        """Build authentication headers from agent config."""
        auth = cfg.get('auth')
        if not auth:
            return {}

        auth_type = auth.get('type', '').lower()
        if auth_type == 'bearer':
            token_env = auth.get('token_env', '')
            token = auth.get('token', '') or os.environ.get(token_env, '')
            if token:
                return {'Authorization': f'Bearer {token}'}

        return {}

    def list_agents(self) -> List[str]:
        return list(self._config.keys())

    async def close_all(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
