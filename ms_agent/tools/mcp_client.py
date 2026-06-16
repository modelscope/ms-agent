# Copyright (c) ModelScope Contributors. All rights reserved.
import copy
import os
from contextlib import AsyncExitStack
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
CONNECTION_TIMEOUT = os.getenv('CONNECTION_TIMEOUT', 120)

DEFAULT_STREAMABLE_HTTP_TIMEOUT = timedelta(seconds=30)
DEFAULT_STREAMABLE_HTTP_SSE_READ_TIMEOUT = timedelta(seconds=60 * 5)


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
        self._server_stacks: Dict[str, AsyncExitStack] = {}
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
                return f'execute tool call error: [{server_name}]{tool_name}, {sep.join(response.content)}'
            else:
                item_list = []
                for item in response.content:
                    item_list.append(item.text)
                return f'execute tool call error: [{server_name}]{tool_name}, {sep.join(item_list)}'
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
            )
            for t in session_tools
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
        return self._filter_session_tools(server_name, response)

    async def get_tools(self) -> Dict:
        tools: Dict[str, List[Tool]] = {}
        for key in self.sessions:
            try:
                tools[key] = await self.get_tools_for_server(key)
            except Exception as e:
                logger.warning(
                    'Skipping MCP server %s in get_tools: %s', key, e)
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
        stack = self._server_stacks.pop(server_name, None)
        self.sessions.pop(server_name, None)
        self.exclude_functions.pop(server_name, None)
        self.include_functions.pop(server_name, None)
        if stack is not None:
            await stack.aclose()

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
        for drop_key in ('enabled', 'source', 'meta'):
            server.pop(drop_key, None)
        return await self.connect_to_server(
            server_name=server_name,
            env=env_dict,
            timeout=timeout,
            **server,
        )

    async def connect_to_server(self,
                                server_name: str,
                                timeout: int = CONNECTION_TIMEOUT,
                                **kwargs):
        if self.is_connected(server_name):
            return server_name
        logger.info(f'connect to {server_name}')
        stack = AsyncExitStack()
        self._server_stacks[server_name] = stack
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
            session = await stack.enter_async_context(
                ClientSession(stdio, write))
        else:
            raise ValueError(
                "'url' or 'command' parameter is required for connection")

        await session.initialize()
        # Store session
        self.sessions[server_name] = session
        self.print_tools(server_name, await session.list_tools())
        return server_name

    async def connect(self, timeout: int = CONNECTION_TIMEOUT):
        assert self.mcp_config, 'MCP config is required'
        envs = Env.load_env()
        mcp_config = self.mcp_config['mcpServers']
        for name, server in mcp_config.items():
            try:
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
                timeout = server.pop('timeout', timeout)
                await self.connect_to_server(
                    server_name=name, env=env_dict, timeout=timeout, **server)
            except Exception as e:
                new_eg = enhance_error(e, f'Connect `{name}` failed, details:')
                raise new_eg from e

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
        for name in list(self._server_stacks):
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
