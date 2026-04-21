import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml
from acp import (PROTOCOL_VERSION, Agent, InitializeResponse,
                 NewSessionResponse, PromptResponse, run_agent,
                 spawn_agent_process)
from acp.interfaces import Client
from acp.schema import (AgentCapabilities, ClientCapabilities, Implementation,
                        PromptCapabilities, SessionCapabilities,
                        SessionConfigOptionSelect, SessionConfigSelect,
                        SessionConfigSelectOption, SessionListCapabilities)
from ms_agent.utils.logger import get_logger

from .errors import ConfigError, wrap_agent_error
from .proxy_session import ProxySessionStore

logger = get_logger()

_VERSION = '0.1.0'


@dataclass
class BackendConfig:
    """Parsed configuration for a single backend agent."""
    name: str
    command: str
    args: list = field(default_factory=list)
    description: str = ''
    env: dict = field(default_factory=dict)


@dataclass
class ProxyConfig:
    """Top-level proxy configuration parsed from YAML."""
    max_sessions: int = 8
    session_timeout: int = 3600
    default_backend: str = ''
    backends: Dict[str, BackendConfig] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str) -> 'ProxyConfig':
        if not path or not os.path.exists(path):
            raise ConfigError(f'Proxy config not found: {path}')
        with open(path) as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict):
            raise ConfigError(f'Invalid proxy config format in {path}')

        proxy_section = raw.get('proxy', {})
        backends_section = raw.get('backends', {})

        backends: Dict[str, BackendConfig] = {}
        for name, cfg in backends_section.items():
            if not isinstance(cfg, dict) or 'command' not in cfg:
                logger.warning('Skipping backend %s: missing "command"', name)
                continue
            backends[name] = BackendConfig(
                name=name,
                command=cfg['command'],
                args=cfg.get('args', []),
                description=cfg.get('description', f'ACP agent: {name}'),
                env=cfg.get('env', {}),
            )

        default = proxy_section.get('default_backend', '')
        if not default and backends:
            default = next(iter(backends))

        return cls(
            max_sessions=proxy_section.get('max_sessions', 8),
            session_timeout=proxy_section.get('session_timeout', 3600),
            default_backend=default,
            backends=backends,
        )


class _RelayClient(Client):
    """ACP Client that transparently relays ``session_update`` and
    ``request_permission`` from a backend agent back through the proxy's
    own connection to the IDE.

    This is the core mechanism that makes streaming work without any
    translator or delta-tracking logic.
    """

    def __init__(self, proxy_connection: Any, proxy_session_id: str):
        self._conn = proxy_connection
        self._proxy_sid = proxy_session_id

    async def session_update(self, session_id: str, update: Any,
                             **kwargs: Any) -> None:
        await self._conn.session_update(self._proxy_sid, update)

    async def request_permission(self, options: list, session_id: str,
                                 tool_call: Any, **kwargs: Any) -> Any:
        return await self._conn.request_permission(
            session_id=self._proxy_sid,
            tool_call=tool_call,
            options=options,
        )


class MSAgentACPProxy(Agent):
    """ACP Proxy Server that dispatches sessions to backend ACP agents.

    Unlike ``MSAgentACPServer``, this module implements a pure ACP-to-ACP relay.
    It presents itself as a standard ACP ``Agent`` to the IDE,
    but internally dispatches every session to a backend agent subprocess via ``spawn_agent_process``.
    Import boundary: this module MUST NOT import from ``ms_agent.agent``,
    ``ms_agent.llm``, ``ms_agent.tools``, or ``ms_agent.acp.translator``.
    """

    def __init__(self, config: ProxyConfig) -> None:
        self.config = config
        self.session_store = ProxySessionStore(
            max_sessions=config.max_sessions,
            session_timeout=config.session_timeout,
        )

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        negotiated = min(protocol_version, PROTOCOL_VERSION)
        logger.info(
            'ACP proxy initialize: client=%s  negotiated_version=%d',
            client_info.name if client_info else '<unknown>',
            negotiated,
        )
        return InitializeResponse(
            protocol_version=negotiated,
            agent_capabilities=AgentCapabilities(
                load_session=False,
                prompt_capabilities=PromptCapabilities(
                    image=False,
                    audio=False,
                    embedded_context=True,
                ),
                session_capabilities=SessionCapabilities(
                    list=SessionListCapabilities(), ),
            ),
            agent_info=Implementation(
                name='ms-agent-proxy',
                title='MS-Agent Proxy',
                version=_VERSION,
            ),
            auth_methods=[],
        )

    async def new_session(
        self,
        cwd: str,
        mcp_servers: list | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        backend_name = self.config.default_backend
        try:
            entry = await self._spawn_backend_session(backend_name, cwd)
        except Exception as e:
            logger.error('new_session failed: %s', e, exc_info=True)
            raise

        config_options = self._build_config_options(backend_name)
        return NewSessionResponse(
            session_id=entry.id,
            config_options=config_options,
        )

    async def prompt(
        self,
        prompt: list,
        session_id: str,
        **kwargs: Any,
    ) -> PromptResponse:
        entry = self.session_store.get(session_id)
        entry.is_running = True
        try:
            result = await entry.backend_conn.prompt(
                session_id=entry.backend_sid,
                prompt=prompt,
            )
            return result
        except Exception as e:
            logger.error('Proxy prompt error: %s', e, exc_info=True)
            raise wrap_agent_error(e)
        finally:
            entry.is_running = False

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        try:
            entry = self.session_store.get(session_id)
            entry.request_cancel()
            try:
                await entry.backend_conn.cancel(session_id=entry.backend_sid)
            except Exception:
                logger.warning('Backend cancel failed for %s', session_id)
        except Exception:
            logger.warning('Cancel for unknown proxy session %s', session_id)

    async def list_sessions(
        self,
        cursor: str | None = None,
        cwd: str | None = None,
        **kwargs: Any,
    ):
        from acp.schema import ListSessionsResponse, SessionInfo
        entries = self.session_store.list_sessions()
        items = [
            SessionInfo(
                session_id=e['session_id'],
                cwd=e.get('cwd'),
            ) for e in entries
        ]
        return ListSessionsResponse(sessions=items)

    async def set_config_option(
        self,
        config_id: str,
        session_id: str,
        value: str | bool,
        **kwargs: Any,
    ):
        from acp.schema import SetSessionConfigOptionResponse

        if config_id == 'backend':
            new_backend = str(value)
            if new_backend not in self.config.backends:
                raise ConfigError(f'Unknown backend: {new_backend}')

            entry = self.session_store.get(session_id)
            old_cwd = entry.cwd

            await self.session_store.remove(session_id)
            new_entry = await self._spawn_backend_session(new_backend, old_cwd)

            self.session_store._sessions[session_id] = new_entry
            new_entry.id = session_id

            config_options = self._build_config_options(new_backend)
            return SetSessionConfigOptionResponse(
                config_options=config_options or [])

        entry = self.session_store.get(session_id)
        try:
            result = await entry.backend_conn.set_config_option(
                config_id=config_id,
                session_id=entry.backend_sid,
                value=value,
            )
            return result
        except Exception:
            logger.warning('Backend set_config_option failed', exc_info=True)
            return SetSessionConfigOptionResponse(config_options=[])

    def on_connect(self, conn) -> None:
        self.connection = conn

    async def _shutdown(self) -> None:
        await self.session_store.close_all()

    async def _spawn_backend_session(
        self,
        backend_name: str,
        cwd: str,
    ):
        """Spawn a backend agent process, initialize it, create a session,
        and register everything in the proxy session store."""
        import uuid as _uuid

        bcfg = self.config.backends.get(backend_name)
        if bcfg is None:
            raise ConfigError(f'Backend not configured: {backend_name}')

        proxy_sid = f'pxy_{_uuid.uuid4().hex[:12]}'

        relay = _RelayClient(self.connection, proxy_sid)

        env = dict(os.environ)
        env.update(bcfg.env)

        ctx = spawn_agent_process(relay, bcfg.command, *bcfg.args, env=env)
        conn, proc = await ctx.__aenter__()

        try:
            await conn.initialize(protocol_version=PROTOCOL_VERSION)
            session_resp = await conn.new_session(cwd=cwd, mcp_servers=[])
            backend_sid = session_resp.session_id
        except Exception:
            try:
                await ctx.__aexit__(None, None, None)
            except Exception:
                pass
            raise

        entry = self.session_store.register(
            backend_name=backend_name,
            backend_sid=backend_sid,
            backend_conn=conn,
            backend_proc=proc,
            ctx_manager=ctx,
            cwd=cwd,
        )
        old_id = entry.id
        entry.id = proxy_sid
        self.session_store._sessions.pop(old_id, None)
        self.session_store._sessions[proxy_sid] = entry

        return entry

    def _build_config_options(
        self,
        current_backend: str,
    ) -> list | None:
        if len(self.config.backends) <= 1:
            return None

        values = [
            SessionConfigSelectOption(
                value=name,
                name=f'{name}: {bcfg.description}',
            ) for name, bcfg in self.config.backends.items()
        ]
        return [
            SessionConfigOptionSelect(
                type='select',
                id='backend',
                name='Backend Agent',
                category='model',
                current_value=current_backend,
                options=values,
            ),
        ]


def configure_proxy_logging(log_file: str | None = None) -> None:
    """Set up logging so nothing leaks onto stdout (the ACP wire)."""
    handler: logging.Handler
    if log_file:
        handler = logging.FileHandler(log_file)
    else:
        handler = logging.StreamHandler(sys.stderr)

    fmt = logging.Formatter(
        '%(asctime)s [%(name)s] %(levelname)s: %(message)s')
    handler.setFormatter(fmt)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def serve_proxy(
    config_path: str,
    log_file: str | None = None,
) -> None:
    """Entry point: run the ACP proxy server over stdio."""
    configure_proxy_logging(log_file)

    config = ProxyConfig.from_yaml(config_path)
    logger.info(
        'Proxy starting: %d backends configured [%s], default=%s',
        len(config.backends),
        ', '.join(config.backends.keys()),
        config.default_backend,
    )

    proxy = MSAgentACPProxy(config)

    import asyncio
    asyncio.run(_run_proxy(proxy))


async def _run_proxy(proxy: MSAgentACPProxy) -> None:
    try:
        await run_agent(proxy)
    finally:
        await proxy._shutdown()
