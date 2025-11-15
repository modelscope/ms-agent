# Copyright (c) Alibaba, Inc. and its affiliates.
from typing import Any, List, Union

from ms_agent.llm import Message
from omegaconf import DictConfig

from .base import Agent


class CodeAgent(Agent):
    """A code class can be executed in a `CodeAgent` in a workflow"""

    AGENT_NAME = 'CodeAgent'

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.load_cache = kwargs.get('load_cache', False)

    async def run(self, inputs: Union[str, List[Message]],
                  **kwargs) -> List[Message]:
        """Run the external code. Default implementation here does nothing.

        Args:
            inputs(`Union[str, List[Message]]`): The inputs can be a prompt string,
                or a list of messages from the previous agent

        Returns:
            The messages to output to the next agent
        """
        _config = None
        _messages = None
        if self.load_cache:
            _config, _messages = self.read_history(inputs)
        if _config is not None and _messages is not None:
            self.config = _config
            return _messages
        messages = await self.execute_code(inputs, **kwargs)
        self.save_history(messages, **kwargs)
        return messages

    async def execute_code(self, inputs: Union[str, List[Message]],
                           **kwargs) -> List[Message]:
        return inputs
