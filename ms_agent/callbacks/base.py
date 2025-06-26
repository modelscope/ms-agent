# Copyright (c) Alibaba, Inc. and its affiliates.
from typing import List

from ms_agent.agent.runtime import Runtime
from ms_agent.llm.utils import Message
from omegaconf import DictConfig


class Callback:

    def __init__(self, config: DictConfig):
        self.config = config

    async def on_task_begin(self, runtime: Runtime,
                            messages: List[Message]) -> None:
        """Called when a task begins.

        Args:
            runtime: The runtime.
            messages: The messages, you can modify it in-place.

        Returns:
            None.
        """
        pass

    async def on_generate_response(self, runtime: Runtime,
                                   messages: List[Message]):
        """Called before LLM generates response.

        Args:
            runtime: The runtime.
            messages: The messages, you can modify it in-place.

        Returns:
            None.
        """
        pass

    async def after_generate_response(self, runtime: Runtime,
                                      messages: List[Message]):
        """Called after LLM generates response.

        Args:
            runtime: The runtime.
            messages: The messages, you can modify it in-place.

        Returns:
            None.
        """
        pass

    async def on_tool_call(self, runtime: Runtime, messages: List[Message]):
        """Called before calling tools.

        Args:
            runtime: The runtime.
            messages: The messages, you can modify it in-place.

        Returns:
            None.
        """
        pass

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        """Called after calling tools.

        Args:
            runtime: The runtime.
            messages: The messages, you can modify it in-place.

        Returns:
            None.
        """
        pass

    async def on_task_end(self, runtime: Runtime, messages: List[Message]):
        """Called when a task finishes.

        Args:
            runtime: The runtime.
            messages: The messages, you can modify it in-place.

        Returns:
            None.
        """
        pass

    async def on_split_task(self, config: DictConfig):
        """Called when a subtask begins, this will be called once for each subtask.

        Args:
            config: The config for the subtask, prompt.system and prompt.query is valid, you can modify it in-place.

        Returns:
            None.
        """
        pass
