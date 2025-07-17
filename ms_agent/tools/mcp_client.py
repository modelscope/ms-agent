# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import os
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Literal, Optional

from mcp import ClientSession, ListToolsResult, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from ms_agent.config import Config
from ms_agent.config.env import Env
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()

EncodingErrorHandler = Literal['strict', 'ignore', 'replace']

DEFAULT_ENCODING = 'utf-8'
DEFAULT_ENCODING_ERROR_HANDLER: EncodingErrorHandler = 'strict'

DEFAULT_HTTP_TIMEOUT = 5
DEFAULT_SSE_READ_TIMEOUT = 60 * 5
TOOL_CALL_TIMEOUT = os.getenv('TOOL_CALL_TIMEOUT', 15)


class MCPClient(ToolBase):
    """MCP client for all mcp tools

    This class can hold multiple mcp servers.

    Args:
        config(`DictConfig`): The config instance.
        mcp_config(`Optional[Dict[str, Any]]`): Extra mcp servers in json format.
    """

    def __init__(self,
                 config: DictConfig,
                 mcp_config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.sessions: Dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()
        self.mcp_config: Dict[str, Dict[
            str, Any]] = Config.convert_mcp_servers_to_json(config)
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
                return f'execute error: {sep.join(response.content)}'
            else:
                item_list = []
                for item in response.content:
                    item_list.append(item.text)
                return f'execute error: {sep.join(item_list)}'
        for content in response.content:
            if content.type == 'text':
                texts.append(content.text)
        return '\n\n'.join(texts)

    async def get_tools(self) -> Dict:
        tools = {}
        for key, session in self.sessions.items():
            tools[key] = []
            response = await session.list_tools()
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
        command = kwargs.get('command')
        url = kwargs.get('url')
        session_kwargs = kwargs.get('session_kwargs')
        if url:
            # transport: 'sse'
            sse_transport = await self.exit_stack.enter_async_context(
                sse_client(
                    url, kwargs.get('headers'),
                    kwargs.get('timeout', DEFAULT_HTTP_TIMEOUT),
                    kwargs.get('sse_read_timeout', DEFAULT_SSE_READ_TIMEOUT)))
            read, write = sse_transport
            session_kwargs = session_kwargs or {}
            session = await self.exit_stack.enter_async_context(
                ClientSession(read, write, **session_kwargs))

            await session.initialize()
            # Store session
            self.sessions[server_name] = session
            # List available tools
            self.print_tools(server_name, await session.list_tools())
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
            await session.initialize()

            # Store session
            self.sessions[server_name] = session
            self.print_tools(server_name, await session.list_tools())
        else:
            raise ValueError(
                "'url' or 'command' parameter is required for connection")
        return server_name

    async def connect(self):
        assert self.mcp_config, 'MCP config is required'
        envs = Env.load_env()
        mcp_config = self.mcp_config['mcpServers']
        for name, server in mcp_config.items():
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
