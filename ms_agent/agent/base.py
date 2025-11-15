# Copyright (c) Alibaba, Inc. and its affiliates.
import os
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, List, Tuple, Union

from ms_agent.llm import Message
from ms_agent.utils import read_history, save_history
from ms_agent.utils.constants import DEFAULT_OUTPUT_DIR, DEFAULT_RETRY_COUNT
from omegaconf import DictConfig


class Agent(ABC):
    """
    Base class for all agents. Make sure your custom agents are derived from this class.
    Args:
        config (DictConfig): Pre-loaded configuration object.
    """

    retry_count = int(os.environ.get('AGENT_RETRY_COUNT', DEFAULT_RETRY_COUNT))

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        """
         Base class for all agents. Provides core functionality such as configuration loading,
         lifecycle handling via external code, and defining the interface for agent execution.

         The agent can be initialized either with a config object directly or by loading from a config directory or ID.
         If external code (e.g., custom handlers) is involved, the agent must be explicitly trusted via
         `trust_remote_code=True`.

         Base class for all agents. Make sure your custom agents are derived from this class.
         Args:
             config (DictConfig): Pre-loaded configuration object.
             tag (str): A custom tag for identifying this agent run.
             trust_remote_code (bool): Whether to allow loading of external code (e.g., custom handler modules).
         """
        self.config = config
        self.tag = tag
        self.trust_remote_code = trust_remote_code
        self.config.tag = tag
        self.config.trust_remote_code = trust_remote_code
        self.output_dir = getattr(self.config, 'output_dir',
                                  DEFAULT_OUTPUT_DIR)

    @abstractmethod
    async def run(
            self, inputs: Union[str, List[Message]], **kwargs
    ) -> Union[List[Message], AsyncGenerator[List[Message], Any]]:
        """
        Main method to execute the agent.

        This method should define the logic of how the agent processes input and generates output messages.

        Args:
            inputs (Union[str, List[Message]]): Input data for the agent. Can be a raw string prompt,
                                                or a list of previous interaction messages.
        Returns:
            List[Message]: A list of message objects representing the agent's response or interaction history.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError()

    def read_history(self, messages: Any,
                     **kwargs) -> Tuple[DictConfig, List[Message]]:
        return read_history(self.output_dir, self.tag)

    def save_history(self, messages: Any, **kwargs):
        if not getattr(self.config, 'save_history', True):
            return
        save_history(self.output_dir, self.tag, self.config, messages)

    def next_flow(self, idx: int) -> int:
        """Used in workflow, decide which agent goes next."""
        return idx + 1
