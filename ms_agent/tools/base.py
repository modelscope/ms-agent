# Copyright (c) Alibaba, Inc. and its affiliates.
from abc import abstractmethod
from typing import Any, Dict

from ms_agent.utils.constants import DEFAULT_OUTPUT_DIR
from omegaconf import DictConfig


class ToolBase:
    """The base class for all tools.

    Note: A subclass of ToolBase can manage multiple tools or servers.
    """

    def __init__(self, config):
        self.config = config
        self.exclude_functions = []
        self.include_functions = []
        self.output_dir = getattr(self.config, 'output_dir',
                                  DEFAULT_OUTPUT_DIR)

    def exclude_func(self, tool_config: DictConfig):
        if tool_config is not None:
            self.exclude_functions = getattr(tool_config, 'exclude', [])
            self.include_functions = getattr(tool_config, 'include', [])

        assert (not self.exclude_functions) or (
            not self.include_functions
        ), 'Set either `include` or `exclude` in tools config.'

    @abstractmethod
    async def connect(self) -> None:
        """Connect the tool.

        Returns:
            None
        Raises:
            Exceptions if anything goes wrong.
        """
        pass

    async def cleanup(self) -> None:
        """Disconnect and clean up the tool.

        Returns:
            None
        Raises:
            Exceptions if anything goes wrong.
        """
        pass

    async def get_tools(self) -> Dict[str, Any]:
        """List tools available.

        Returns:
            A Dict of {server_name: tools}
        """
        tools = await self._get_tools_inner()
        output = {}
        for server, tool_list in tools.items():
            available_tools = []
            for tool in tool_list:
                if self.include_functions:
                    if tool['tool_name'] in self.include_functions:
                        available_tools.append(tool)
                elif self.exclude_functions:
                    if tool['tool_name'] not in self.exclude_functions:
                        available_tools.append(tool)
                else:
                    available_tools.append(tool)
            output[server] = available_tools
        return output

    @abstractmethod
    async def _get_tools_inner(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        """Call a tool.

        Args:
            server_name(`str`): The server name of the tool.
            tool_name: The tool name.
            tool_args: The tool args in dict format.

        Returns:
            Calling result in string format.
        """
        pass
