import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from acp import spawn_agent_process, text_block
from acp.interfaces import Client
from ms_agent.utils.logger import get_logger

logger = get_logger()


class _CollectorClient(Client):
    """Minimal ACP client that accumulates streamed text from an external agent.

    Permission requests are resolved by the configured *policy*.
    """

    def __init__(self, permission_policy: str = 'auto_approve'):
        self.collected: Dict[str, List[str]] = {}
        self.permission_policy = permission_policy

    async def session_update(self, session_id: str, update: Any,
                             **kwargs: Any) -> None:
        update_type = getattr(update, 'session_update', None)
        if update_type == 'agent_message_chunk':
            content = getattr(update, 'content', None)
            if content is not None:
                text = getattr(content, 'text', None) or str(content)
                self.collected.setdefault(session_id, []).append(text)

    async def request_permission(self, options: list, session_id: str,
                                 tool_call: Any, **kwargs: Any):
        from acp.schema import (RequestPermissionResponse, AllowedOutcome,
                                DeniedOutcome)
        if self.permission_policy == 'auto_approve':
            allow = next(
                (o for o in options
                 if 'allow' in (getattr(o, 'kind', '') or '')),
                None,
            )
            if allow:
                option_id = getattr(allow, 'option_id', 'allow_once')
                return RequestPermissionResponse(
                    outcome=AllowedOutcome(
                        outcome='selected',
                        option_id=option_id,
                    ))
        return RequestPermissionResponse(
            outcome=DeniedOutcome(outcome='cancelled'))

    def get_output(self, session_id: str) -> str:
        parts = self.collected.get(session_id, [])
        return ''.join(parts)

    def clear(self, session_id: str) -> None:
        self.collected.pop(session_id, None)


class ACPClientManager:
    """Lifecycle manager for external ACP agent connections,
    which spawns external agent processes via the SDK's
    ``spawn_agent_process`` and provides a high-level interface for sending
    prompts, collecting streamed output, and handling permission callbacks.

    Each configured agent (from ``acp_agents`` in the YAML config) is
    represented by its *command + args*.  Connections are opened lazily
    and cached for the lifetime of the manager.
    """

    def __init__(self, acp_agents_config: dict | None = None):
        self._config: Dict[str, dict] = acp_agents_config or {}
        self._clients: Dict[str, _CollectorClient] = {}
        self._connections: Dict[str, Any] = {}
        self._processes: Dict[str, Any] = {}
        self._ctx_managers: Dict[str, Any] = {}

    async def call_agent(
        self,
        agent_name: str,
        query: str,
        cwd: str = '/tmp',
    ) -> str:
        """Send a single-turn prompt to an external ACP agent and return
        the accumulated text response.
        """
        cfg = self._config.get(agent_name)
        if cfg is None:
            return f'Error: ACP agent "{agent_name}" not configured'

        policy = cfg.get('permission_policy', 'auto_approve')
        client = _CollectorClient(permission_policy=policy)

        command = cfg['command']
        args = cfg.get('args', [])

        try:
            ctx = spawn_agent_process(client, command, *args)
            conn, proc = await ctx.__aenter__()

            try:
                await conn.initialize(protocol_version=1)
                session = await conn.new_session(cwd=cwd, mcp_servers=[])
                sid = session.session_id

                await conn.prompt(
                    session_id=sid,
                    prompt=[text_block(query)],
                )
                return client.get_output(sid) or '(no output)'
            finally:
                try:
                    await ctx.__aexit__(None, None, None)
                except Exception:
                    pass
        except Exception as e:
            logger.error(
                'ACP call to %s failed: %s', agent_name, e, exc_info=True)
            return f'Error calling ACP agent "{agent_name}": {e}'

    def list_agents(self) -> List[str]:
        return list(self._config.keys())

    async def close_all(self) -> None:
        for name, ctx in list(self._ctx_managers.items()):
            try:
                await ctx.__aexit__(None, None, None)
            except Exception:
                pass
        self._connections.clear()
        self._processes.clear()
        self._clients.clear()
        self._ctx_managers.clear()
