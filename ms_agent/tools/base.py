# Copyright (c) Alibaba, Inc. and its affiliates.
from abc import abstractmethod
from typing import Any, Dict, List


class ToolBase:
    """The base class for all tools.

    Note: A subclass of ToolBase can manage multiple tools or servers.
    """

    def __init__(self, config):
        self.config = config

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

    @abstractmethod
    async def get_tools(self) -> Dict[str, Any]:
        """List tools available.

        Returns:
            A Dict of {server_name: tools}
        """
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
