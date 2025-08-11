# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import os
from contextlib import AsyncExitStack
from datetime import timedelta
from os import environb
from types import TracebackType
from typing import Any, Dict, List, Literal, Optional, Union

from mcp import ClientSession, ListToolsResult, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from ms_agent.config import Config
from ms_agent.config.env import Env
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger
from omegaconf import DictConfig, ListConfig

logger = get_logger()

EncodingErrorHandler = Literal['strict', 'ignore', 'replace']

DEFAULT_ENCODING = 'utf-8'
DEFAULT_ENCODING_ERROR_HANDLER: EncodingErrorHandler = 'strict'

DEFAULT_HTTP_TIMEOUT = 5
DEFAULT_SSE_READ_TIMEOUT = 60 * 5
TOOL_CALL_TIMEOUT = os.getenv('TOOL_CALL_TIMEOUT', 30)

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
        config: Union[DictConfig, ListConfig, None] = None,
    ):
        super().__init__(config)
        self.sessions: Dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()
        self.mcp_config: Dict[str, Dict[str, Any]] = dict()
        if config is not None:
            self.mcp_config = Config.convert_mcp_servers_to_json(config)
        self._exclude_functions = {}
        if mcp_config is not None:
            self.mcp_config.update(mcp_config)

    async def call_tool(self, server_name: str, tool_name: str,
                        tool_args: dict):
        try:
            response = await asyncio.wait_for(
                self.sessions[server_name].call_tool(tool_name, tool_args),
                timeout=TOOL_CALL_TIMEOUT)
        except asyncio.TimeoutError:
            # TODO: How to get the information printed by the tool before hanging to return to the model?
            return f'execute tool call timeout: [{server_name}]{tool_name}, args: {tool_args}'

        texts = []
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
        return '\n\n'.join(texts)

    async def get_tools(self) -> Dict:
        tools = {}
        error = dict()
        for key, session in self.sessions.items():
            try:
                tools[key] = []
                response = await asyncio.wait_for(
                    session.list_tools(), timeout=TOOL_CALL_TIMEOUT)
                _session_tools = response.tools
                exclude = []
                if key in self._exclude_functions:
                    exclude = self._exclude_functions[key]
                _session_tools = [
                    t for t in _session_tools if t.name not in exclude
                ]
                _session_tools = [
                    Tool(
                        tool_name=t.name,
                        server_name=key,
                        description=t.description,
                        parameters=t.inputSchema) for t in _session_tools
                ]
                tools[key].extend(_session_tools)
            except asyncio.TimeoutError:
                error[key] = 'timeout'
            except BaseException as exc:
                error[key] = exc
        if error:
            error_messages = '; '.join(f'`{srv}`: {msg}'
                                       for srv, msg in error.items())
            raise ConnectionError(
                f'get MCP tool failed for: {error_messages}. Please check MCP servers and retry.'
            )
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

    async def connect_to_server(self, server_name: str, **kwargs):
        logger.info(f'connect to {server_name}')
        # transport: stdio, sse, streamable_http, websocket
        transport = kwargs.get('transport') or kwargs.get('type')
        command = kwargs.get('command')
        url = kwargs.get('url')
        session_kwargs = kwargs.get('session_kwargs')
        if url:
            if transport == 'streamable_http':
                try:
                    from mcp.client.streamable_http import streamablehttp_client
                except ImportError:
                    raise ImportError(
                        'Could not import streamablehttp_client. '
                        'To use streamable http connections, please upgrade to the latest version of mcp with: '
                        "'pip install -U mcp'") from None
                httpx_client_factory = kwargs.get('httpx_client_factory')
                other_kwargs = {}
                if httpx_client_factory is not None:
                    other_kwargs['httpx_client_factory'] = httpx_client_factory
                streamable_transport = await self.exit_stack.enter_async_context(
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

            elif transport == 'websocket':
                try:
                    from mcp.client.websocket import websocket_client
                except ImportError:
                    raise ImportError(
                        'Could not import websocket_client. '
                        'To use Websocket connections, please install the required dependency with: '
                        "'pip install mcp[ws]' or 'pip install websockets'"
                    ) from None
                websocket_transport = await self.exit_stack.enter_async_context(
                    websocket_client(url))
                read, write = websocket_transport

            else:
                sse_transport = await self.exit_stack.enter_async_context(
                    sse_client(
                        url, kwargs.get('headers'),
                        kwargs.get('timeout', DEFAULT_HTTP_TIMEOUT),
                        kwargs.get('sse_read_timeout',
                                   DEFAULT_SSE_READ_TIMEOUT)))
                read, write = sse_transport

            session_kwargs = session_kwargs or {}
            session = await self.exit_stack.enter_async_context(
                ClientSession(read, write, **session_kwargs))

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

            stdio, write = await self.exit_stack.enter_async_context(
                stdio_client(server_params))
            session = await self.exit_stack.enter_async_context(
                ClientSession(stdio, write))
        else:
            raise ValueError(
                "'url' or 'command' parameter is required for connection")

        await session.initialize()
        # Store session
        self.sessions[server_name] = session
        self.print_tools(server_name, await session.list_tools())
        return server_name

    async def connect(self):
        assert self.mcp_config, 'MCP config is required'
        envs = Env.load_env()
        mcp_config = self.mcp_config['mcpServers']
        error = dict()
        for name, server in mcp_config.items():
            try:
                env_dict = server.pop('env', {})
                env_dict = {
                    key: value if value else envs.get(key, '')
                    for key, value in env_dict.items()
                }
                if 'exclude' in server:
                    self._exclude_functions[name] = server.pop('exclude')
                await self.connect_to_server(
                    server_name=name, env=env_dict, **server)
            except BaseException as exc:
                error[name] = str(exc)
        if error:
            error_messages = '; '.join(f'`{srv}`: {msg}'
                                       for srv, msg in error.items())
            raise ConnectionError(
                f'MCP connections failed for: {error_messages}. Please check mcp configurations and retry.'
            )

    async def add_mcp_config(self, mcp_config: Dict[str, Dict[str, Any]]):
        if mcp_config is None:
            return
        new_mcp_config = mcp_config['mcpServers']
        servers = self.mcp_config['mcpServers']
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
                    self._exclude_functions[name] = server.pop('exclude')
                await self.connect_to_server(
                    server_name=name, env=env_dict, **server)

    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()

    async def __aenter__(self) -> 'MCPClient':
        try:
            await self.connect()
            return self
        except Exception:
            await self.exit_stack.aclose()
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.exit_stack.aclose()
