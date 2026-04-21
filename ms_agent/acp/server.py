import io
import logging
import os
import sys
from contextlib import contextmanager
from typing import Any

import json
from acp import (PROTOCOL_VERSION, Agent, InitializeResponse,
                 NewSessionResponse, PromptResponse, run_agent, text_block)
from acp.schema import (AgentCapabilities, ClientCapabilities, Implementation,
                        PermissionOption, PromptCapabilities,
                        SessionCapabilities, SessionListCapabilities)
from ms_agent.utils.logger import get_logger

from .config import (apply_config_option, build_config_options,
                     build_session_modes)
from .errors import wrap_agent_error
from .session_store import ACPSessionStore
from .translator import ACPTranslator

logger = get_logger()

SUPPORTED_PROTOCOL_VERSION: int = PROTOCOL_VERSION

_VERSION = '0.1.0'


def configure_acp_logging(log_file: str | None = None) -> None:
    """Set up logging so nothing leaks onto stdout (the ACP wire).

    By default logs go to *stderr*; pass ``log_file`` to write to disk
    instead.
    """
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


class MSAgentACPServer(Agent):
    """ACP Server that wraps ms-agent's ``LLMAgent`` (or any project agent)."""

    def __init__(
        self,
        config_path: str,
        trust_remote_code: bool = False,
        max_sessions: int = 8,
        session_timeout: int = 3600,
    ) -> None:
        self.config_path = config_path
        self.trust_remote_code = trust_remote_code
        self.session_store = ACPSessionStore(
            max_sessions=max_sessions,
            session_timeout=session_timeout,
        )
        self._translators: dict[str, ACPTranslator] = {}

    def _get_translator(self, session_id: str) -> ACPTranslator:
        if session_id not in self._translators:
            self._translators[session_id] = ACPTranslator()
        return self._translators[session_id]

    @staticmethod
    @contextmanager
    def _suppress_stdout():
        """Redirect stdout to devnull while running agent logic.

        LLMAgent.step() writes streaming tokens to sys.stdout, which
        would corrupt the ACP JSON-RPC wire when running over stdio.
        """
        real_stdout = sys.stdout
        sys.stdout = open(os.devnull, 'w')
        try:
            yield
        finally:
            sys.stdout.close()
            sys.stdout = real_stdout

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        negotiated = min(protocol_version, SUPPORTED_PROTOCOL_VERSION)
        logger.info(
            'ACP initialize: client=%s  negotiated_version=%d',
            client_info.name if client_info else '<unknown>',
            negotiated,
        )
        return InitializeResponse(
            protocol_version=negotiated,
            agent_capabilities=AgentCapabilities(
                load_session=True,
                prompt_capabilities=PromptCapabilities(
                    image=False,
                    audio=False,
                    embedded_context=True,
                ),
                session_capabilities=SessionCapabilities(
                    list=SessionListCapabilities(), ),
            ),
            agent_info=Implementation(
                name='ms-agent',
                title='MS-Agent',
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
        meta = kwargs.get('_meta') or kwargs.get('field_meta')
        try:
            session = await self.session_store.create(
                config_path=self.config_path,
                cwd=cwd,
                trust_remote_code=self.trust_remote_code,
                mcp_servers=mcp_servers,
                meta=meta,
            )
        except Exception as e:
            logger.error('new_session failed: %s', e, exc_info=True)
            raise
        config_options = build_config_options(session.config)
        modes = build_session_modes()
        return NewSessionResponse(
            session_id=session.id,
            config_options=config_options,
            modes=modes,
        )

    async def prompt(
        self,
        prompt: list,
        session_id: str,
        **kwargs: Any,
    ) -> PromptResponse:
        session = self.session_store.get(session_id)
        translator = self._get_translator(session_id)

        is_first_turn = len(session.messages) == 0
        prior_msg_count = len(session.messages)

        translator.reset_turn(prior_msg_count)

        if is_first_turn:
            user_text = translator.prompt_to_messages(prompt)[0].content
            run_input = user_text
        else:
            run_input = translator.prompt_to_messages(prompt, session.messages)

        session.is_running = True
        session._cancel_event.clear()

        try:
            with self._suppress_stdout():
                result = await session.agent.run(run_input, stream=True)
                if hasattr(result, '__aiter__'):
                    async for chunk in result:
                        session.messages = chunk
                        updates = translator.messages_to_updates(chunk)
                        for update in updates:
                            try:
                                await self.connection.session_update(
                                    session_id, update)
                            except Exception as send_err:
                                logger.warning(
                                    'Failed to send session_update: %s',
                                    send_err)
                        if session.cancelled:
                            break
                elif isinstance(result, list):
                    session.messages = result
                    updates = translator.messages_to_updates(result)
                    for update in updates:
                        try:
                            await self.connection.session_update(
                                session_id, update)
                        except Exception as send_err:
                            logger.warning('Failed to send session_update: %s',
                                           send_err)

            plan_updates = self._extract_plan_updates(session, translator)
            for pu in plan_updates:
                try:
                    await self.connection.session_update(session_id, pu)
                except Exception:
                    pass

            stop = translator.map_stop_reason(session)
            return PromptResponse(stop_reason=stop)
        except Exception as e:
            logger.error('Error during prompt: %s', e, exc_info=True)
            raise wrap_agent_error(e)
        finally:
            session.is_running = False

    @staticmethod
    def _extract_plan_updates(session, translator) -> list:
        """Extract plan updates from agent state (todo tool, etc.)."""
        agent = session.agent
        steps = []

        if hasattr(agent, 'runtime') and agent.runtime:
            todo_items = getattr(agent.runtime, 'todo_items', None)
            if todo_items and isinstance(todo_items, list):
                for item in todo_items:
                    if isinstance(item, dict):
                        steps.append({
                            'description':
                            item.get('description', item.get('content', '')),
                            'status':
                            item.get('status', 'pending'),
                            'priority':
                            item.get('priority', 'medium'),
                        })

        if not steps:
            for msg in reversed(session.messages or []):
                if (msg.role == 'tool' and msg.name
                        in ('todo_write', 'todo_read', 'todo', 'split_task')
                        and msg.content):
                    try:
                        data = json.loads(msg.content)
                        todos = None
                        if isinstance(data, dict):
                            todos = data.get('todos', None)
                        if isinstance(data, list):
                            todos = data
                        if todos and isinstance(todos, list):
                            for item in todos:
                                if isinstance(item, dict):
                                    steps.append({
                                        'description':
                                        item.get(
                                            'content',
                                            item.get('description',
                                                     item.get('task', ''))),
                                        'status':
                                        item.get('status', 'pending'),
                                        'priority':
                                        item.get('priority', 'medium'),
                                    })
                            break
                    except (json.JSONDecodeError, TypeError):
                        pass

        if steps:
            return [translator.build_plan_update(steps)]
        return []

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        try:
            session = self.session_store.get(session_id)
            session.request_cancel()
            logger.info('Session %s cancel requested', session_id)
        except Exception:
            logger.warning('Cancel for unknown session %s', session_id)

    async def load_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list | None = None,
        **kwargs: Any,
    ):
        from acp.schema import LoadSessionResponse
        try:
            session = self.session_store.get(session_id)
        except Exception:
            logger.info('load_session: session %s not found, creating new',
                        session_id)
            meta = kwargs.get('_meta') or kwargs.get('field_meta')
            session = await self.session_store.create(
                config_path=self.config_path,
                cwd=cwd,
                trust_remote_code=self.trust_remote_code,
                mcp_servers=mcp_servers,
                meta=meta,
            )

        translator = self._get_translator(session.id)
        translator.reset_turn()
        for i, msg in enumerate(session.messages):
            partial = session.messages[:i + 1]
            updates = translator.messages_to_updates(partial)
            for update in updates:
                try:
                    await self.connection.session_update(session.id, update)
                except Exception:
                    pass

        config_options = build_config_options(session.config)
        modes = build_session_modes()
        return LoadSessionResponse(
            session_id=session.id,
            config_options=config_options,
            modes=modes,
        )

    async def list_sessions(
        self,
        cursor: str | None = None,
        cwd: str | None = None,
        **kwargs: Any,
    ):
        from acp.schema import ListSessionsResponse, SessionInfo
        entries = self.session_store.list_sessions()
        items = []
        for e in entries:
            items.append(
                SessionInfo(
                    session_id=e['session_id'],
                    cwd=e.get('cwd'),
                ))
        return ListSessionsResponse(sessions=items)

    async def set_config_option(
        self,
        config_id: str,
        session_id: str,
        value: str | bool,
        **kwargs: Any,
    ):
        from acp.schema import SetSessionConfigOptionResponse
        session = self.session_store.get(session_id)
        apply_config_option(session.config, config_id, str(value))
        new_options = build_config_options(session.config) or []
        return SetSessionConfigOptionResponse(config_options=new_options)

    async def set_session_mode(
        self,
        mode_id: str,
        session_id: str,
        **kwargs: Any,
    ):
        from acp.schema import SetSessionModeResponse, CurrentModeUpdate
        # _session = self.session_store.get(session_id)
        await self.connection.session_update(
            session_id,
            CurrentModeUpdate(
                session_update='current_mode_update',
                current_mode_id=mode_id,
            ),
        )
        return SetSessionModeResponse()

    def on_connect(self, conn) -> None:
        self.connection = conn

    async def _shutdown(self) -> None:
        await self.session_store.close_all()


def serve(
    config_path: str,
    trust_remote_code: bool = False,
    max_sessions: int = 8,
    session_timeout: int = 3600,
    log_file: str | None = None,
) -> None:
    """Entry point: run the ACP server over stdio."""
    configure_acp_logging(log_file)
    logger.info(
        'serve() called: config_path=%s trust_remote_code=%s '
        'sys.argv=%s', config_path, trust_remote_code, sys.argv)
    server = MSAgentACPServer(
        config_path=config_path,
        trust_remote_code=trust_remote_code,
        max_sessions=max_sessions,
        session_timeout=session_timeout,
    )
    import asyncio
    asyncio.run(_run_server(server))


async def _run_server(server: MSAgentACPServer) -> None:
    try:
        await run_agent(server)
    finally:
        await server._shutdown()
