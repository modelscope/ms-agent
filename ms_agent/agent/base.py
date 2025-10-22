# Copyright (c) Alibaba, Inc. and its affiliates.
import os
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, List, Union

from ms_agent.llm import Message
from ms_agent.utils.constants import DEFAULT_RETRY_COUNT
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
