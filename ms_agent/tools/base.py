# Copyright (c) ModelScope Contributors. All rights reserved.
import math
from abc import abstractmethod
from omegaconf import DictConfig
from typing import Any, Dict, Optional

from ms_agent.utils.constants import DEFAULT_OUTPUT_DIR

#: Return this from :attr:`ToolBase.max_output_chars` to declare that a tool
#: bounds its own output and must never be cut by the generic truncator.
SELF_MANAGED_OUTPUT = math.inf

#: Where to keep text from when an oversized output IS cut generically.
TRUNCATE_KEEP_HEAD = 'head'
TRUNCATE_KEEP_TAIL = 'tail'
TRUNCATE_KEEP_BOTH = 'both'


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

    # ---------------------------------------------------------------- output
    # Oversized tool output has to be bounded or it eats the context window,
    # but the generic way to bound it — keep the head and the tail, splice a
    # notice into the middle — assumes the payload is prose. Applied to a tool
    # that answers in JSON it lands inside a string literal and the result stops
    # parsing: measured on web_search, an 84k-char payload reached the model as
    # invalid JSON, so the model saw neither the results nor an error.
    #
    # A tool that already bounds itself therefore needs a way to say so. Same
    # protocol as qwen-code's `Tool.maxOutputChars` / `truncateKeep` (which in
    # turn mirrors Claude Code's per-tool `maxResultSizeChars`): the DEFAULT is
    # unchanged behaviour, and a tool opts in.

    @property
    def max_output_chars(self) -> Optional[float]:
        """Model-facing character budget for this tool's output.

        * ``None`` (default) — use the global ``MAX_TOOL_OUTPUT_LEN``.
        * :data:`SELF_MANAGED_OUTPUT` — the tool guarantees its own bound
          (paging, spilling to disk, …); never truncate it generically.
        * a number — this tool's own budget, used instead of the global one.

        Override in a subclass to opt in. Declaring a budget is a promise about
        SHAPE as much as size: a tool that returns structured data should keep
        itself under budget so the generic cut never has to run.
        """
        return None

    @property
    def truncate_keep(self) -> str:
        """Which end survives when this tool's output IS cut generically.

        ``'head'`` (a command's first output is the useful part), ``'tail'``
        (a long run whose verdict is last), or ``'both'`` (default).
        """
        return TRUNCATE_KEEP_BOTH

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
