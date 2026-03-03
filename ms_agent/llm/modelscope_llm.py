# Copyright (c) ModelScope Contributors. All rights reserved.
from ms_agent.llm.openai_llm import OpenAI
from ms_agent.utils.constants import get_service_config
from omegaconf import DictConfig


class ModelScope(OpenAI):

    def __init__(self, config: DictConfig):
        assert hasattr(
            config.llm, 'modelscope_api_key'
        ) and config.llm.modelscope_api_key is not None, 'Please provide `modelscope_api_key` in env or cmd.'
        super().__init__(
            config,
            base_url=config.llm.modelscope_base_url
            or get_service_config('modelscope').base_url,
            api_key=config.llm.modelscope_api_key)
