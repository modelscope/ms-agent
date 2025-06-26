# Copyright (c) Alibaba, Inc. and its affiliates.
from abc import abstractmethod
from typing import List, Union

from ms_agent.llm import Message


class Code:
    """A code class can be executed in a `CodeAgent` in a workflow"""

    def __init__(self, config=None):
        self.config = config

    @abstractmethod
    async def run(self, inputs: Union[str, List[Message]],
                  **kwargs) -> List[Message]:
        """Run the code

        Args:
            inputs(`Union[str, List[Message]]`): The inputs can be a prompt string,
                or a list of messages from the previous agent
            **kwargs:

        Returns:
            The messages to output to the next agent
        """
        pass
