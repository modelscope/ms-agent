import os
from typing import List

from ms_agent import LLMAgent
from ms_agent.llm import Message


class ArchitectureAgent(LLMAgent):

    async def run(self, messages, **kwargs):
        query = '请读取对应文件并给出你的设计：'

        messages = [
            Message(role='system', content=self.config.prompt.system),
            Message(role='user', content=query),
        ]
        return await super().run(messages, **kwargs)

    async def on_task_end(self, messages: List[Message]):
        assert os.path.isfile(os.path.join(self.output_dir, 'framework.txt'))
        assert os.path.isfile(os.path.join(self.output_dir, 'protocol.txt'))
        assert os.path.isfile(os.path.join(self.output_dir, 'modules.txt'))
