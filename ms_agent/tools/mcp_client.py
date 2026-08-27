from __future__ import annotations

# Copyright (c) ModelScope Contributors. All rights reserved.
import asyncio
import copy
import os
import re
from contextlib import AsyncExitStack, suppress
from datetime import timedelta
from mcp import ClientSession, ListToolsResult, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from omegaconf import DictConfig
from types import TracebackType
from typing import Any, Dict, List, Literal, Optional

from ms_agent.config import Config
from ms_agent.config.env import Env
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import enhance_error, get_logger

logger = get_logger()

EncodingErrorHandler = Literal['strict', 'ignore', 'replace']

DEFAULT_ENCODING = 'utf-8'
DEFAULT_ENCODING_ERROR_HANDLER: EncodingErrorHandler = 'strict'

DEFAULT_HTTP_TIMEOUT = 5
DEFAULT_SSE_READ_TIMEOUT = 60 * 5


def _int_env(name: str, default: int) -> int:
    """``os.getenv`` hands back a STRING once the variable is set, and these
    values end up in ``timedelta(seconds=...)``, which rejects one."""
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


CONNECTION_TIMEOUT = _int_env('CONNECTION_TIMEOUT', 120)

#: How many servers may be started at once. Bounded because each stdio server
#: is a child process and a large config would otherwise fork all of them
#: simultaneously.
MAX_PARALLEL_CONNECTS = _int_env('MCP_MAX_PARALLEL_CONNECTS', 8)

#: How long to wait for a server's owner task to close its transport before
#: cancelling it outright.
SERVER_STOP_TIMEOUT = _int_env('MCP_STOP_TIMEOUT', 15)

#: Wall-clock ceiling on bringing ONE server up (spawn/dial + initialize).
#: Without it a stdio server that never answers — a cold ``uvx`` still
#: resolving, a wrapper whose upstream 403s — parks the whole connect,
#: and with servers brought up together that is a session that never
#: finishes preparing its tools.
DEFAULT_SERVER_STARTUP_TIMEOUT = _int_env('MCP_STARTUP_TIMEOUT', 60)

DEFAULT_STREAMABLE_HTTP_TIMEOUT = timedelta(seconds=30)
DEFAULT_STREAMABLE_HTTP_SSE_READ_TIMEOUT = timedelta(seconds=60 * 5)


_PYDANTIC_DOC_LINK = re.compile(r'\s*For further information visit \S+')
_PYDANTIC_FIELD_LINE = re.compile(r'^(\S+?)(?:\.\w+)?\n\s+(.+?)\s*\[type=',
                                  re.MULTILINE)


def _summarize_tool_error(detail: str) -> str:
    """Make a validator's complaint answerable.

    A union of strict types reports once per branch, so rejecting two quoted
    numbers arrives as four near-identical paragraphs, each ending in a link to
    the validation library's documentation. None of that tells the model what
    to send instead, and its length buries the one line that does. The
    per-field expectation is lifted to the front; the original follows for
    anyone reading the transcript.
    """
    if 'validation error' not in detail:
        return detail

    seen: dict = {}
    for field, message in _PYDANTIC_FIELD_LINE.findall(detail):
        seen.setdefault(field, message)
    if not seen:
        return _PYDANTIC_DOC_LINK.sub('', detail).strip()

    lines = [f'- `{field}`: {message}' for field, message in seen.items()]
    return ('the arguments were rejected by the tool:\n'
            + '\n'.join(lines)
            + '\nSend each value as its declared JSON type (a number '
            'unquoted, not as a string) and call again.\n\nOriginal error:\n'
            + _PYDANTIC_DOC_LINK.sub('', detail).strip())


class MCPClient(ToolBase):
    """MCP client for all mcp tools

    This class can hold multiple mcp servers.

    Args:
        config(`DictConfig`): The config instance.
        mcp_config(`Optional[Dict[str, Any]]`): Extra mcp servers in json format.
    """

    def __init__(
        self,
        mcp_config: Optional[Dict[str, Any]] = None,
        config: Optional[DictConfig] = None,
    ):
        super().__init__(config)
        self.sessions: Dict[str, ClientSession] = {}
        # One owner task per server, holding that server's transport open for
        # its whole lifetime (see _own_server), plus the event that asks it to
        # let go.
        self._server_tasks: Dict[str, 'asyncio.Task'] = {}
        self._server_shutdown: Dict[str, asyncio.Event] = {}
        self.exit_stack = AsyncExitStack()
        self.mcp_config: Dict[str, Dict[str, Any]] = {'mcpServers': {}}
        if config is not None:
            config_from_file = Config.convert_mcp_servers_to_json(config)
            self.mcp_config['mcpServers'].update(
                config_from_file.get('mcpServers', {}))
        self.exclude_functions = {}
        self.include_functions = {}
        if mcp_config is not None:
            self.mcp_config['mcpServers'].update(
                mcp_config.get('mcpServers', {}))

    async def call_tool(self, server_name: str, tool_name: str,
                        tool_args: dict):
        response = await self.sessions[server_name].call_tool(
            tool_name, tool_args)

        texts = []
        resources = []
        if response.isError:
            sep = '\n\n'
            if all(isinstance(item, str) for item in response.content):
                detail = sep.join(response.content)
            else:
                detail = sep.join(
                    getattr(item, 'text', str(item))
                    for item in response.content)
            # Marked as an error rather than returned as ordinary text. A
            # failure reported only in prose reaches the model with no error
            # flag and reaches the UI with no failed step, so a call that was
            # refused looks like a call that answered.
            return {
                'result':
                (f'execute tool call error: [{server_name}]{tool_name}, '
                 f'{_summarize_tool_error(detail)}'),
                'is_error':
                True,
            }
        for content in response.content:
            if content.type == 'text':
                texts.append(content.text)
            elif content.type == 'resource':
                import json5
                json_str = content.resource.model_dump_json(by_alias=True)
                texts.append(json_str)
                resources.append(json5.loads(json_str))

        if resources:
            return {'text': '\n\n'.join(texts), 'resources': resources}

        return '\n\n'.join(texts)

    def _filter_session_tools(
        self,
        server_name: str,
        response: ListToolsResult,
    ) -> List[Tool]:
        exclude: list[str] = []
        include: list[str] = []
        if self.include_functions and server_name in self.include_functions:
            include = self.include_functions[server_name]
        elif self.exclude_functions and server_name in self.exclude_functions:
            exclude = self.exclude_functions[server_name]
        session_tools = [t for t in response.tools if t.name not in exclude]
        if include:
            session_tools = [t for t in session_tools if t.name in include]
        return [
            Tool(
                tool_name=t.name,
                server_name=server_name,
                description=t.description,
                parameters=t.inputSchema,
            ) for t in session_tools
        ]

    async def get_tools_for_server(self, server_name: str) -> List[Tool]:
        """List tools for a single connected server (failures are isolated)."""
        session = self.sessions.get(server_name)
        if session is None:
            return []
        try:
            response = await session.list_tools()
        except Exception as e:
            new_eg = enhance_error(
                e, f'MCP `{server_name}` list tool failed, details: ')
            raise new_eg from e
        # Logged from here rather than from connect(): the same listing that
        # registers the tools also reports them, so the log costs no extra
        # round trip to the server.
        self.print_tools(server_name, response)
        return self._filter_session_tools(server_name, response)

    async def get_tools(self) -> Dict:
        tools: Dict[str, List[Tool]] = {}
        for key in self.sessions:
            try:
                tools[key] = await self.get_tools_for_server(key)
            except Exception as e:
                logger.warning('Skipping MCP server %s in get_tools: %s', key,
                               e)
                tools[key] = []
        return tools

    @staticmethod
    def print_tools(server_name: str, tools: ListToolsResult):
        tools = tools.tools
        sep = ','
        if len(tools) > 10:
            tools = [tool.name for tool in tools][:10]
            logger.info(
                f'\nConnected to server "{server_name}" '
                f'with tools: \n{sep.join(tools)}\nOnly list first 10 of them.'
            )
        else:
            tools = [tool.name for tool in tools]
            logger.info(f'\nConnected to server "{server_name}" '
                        f'with tools: \n{sep.join(tools)}.')

    @staticmethod
    def resolve_server_env(server: Dict[str, Any]) -> Dict[str, str]:
        envs = Env.load_env()
        env_dict = copy.deepcopy(server.get('env') or {})
        return {
            key: value if value else envs.get(key, '')
            for key, value in env_dict.items()
        }

    def list_connected_servers(self) -> list[str]:
        return list(self.sessions.keys())

    def is_connected(self, server_name: str) -> bool:
        return server_name in self.sessions

    async def disconnect_server(self, server_name: str) -> None:
        """Disconnect a single MCP server."""
        self.exclude_functions.pop(server_name, None)
        self.include_functions.pop(server_name, None)
        await self._stop_server(server_name)

    async def connect_single_server(
        self,
        server_name: str,
        server_config: Dict[str, Any],
        timeout: int = CONNECTION_TIMEOUT,
    ) -> str:
        """Connect one server from a normalized config entry."""
        if self.is_connected(server_name):
            return server_name
        server = copy.deepcopy(server_config)
        env_dict = self.resolve_server_env(server)
        if 'exclude' in server:
            self.exclude_functions[server_name] = server.pop('exclude')
        if 'include' in server:
            self.include_functions[server_name] = server.pop('include')
        assert (not self.include_functions.get(server_name)) or (
            not self.exclude_functions.get(server_name)
        ), 'Set either `include` or `exclude` in tools config.'
        timeout = server.pop('timeout', timeout)
        for drop_key in ('enabled', 'source', 'plugin_id', 'meta'):
            server.pop(drop_key, None)
        return await self.connect_to_server(
            server_name=server_name,
            env=env_dict,
            timeout=timeout,
            **server,
        )

    async def _open_session(self, stack: AsyncExitStack, server_name: str,
                            timeout: int, **kwargs) -> ClientSession:
        """Open the transport for one server and return its initialized session.

        Every context entered here is registered on ``stack``, which the
        caller must also close — see :meth:`_own_server` for why that has to
        happen in the same task.
        """
        # transport: stdio, sse, streamable_http, websocket
        transport = kwargs.get('transport') or kwargs.get('type')
        command = kwargs.get('command')
        url = kwargs.get('url')
        session_kwargs = kwargs.get('session_kwargs')
        if url:
            if transport and transport.lower() == 'sse':
                logger.info(
                    '`transport` or `type` is configured as "sse", using sse transport.'
                )
                sse_transport = await stack.enter_async_context(
                    sse_client(
                        url, kwargs.get('headers'),
                        kwargs.get('timeout', DEFAULT_HTTP_TIMEOUT),
                        kwargs.get('sse_read_timeout',
                                   DEFAULT_SSE_READ_TIMEOUT)))
                read, write = sse_transport

            elif transport and transport.lower() == 'websocket':
                logger.info(
                    '`transport` or `type` is configured as "websocket", using websocket transport.'
                )
                try:
                    from mcp.client.websocket import websocket_client
                except ImportError:
                    raise ImportError(
                        'Could not import websocket_client. '
                        'To use Websocket connections, please install the required dependency with: '
                        "'pip install mcp[ws]' or 'pip install websockets'"
                    ) from None
                websocket_transport = await stack.enter_async_context(
                    websocket_client(url))
                read, write = websocket_transport

            else:
                logger.info(
                    'Using streamable_http transport. To configure a different transport such as sse, please'
                    'set the `type` or `transport` variable to "sse".')
                try:
                    from mcp.client.streamable_http import \
                        streamablehttp_client
                except ImportError:
                    raise ImportError(
                        'Could not import streamablehttp_client. '
                        'To use streamable http connections, please upgrade to the latest version of mcp with: '
                        "'pip install -U mcp'") from None
                httpx_client_factory = kwargs.get('httpx_client_factory')
                other_kwargs = {}
                if httpx_client_factory is not None:
                    other_kwargs['httpx_client_factory'] = httpx_client_factory
                streamable_transport = await stack.enter_async_context(
                    streamablehttp_client(
                        url,
                        headers=kwargs.get('headers'),
                        timeout=kwargs.get('timeout',
                                           DEFAULT_STREAMABLE_HTTP_TIMEOUT),
                        sse_read_timeout=kwargs.get(
                            'sse_read_timeout',
                            DEFAULT_STREAMABLE_HTTP_SSE_READ_TIMEOUT),
                        **other_kwargs))
                read, write, _ = streamable_transport

            session_kwargs = session_kwargs or {}
            timeout = max(
                session_kwargs.pop('read_timeout_seconds', timeout), 1)
            session = await stack.enter_async_context(
                ClientSession(
                    read,
                    write,
                    read_timeout_seconds=timedelta(seconds=timeout),
                    **session_kwargs))

        elif command:
            # transport: 'stdio'
            args = kwargs.get('args')
            if not args:
                raise ValueError(
                    "'args' parameter is required for stdio connection")
            server_params = StdioServerParameters(
                command=command,
                args=args,
                env=kwargs.get('env'),
                encoding=kwargs.get('encoding', DEFAULT_ENCODING),
                encoding_error_handler=kwargs.get(
                    'encoding_error_handler', DEFAULT_ENCODING_ERROR_HANDLER),
            )

            stdio, write = await stack.enter_async_context(
                stdio_client(server_params))
            session_kwargs = session_kwargs or {}
            read_timeout = max(
                session_kwargs.pop('read_timeout_seconds', timeout), 1)
            # The url branch above has always passed this; stdio never did, so
            # a child that accepted the pipe and then went quiet left every
            # request on it waiting forever.
            session = await stack.enter_async_context(
                ClientSession(
                    stdio,
                    write,
                    read_timeout_seconds=timedelta(seconds=read_timeout),
                    **session_kwargs))
        else:
            raise ValueError(
                "'url' or 'command' parameter is required for connection")

        await session.initialize()
        return session

    async def _own_server(
        self,
        server_name: str,
        kwargs: Dict[str, Any],
        ready: 'asyncio.Future',
        shutdown: asyncio.Event,
    ) -> None:
        """Hold one server's transport open for as long as it is connected.

        The anyio streams underneath ``stdio_client`` / ``streamablehttp_client``
        carry a cancel scope that must be exited by the same task that entered
        it. Handing the open context back to the caller therefore only works
        while connect and cleanup happen in one task — the moment servers are
        brought up concurrently, teardown raises "Attempted to exit cancel
        scope in a different task". Keeping open, serve and close inside this
        one task removes that coupling entirely.
        """
        stack = AsyncExitStack()
        try:
            async with stack:
                session = await self._open_session(stack, server_name, **kwargs)
                self.sessions[server_name] = session
                if not ready.done():
                    ready.set_result(server_name)
                await shutdown.wait()
        except BaseException as exc:  # noqa: BLE001
            if not ready.done():
                ready.set_exception(exc)
            elif not isinstance(exc, asyncio.CancelledError):
                logger.warning('MCP server %s dropped: %s', server_name, exc)
        finally:
            self.sessions.pop(server_name, None)

    async def connect_to_server(self,
                                server_name: str,
                                timeout: int = CONNECTION_TIMEOUT,
                                startup_timeout: Optional[int] = None,
                                **kwargs):
        if self.is_connected(server_name):
            return server_name
        logger.info(f'connect to {server_name}')
        ready: 'asyncio.Future' = asyncio.get_running_loop().create_future()
        shutdown = asyncio.Event()
        task = asyncio.create_task(
            self._own_server(server_name, {
                'timeout': timeout,
                **kwargs
            }, ready, shutdown),
            name=f'mcp-server:{server_name}')
        self._server_tasks[server_name] = task
        self._server_shutdown[server_name] = shutdown
        try:
            if startup_timeout:
                # Shield so a timeout stops US waiting without cancelling the
                # owner mid-open; _stop_server below unwinds it in its own task.
                await asyncio.wait_for(
                    asyncio.shield(ready), timeout=startup_timeout)
            else:
                await ready
        except BaseException:
            # It never came up, so there is no established session to shut down
            # politely — waiting out the grace period here would just add it to
            # the startup timeout the caller already spent.
            await self._stop_server(server_name, graceful=False)
            raise
        return server_name

    async def _stop_server(self,
                           server_name: str,
                           graceful: bool = True) -> None:
        """Ask a server's owner task to close its transport, and wait for it."""
        shutdown = self._server_shutdown.pop(server_name, None)
        task = self._server_tasks.pop(server_name, None)
        self.sessions.pop(server_name, None)
        if shutdown is not None:
            shutdown.set()
        if task is None or task.done():
            return
        if graceful:
            try:
                await asyncio.wait_for(
                    asyncio.shield(task), timeout=SERVER_STOP_TIMEOUT)
                return
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            except BaseException as exc:  # noqa: BLE001
                logger.debug('MCP server %s stopped with %s', server_name, exc)
                return
        task.cancel()
        with suppress(BaseException):
            await task

    def _plan_server(self, name: str, server: Dict[str, Any],
                     default_timeout: int) -> Dict[str, Any]:
        """Pull the keys ``connect_to_server`` does not take out of a server
        block, and resolve its env against the ambient one."""
        envs = Env.load_env()
        env_dict = server.pop('env', {})
        env_dict = {
            key: value if value else envs.get(key, '')
            for key, value in env_dict.items()
        }
        if 'exclude' in server:
            self.exclude_functions[name] = server.pop('exclude')
        if 'include' in server:
            self.include_functions[name] = server.pop('include')
        assert (not self.include_functions.get(name)) or (
            not self.exclude_functions.get(name)
        ), 'Set either `include` or `exclude` in tools config.'
        # Bound to THIS server. Assigning it to the shared default (as the
        # sequential loop used to) leaked one server's timeout onto every
        # server configured after it.
        return {
            'server_name': name,
            'env': env_dict,
            'timeout': server.pop('timeout', default_timeout),
            **server,
        }

    async def connect(
        self,
        timeout: int = CONNECTION_TIMEOUT,
        startup_timeout: int = DEFAULT_SERVER_STARTUP_TIMEOUT,
    ) -> List[tuple]:
        """Bring every configured server up, and report which ones did not.

        Servers are started TOGETHER rather than one after another. Startup
        cost is dominated by what is being started — a cold ``uvx`` resolving
        and downloading its package runs to seconds — and paying that in
        sequence multiplied it by the number of servers before the user's
        first message could even be read.

        A server that fails or exceeds ``startup_timeout`` is left out instead
        of taking the rest down with it; the returned ``(name, exc)`` list lets
        a caller surface exactly what is missing. If NOTHING came up the
        failure is raised, since that is indistinguishable from a broken
        configuration and callers rely on hearing about it.
        """
        assert self.mcp_config, 'MCP config is required'
        mcp_config = self.mcp_config['mcpServers']
        plans = [
            self._plan_server(name, server, timeout)
            for name, server in mcp_config.items()
        ]
        if not plans:
            return []

        limiter = asyncio.Semaphore(MAX_PARALLEL_CONNECTS)

        async def _one(plan: Dict[str, Any]):
            async with limiter:
                # The bound is applied inside connect_to_server, which unwinds
                # a server that overran through its own owner task.
                await self.connect_to_server(
                    startup_timeout=startup_timeout, **plan)

        results = await asyncio.gather(
            *(_one(plan) for plan in plans), return_exceptions=True)

        failures: List[tuple] = []
        for plan, result in zip(plans, results):
            if not isinstance(result, BaseException):
                continue
            name = plan['server_name']
            if isinstance(result, asyncio.TimeoutError):
                result = TimeoutError(
                    f'MCP server `{name}` did not finish starting within '
                    f'{startup_timeout}s (set MCP_STARTUP_TIMEOUT to change). '
                    'A launcher such as uvx/npx populating a cold cache, or an '
                    'unreachable upstream, is the usual cause.')
            failures.append((name, result))

        if failures and not self.sessions:
            name, exc = failures[0]
            new_eg = enhance_error(exc, f'Connect `{name}` failed, details:')
            raise new_eg from exc
        for name, exc in failures:
            logger.warning('MCP server %s unavailable this session: %s', name,
                           exc)
        return failures

    async def add_mcp_config(self, mcp_config: Dict[str, Dict[str, Any]]):
        if mcp_config is None:
            return
        new_mcp_config = mcp_config.get('mcpServers', {})
        servers = self.mcp_config.setdefault('mcpServers', {})
        envs = Env.load_env()
        for name, server in new_mcp_config.items():
            if name in servers and servers[name] == server:
                continue
            else:
                servers[name] = server
                env_dict = server.pop('env', {})
                env_dict = {
                    key: value if value else envs.get(key, '')
                    for key, value in env_dict.items()
                }
                if 'exclude' in server:
                    self.exclude_functions[name] = server.pop('exclude')
                await self.connect_to_server(
                    server_name=name, env=env_dict, **server)
        self.mcp_config['mcpServers'].update(new_mcp_config)

    async def cleanup(self):
        """Clean up resources"""
        for name in list(self._server_tasks):
            await self.disconnect_server(name)
        await self.exit_stack.aclose()

    async def __aenter__(self) -> 'MCPClient':
        try:
            await self.connect()
            return self
        except Exception:
            await self.cleanup()
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.cleanup()
