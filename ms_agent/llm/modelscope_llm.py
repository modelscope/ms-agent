# Copyright (c) Alibaba, Inc. and its affiliates.
from ms_agent.llm.openai_llm import OpenAI
from omegaconf import DictConfig


class ModelScope(OpenAI):

    def __init__(self, config: DictConfig):
        super().__init__(
            config,
            base_url=config.llm.modelscope_base_url,
            api_key=config.llm.modelscope_api_key)
