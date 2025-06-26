# Copyright (c) Alibaba, Inc. and its affiliates.
from abc import abstractmethod
from typing import Any, Dict, List, Optional

from ms_agent.config import Config
from omegaconf import DictConfig

from .utils import Message, Tool


class LLM:

    def __init__(self, config: DictConfig):
        """Initialize the model.

        Args:
            config: A omegaconf.DictConfig object.
        """
        self.config = config

    @abstractmethod
    def generate(self,
                 messages: List[Message],
                 model: Optional[str] = None,
                 tools: Optional[List[Tool]] = None,
                 **kwargs) -> Any:
        """Generate response by the given messages.

        Args:
            messages(`List[Message]`): The previous messages.
            model(`Optional[str]`): The model to use, use model in config if not specified
            tools(`List[Tool]`): The tools to use.
            **kwargs: Extra generation arguments.

        Returns:
            The response.
        """
        pass

    @classmethod
    def from_task(cls,
                  config_dir_or_id: str,
                  *,
                  env: Optional[Dict[str, str]] = None) -> Any:
        """Instantiate an LLM instance.

        Args:
            config_dir_or_id(`str`): The local task directory or id in the modelscope repository.
            env(`Optional[Dict[str, str]]`): The extra environment variables except ones already been included
                in the environment or in the `.env` file.

        Returns:
            The LLM instance.
        """
        config = Config.from_task(config_dir_or_id, env)
        return cls.from_config(config)

    @classmethod
    def from_config(cls, config: DictConfig) -> Any:
        """Instantiate an LLM instance.

        Args:
            config(`DictConfig`): The omegaconf.DictConfig object.

        Returns:
            The LLM instance.
        """
        from .model_mapping import all_services_mapping
        assert config.llm.service in all_services_mapping
        return all_services_mapping[config.llm.service](config)
