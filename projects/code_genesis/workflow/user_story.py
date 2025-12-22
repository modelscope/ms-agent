import os
from typing import List

from ms_agent import LLMAgent
from ms_agent.llm import Message


class SplitModuleAgent(LLMAgent):

    async def on_task_end(self, messages: List[Message]):
        assert os.path.isfile(os.path.join(self.output_dir, 'user_story.txt'))
        topic = ''
        for message in messages:
            if message.role == 'user':
                topic = message.content
                break
        assert topic
        with open(os.path.join(self.output_dir, 'topic.txt'), 'w') as f:
            f.write(topic)
