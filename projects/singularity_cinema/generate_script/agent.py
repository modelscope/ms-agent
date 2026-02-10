# Copyright (c) ModelScope Contributors. All rights reserved.
import os
from copy import deepcopy
from typing import List

from ms_agent import LLMAgent
from ms_agent.llm import LLM, Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class GenerateScript(LLMAgent):

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        extra = getattr(self.config, 'extra_requirement', '')
        if extra is None:
            extra = ''
        self.extra_req = extra
        os.makedirs(self.work_dir, exist_ok=True)

    def prepare_llm(self):
        """Initialize the LLM model from the configuration."""
        config = deepcopy(self.config)
        config.generation_config.temperature = 0.6
        config.generation_config.top_k = 50
        self.llm: LLM = LLM.from_config(self.config)

    def on_task_end(self, messages: List[Message]):
        script = os.path.join(self.work_dir, 'script.txt')
        title = os.path.join(self.work_dir, 'title.txt')
        assert os.path.isfile(script)
        assert os.path.isfile(title)
        return super().on_task_end(messages)

    async def run(self, query: str, **kwargs):
        script = os.path.join(self.work_dir, 'script.txt')
        title = os.path.join(self.work_dir, 'title.txt')
        query += self.extra_req
        messages = [
            Message(role='system', content=self.system),
            Message(role='user', content=query),
        ]
        if os.path.isfile(title) and os.path.isfile(script):
            return messages
        inputs = await super().run(messages, **kwargs)
        with open(os.path.join(self.work_dir, 'topic.txt'), 'w') as f:
            f.write(messages[1].content)
        return inputs
