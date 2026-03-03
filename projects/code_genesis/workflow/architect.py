import os
from typing import List

from ms_agent import LLMAgent
from ms_agent.llm import Message


class ArchitectureAgent(LLMAgent):

    async def run(self, messages, **kwargs):
        with open(os.path.join(self.output_dir, 'topic.txt'), 'r') as f:
            topic = f.read()

        with open(os.path.join(self.output_dir, 'user_story.txt'), 'r') as f:
            user_story = f.read()

        query = f'Topic: {topic}\nUser Story: {user_story}\nPlease give your design.'

        messages = [
            Message(role='system', content=self.config.prompt.system),
            Message(role='user', content=query),
        ]
        return await super().run(messages, **kwargs)

    async def on_task_end(self, messages: List[Message]):
        assert os.path.isfile(os.path.join(self.output_dir, 'framework.txt'))
        assert os.path.isfile(os.path.join(self.output_dir, 'protocol.txt'))
        assert os.path.isfile(os.path.join(self.output_dir, 'modules.txt'))
