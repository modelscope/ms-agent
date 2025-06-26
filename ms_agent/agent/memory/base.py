# Copyright (c) Alibaba, Inc. and its affiliates.
from abc import abstractmethod
from typing import List

from ms_agent.llm.utils import Message


class Memory:
    """The memory refine tool"""

    @abstractmethod
    async def run(self, messages: List[Message]) -> List[Message]:
        """Refine the messages

        Args:
            messages(`List[Message]`): The input messages

        Returns:
            The output messages
        """
        pass
