import os
from typing import List

import json
from ms_agent import LLMAgent
from ms_agent.llm import Message


class FileDesignAgent(LLMAgent):

    async def run(self, messages, **kwargs):
        query = '请读取file_design.txt并输出file_order.txt:'

        messages = [
            Message(role='system', content=self.config.prompt.system),
            Message(role='user', content=query),
        ]
        return await super().run(messages, **kwargs)

    async def on_task_end(self, messages: List[Message]):
        assert os.path.isfile(os.path.join(self.output_dir, 'file_order.txt'))
        with open(os.path.join(self.output_dir, 'file_order.txt'), 'r') as f:
            file_order = json.load(f)

        with open(os.path.join(self.output_dir, 'file_design.txt'), 'r') as f:
            file_design = json.load(f)

        files1 = set()
        files2 = set()
        for file in file_order:
            files1.update(file['files'])

        for file in file_design:
            names = [f['name'] for f in file['files']]
            files2.update(names)

        assert len(files1) == len(files2)
        assert not (files1 - files2)
