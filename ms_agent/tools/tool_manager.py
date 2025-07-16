# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
from copy import copy
from typing import Any, Dict, List, Optional

import json
from ms_agent.llm.utils import Tool, ToolCall
from ms_agent.tools.base import ToolBase
from ms_agent.tools.filesystem_tool import FileSystemTool
from ms_agent.tools.mcp_client import MCPClient
from ms_agent.tools.split_task import SplitTask


class ToolManager:
    """Interacting with Agent class, hold all tools
    """

    def __init__(self, config, mcp_config: Optional[Dict[str, Any]] = None):
        self.config = config
        self.servers = MCPClient(config, mcp_config)
        self.extra_tools: List[ToolBase] = []
        self.has_split_task_tool = False
        if hasattr(config, 'tools') and hasattr(config.tools, 'split_task'):
            self.extra_tools.append(SplitTask(config))
        if hasattr(config, 'tools') and hasattr(config.tools, 'file_system'):
            self.extra_tools.append(FileSystemTool(config))
        self._tool_index = {}

    def register_tool(self, tool: ToolBase):
        self.extra_tools.append(tool)

    async def connect(self):
        await self.servers.connect()
        for tool in self.extra_tools:
            await tool.connect()
        await self.reindex_tool()

    async def cleanup(self):
        await self.servers.cleanup()
        for tool in self.extra_tools:
            await tool.cleanup()

    async def reindex_tool(self):

        def extend_tool(tool_ins: ToolBase, server_name: str,
                        tool_list: List[Tool]):
            for tool in tool_list:
                key = server_name + ':' + tool['tool_name']
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
            return await tool_ins.call_tool(
                server_name,
                tool_name=tool_name.split(':')[1],
                tool_args=tool_args)
        except Exception as e:
            return f'Tool calling failed: {str(e)}'

    async def parallel_call_tool(self, tool_list: List[ToolCall]):
        tasks = [self.single_call_tool(tool) for tool in tool_list]
        result = await asyncio.gather(*tasks)
        return result
