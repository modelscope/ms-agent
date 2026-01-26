import os

from ms_agent import LLMAgent
from ms_agent.llm import Message


class InstallAgent(LLMAgent):

    async def run(self, messages, **kwargs):
        with open(os.path.join(self.output_dir, 'topic.txt'), 'r') as f:
            topic = f.read()

        with open(os.path.join(self.output_dir, 'framework.txt'), 'r') as f:
            framework = f.read()

        with open(os.path.join(self.output_dir, 'file_design.txt'), 'r') as f:
            file_design = f.read()

        query = (
            f'Topic: {topic}\nFramework: {framework}\nFile Design: {file_design}\n'
            f'Your `workflow_dir` is {self.output_dir}, '
            'Please write dependency files and install dependencies.')

        messages = [
            Message(role='system', content=self.config.prompt.system),
            Message(role='user', content=query),
        ]
        return await super().run(messages, **kwargs)
