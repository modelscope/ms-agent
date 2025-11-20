# Copyright (c) Alibaba, Inc. and its affiliates.
from abc import ABC, abstractmethod
from typing import List

from ms_agent.llm.utils import Message
from omegaconf import DictConfig


class Memory(ABC):
    """The memory refine tool"""

    def __init__(self, config):
        self.config = config
        self.base_config = None

    @abstractmethod
    async def run(self, messages: List[Message]) -> List[Message]:
        """Refine the messages

        Args:
            messages(`List[Message]`): The input messages

        Returns:
            The output messages
        """
        pass

    def set_base_config(self, config: DictConfig):
        """Set the config containing all information

        Args:
            config(`DictConfig`): The config containing all information
        """
        self.base_config = config
