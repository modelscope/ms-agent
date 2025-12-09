import os
from typing import List

import json
from ms_agent import LLMAgent
from ms_agent.llm import Message


class FileDesignAgent(LLMAgent):

    async def run(self, messages, **kwargs):
        query = '请读取对应文件并给出你的设计：'

        messages = [
            Message(role='system', content=self.config.prompt.system),
            Message(role='user', content=query),
        ]
        return await super().run(messages, **kwargs)

    async def on_task_end(self, messages: List[Message]):
        assert os.path.isfile(os.path.join(self.output_dir, 'file_design.txt'))
        with open(os.path.join(self.output_dir, 'file_design.txt'), 'r') as f:
            contents = json.load(f)

        with open(os.path.join(self.output_dir, 'modules.txt'), 'r') as f:
            modules = f.readlines()

        assert len(modules) == len(contents)

        _modules = [content['module'] for content in contents]
        modules = [module.strip() for module in _modules if module.strip()]
        assert not (set(modules) - set(_modules))
