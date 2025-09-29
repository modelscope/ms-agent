# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import importlib
import inspect
import os
import sys
from copy import copy
from types import TracebackType
from typing import Any, Dict, List, Optional

import json
from ms_agent.llm.utils import Tool, ToolCall
from ms_agent.tools.base import ToolBase
from ms_agent.tools.filesystem_tool import FileSystemTool
from ms_agent.tools.mcp_client import MCPClient
from ms_agent.tools.split_task import SplitTask
from ms_agent.utils.constants import TOOL_PLUGIN_NAME

MAX_TOOL_NAME_LEN = int(os.getenv('MAX_TOOL_NAME_LEN', 64))
TOOL_CALL_TIMEOUT = int(os.getenv('TOOL_CALL_TIMEOUT', 30))


class ToolManager:
    """Interacting with Agent class, hold all tools
    """

    TOOL_SPLITER = '---'

    def __init__(self,
                 config,
                 mcp_config: Optional[Dict[str, Any]] = None,
                 mcp_client: Optional[MCPClient] = None,
                 **kwargs):
        self.config = config
        self.trust_remote_code = kwargs.get('trust_remote_code', False)

        self.extra_tools: List[ToolBase] = []
        self.has_split_task_tool = False
        if hasattr(config, 'tools') and hasattr(config.tools, 'split_task'):
            self.extra_tools.append(SplitTask(config))
        if hasattr(config, 'tools') and hasattr(config.tools, 'file_system'):
            self.extra_tools.append(FileSystemTool(config))
        self.tool_call_timeout = getattr(config, 'tool_call_timeout',
                                         TOOL_CALL_TIMEOUT)
        local_dir = self.config.local_dir if hasattr(self.config,
                                                     'local_dir') else None
        if hasattr(config, 'tools') and hasattr(config.tools,
                                                TOOL_PLUGIN_NAME):
            plugins = getattr(config.tools, TOOL_PLUGIN_NAME)
            for plugin in plugins:
                subdir = os.path.dirname(plugin)
                _plugin = os.path.basename(plugin)
                assert local_dir is not None, 'Using external py files, but local_dir cannot be found.'
                if subdir:
                    subdir = os.path.join(local_dir, str(subdir))
                if not self.trust_remote_code:
                    raise AssertionError(
                        '[External Code Found] Your config file contains external code, '
                        'instantiate the code may be UNSAFE, if you trust the code, '
                        'please pass `trust_remote_code=True` or `--trust_remote_code true`'
                    )
                if local_dir not in sys.path:
                    sys.path.insert(0, local_dir)
                if subdir and subdir not in sys.path:
                    sys.path.insert(0, subdir)
                plugin_file = importlib.import_module(_plugin)
                module_classes = {
                    name: cls
                    for name, cls in inspect.getmembers(
                        plugin_file, inspect.isclass)
                }
                for name, cls in module_classes.items():
                    # Find cls which base class is `ToolBase`
                    if issubclass(cls, ToolBase) and cls.__module__ == _plugin:
                        self.register_tool(cls(self.config))
        self._tool_index = {}

        # Used temporarily during async initialization; the actual client is managed in self.servers
        self.mcp_client = mcp_client
        self.mcp_config = mcp_config
        self._managed_client = mcp_client is None

    def register_tool(self, tool: ToolBase):
        self.extra_tools.append(tool)

    async def connect(self):
        if self.mcp_client and isinstance(self.mcp_client, MCPClient):
            self.servers = self.mcp_client
            await self.servers.add_mcp_config(self.mcp_config)
            self.mcp_config = self.servers.mcp_config
        else:
            self.servers = MCPClient(self.mcp_config, self.config)
            await self.servers.connect()
        for tool in self.extra_tools:
            await tool.connect()
        await self.reindex_tool()

    async def cleanup(self):
        if self._managed_client and self.servers:
            await self.servers.cleanup()
        self.servers = None
        for tool in self.extra_tools:
            await tool.cleanup()

    async def reindex_tool(self):

        def extend_tool(tool_ins: ToolBase, server_name: str,
                        tool_list: List[Tool]):
            for tool in tool_list:
                # Subtract the length of the tool name splitter
                max_server_len = MAX_TOOL_NAME_LEN - len(
                    tool['tool_name']) - len(self.TOOL_SPLITER)
                if len(server_name) > max_server_len:
                    key = f"{server_name[:max(0, max_server_len)]}{self.TOOL_SPLITER}{tool['tool_name']}"
                else:
                    key = f"{server_name}{self.TOOL_SPLITER}{tool['tool_name']}"
                assert key not in self._tool_index, f'Tool name duplicated {tool["tool_name"]}'
                tool = copy(tool)
                tool['tool_name'] = key
                self._tool_index[key] = (tool_ins, server_name, tool)

        mcps = await self.servers.get_tools()
        for server_name, tool_list in mcps.items():
            extend_tool(self.servers, server_name, tool_list)
        for extra_tool in self.extra_tools:
            tools = await extra_tool.get_tools()
            for server_name, tool_list in tools.items():
                extend_tool(extra_tool, server_name, tool_list)

    async def get_tools(self):
        return [value[2] for value in self._tool_index.values()]

    async def single_call_tool(self, tool_info: ToolCall):
        try:
            tool_name = tool_info['tool_name']
            tool_args = tool_info['arguments']
            while isinstance(tool_args, str):
                tool_args = json.loads(tool_args)
            assert tool_name in self._tool_index, f'Tool name {tool_name} not found'
            tool_ins, server_name, _ = self._tool_index[tool_name]
            response = await asyncio.wait_for(
                tool_ins.call_tool(
                    server_name,
                    tool_name=tool_name.split(self.TOOL_SPLITER)[1],
                    tool_args=tool_args),
                timeout=self.tool_call_timeout)
            return response
        except asyncio.TimeoutError:
            # TODO: How to get the information printed by the tool before hanging to return to the model?
            return f'Execute tool call timeout: {tool_info}'
        except Exception as e:
            return f'Tool calling failed: {tool_info}, details: {str(e)}'

    async def parallel_call_tool(self, tool_list: List[ToolCall]):
        tasks = [self.single_call_tool(tool) for tool in tool_list]
        result = await asyncio.gather(*tasks)
        return result

    async def __aenter__(self) -> 'ToolManager':

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass
