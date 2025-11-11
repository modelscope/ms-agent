# Copyright (c) Alibaba, Inc. and its affiliates.
from typing import List, Union

from ms_agent.llm import Message

from .base import Agent


class CodeAgent(Agent):
    """A code class can be executed in a `CodeAgent` in a workflow"""

    AGENT_NAME = 'CodeAgent'

    async def run(self, inputs: Union[str, List[Message]],
                  **kwargs) -> List[Message]:
        """Run the external code. Default implementation here does nothing.

        Args:
            inputs(`Union[str, List[Message]]`): The inputs can be a prompt string,
                or a list of messages from the previous agent

        Returns:
            The messages to output to the next agent
        """
        return inputs
