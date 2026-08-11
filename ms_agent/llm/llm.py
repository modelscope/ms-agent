# Copyright (c) ModelScope Contributors. All rights reserved.
import os
from abc import abstractmethod
from omegaconf import DictConfig
from typing import Any, Dict, List, Optional

from ms_agent.config import Config
from ..utils.constants import DEFAULT_RETRY_COUNT
from .utils import Message, Tool


class LLM:

    retry_count = int(os.environ.get('LLM_RETRY_COUNT', DEFAULT_RETRY_COUNT))

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

        Routing (see ``ms_agent/llm/router.py``):
            - ``config.llm.use_provider_router: true``  -> always use the
              data-driven provider layer.
            - unset -> the legacy services (modelscope/openai/anthropic/
              dashscope) keep the old hard-coded path (zero behavior change),
              while any other provider the registry knows (deepseek, zhipu/glm,
              kimi/moonshot, minimax, google, openrouter, ...) is auto-routed to
              the provider layer so it works with its own credentials.
            - ``config.llm.use_provider_router: false`` -> force the legacy path
              for every service (explicit opt-out).
        """
        router_flag = config.llm.get('use_provider_router', None)
        if router_flag:
            from .router import ProviderRouter
            return ProviderRouter().create(config)

        from .model_mapping import OpenAI, all_services_mapping
        service = config.llm.get('service')

        # Auto-route providers the legacy mapping cannot serve but the registry
        # knows. Unset (None) enables this; an explicit False opts out.
        if router_flag is None and service and service not in all_services_mapping:
            from .spec import get_registry
            if get_registry().get(service) is not None:
                from .router import ProviderRouter
                return ProviderRouter().create(config)

        if service in all_services_mapping:
            return all_services_mapping[service](config)
        else:
            return OpenAI(config)
