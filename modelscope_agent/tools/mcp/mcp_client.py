import os
import shutil
from contextlib import AsyncExitStack
from types import TracebackType
from datetime import timedelta
from typing import Any, Dict, Literal

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client


EncodingErrorHandler = Literal['strict', 'ignore', 'replace']

DEFAULT_ENCODING = 'utf-8'
DEFAULT_ENCODING_ERROR_HANDLER: EncodingErrorHandler = 'strict'

DEFAULT_HTTP_TIMEOUT = 5
DEFAULT_SSE_READ_TIMEOUT = 60 * 5

DEFAULT_STREAMABLE_HTTP_TIMEOUT = timedelta(seconds=30)
DEFAULT_STREAMABLE_HTTP_SSE_READ_TIMEOUT = timedelta(seconds=60 * 5)

class MCPClient:

    def __init__(self, mcp_config: Dict[str, Any]):
        self.sessions: Dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()
        self.mcp = mcp_config

    @staticmethod
    def parse_config(mcp_servers: Dict[str, Any]) -> Dict[str, Any]:
        config_json = {}
        for mcp_server_name, mcp_content in mcp_servers.items():
            if 'command' in mcp_content:
                command = mcp_content['command']
                if 'fastmcp' in command:
                    command = shutil.which('fastmcp')
                    if not command:
                        raise FileNotFoundError(
                            f'Cannot locate the fastmcp command file for {mcp_server_name}, '
                            f'please install fastmcp by `pip install fastmcp`')
                    mcp_content['command'] = command
                if 'uv' in command:
                    command = shutil.which('uv')
                    if not command:
                        raise FileNotFoundError(
                            'Cannot locate the uv command, please consider your installation of Python.'
                        )

                args = mcp_content['args']
                for idx in range(len(args)):
                    if '/path/to' in args[idx]:
                        # TODO: 对stdio的工具需要进一步整合
                        args[idx] = args[idx].replace('/path/to', os.getcwd())
            config_json[mcp_server_name] = mcp_content

        return config_json

    async def connect_to_server(self, server_name: str, **kwargs):
        print(f'kwargs: {kwargs}')
        transport = kwargs.get('transport')
        command = kwargs.get('command')
        url = kwargs.get('url')
        session_kwargs = kwargs.get('session_kwargs')
        if not url and not command:
            raise ValueError(
                "'url' or 'command' parameter is required for connection")
        if url:
            if transport == 'streamable_http':
                try:
                    from mcp.client.streamable_http import streamablehttp_client
                except ImportError:
                    raise ImportError(
                        "Could not import streamablehttp_client. ",
                        "To use streamable http connections, please upgrade the required dependency with: ",
                        "'pip install -U mcp'",
                    ) from None
                httpx_client_factory = kwargs.get("httpx_client_factory")
                other_kwargs = {}
                if httpx_client_factory is not None:
                    other_kwargs['httpx_client_factory'] = httpx_client_factory
                streamable_transport = await self.exit_stack.enter_async_context(
                    streamablehttp_client(
                        url,
                        headers=kwargs.get('headers'),
                        timeout=kwargs.get('timeout', DEFAULT_HTTP_TIMEOUT),
                        sse_read_timeout=kwargs.get("sse_read_timeout", DEFAULT_STREAMABLE_HTTP_SSE_READ_TIMEOUT),
                        **other_kwargs
                    )
                )
                read, write, _ = streamable_transport
                session_kwargs = session_kwargs or {}
                session = await self.exit_stack.enter_async_context(
                    ClientSession(read, write, **session_kwargs))
            elif transport == 'websocket':
                try:
                    from mcp.client.websocket import websocket_client
                except ImportError:
                    raise ImportError(
                        "Could not import websocket_client. ",
                        "To use Websocket connections, please install the required dependency with: ",
                        "'pip install mcp[ws]' or 'pip install websockets'",
                    ) from None
                websocket_transport = await self.exit_stack.enter_async_context(
                    websocket_client(url)
                )
                read, write = websocket_transport
                session_kwargs = session_kwargs or {}
                session = await self.exit_stack.enter_async_context(
                    ClientSession(read, write, **session_kwargs))
            else:
                sse_transport = await self.exit_stack.enter_async_context(
                    sse_client(
                        url, kwargs.get('headers'),
                        kwargs.get('timeout', DEFAULT_HTTP_TIMEOUT),
                        kwargs.get('sse_read_timeout', DEFAULT_SSE_READ_TIMEOUT)))
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

            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params))

            stdio, write = stdio_transport
            session = await self.exit_stack.enter_async_context(
                ClientSession(stdio, write))

        await session.initialize()
        # Store session
        self.sessions[server_name] = session

        # List available tools
        response = await session.list_tools()
        tools = response.tools
        print(f"\nConnected to server '{server_name}' with tools:",
              [tool.name for tool in tools])

        return server_name

    async def list_servers(self):
        """List all connected servers"""
        if not self.sessions:
            print('No servers connected')
            return

        print('\nConnected servers:')
        for name in self.sessions.keys():
            marker = '* ' if name == self.current_server else '  '
            print(f'{marker}{name}')

    async def call_tool(self, server_name: str, tool_name: str,
                        tool_args: dict):
        response = await self.sessions[server_name].call_tool(
            tool_name, tool_args)
        texts = []
        for content in response.content:
            if content.type == 'text':
                texts.append(content.text)
        if texts:
            return '\n\n'.join(texts)
        else:
            return 'execute error'

    async def connect_all_servers(self):
        mcp_config = self.mcp['mcpServers']
        config = self.parse_config(mcp_config)

        print(f'config: {config}')
        for tool in mcp_config:
            cmd = config[tool]
            env_dict = cmd.pop('env', {})
            env_dict = {
                key: value if value else os.environ.get(key, '')
                for key, value in env_dict.items()
            }
            await self.connect_to_server(server_name=tool, env=env_dict, **cmd)

    async def get_tools(self) -> Dict:
        tools = {}
        for key, session in self.sessions.items():
            tools[key] = []
            response = await session.list_tools()
            tools[key].extend(response.tools)
        return tools

    async def __aenter__(self) -> 'MCPClient':
        try:
            await self.connect_all_servers()
            return self
        except Exception:
            await self.exit_stack.aclose()
            raise

    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.exit_stack.aclose()
