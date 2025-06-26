# Copyright (c) Alibaba, Inc. and its affiliates.
from abc import abstractmethod
from typing import List

from ms_agent.agent.runtime import Runtime
from ms_agent.llm.utils import Message
from pydantic import ConfigDict


class Planer:
    """A planer to guide the agent"""

    def __init__(self, config: ConfigDict):
        self.config = config

    @abstractmethod
    async def make_plan(self, runtime: Runtime,
                        messages: List[Message]) -> List[Message]:
        """Make an initial plan

        Args:
            runtime (`Runtime`): The runtime
            messages (`List[Message]`): The input messages
        """
        pass

    @abstractmethod
    async def update_plan(self, runtime: Runtime,
                          messages: List[Message]) -> List[Message]:
        """Update the plan

        Args:
            runtime (`Runtime`): The runtime
            messages (`List[Message]`): The input messages
        """
        pass
