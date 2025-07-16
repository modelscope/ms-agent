# Copyright (c) Alibaba, Inc. and its affiliates.
import os
from abc import abstractmethod
from typing import List, Optional, Type

import json
from ms_agent.agent import Agent, CodeAgent, LLMAgent
from ms_agent.config import Config
from ms_agent.llm import Message
from ms_agent.utils.utils import str_to_md5
from omegaconf import DictConfig, OmegaConf

from modelscope.hub.utils.utils import get_cache_dir


class Workflow:
    """Base class for workflows that define a sequence of agent-based processing steps.

    A workflow manages the execution flow of multiple agents, each responsible for
    a specific task in the overall process. Subclasses should implement the `run` method.
    """

    @staticmethod
    def find_agent(type: str) -> Optional[Type[Agent]]:
        """Find and return an Agent class by its type name.

        Args:
            type (`str`): The name of the agent type to find.

        Returns:
            Optional[Type[Agent]]: The corresponding Agent class if found, otherwise None.
        """
        if type == 'LLMAgent':
            return LLMAgent
        elif type == 'CodeAgent':
            return CodeAgent
        return None

    @abstractmethod
    async def run(self, inputs, **kwargs):
        pass
