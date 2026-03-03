# Copyright (c) ModelScope Contributors. All rights reserved.
from abc import ABC, abstractmethod
from typing import List

from ms_agent.llm.utils import Message
from ms_agent.utils.constants import DEFAULT_OUTPUT_DIR
from omegaconf import DictConfig


class Memory(ABC):
    """The memory refine tool"""

    def __init__(self, config):
        self.config = config
        self.output_dir = getattr(self.config, 'output_dir',
                                  DEFAULT_OUTPUT_DIR)
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
