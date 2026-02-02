import os
from typing import List

from ms_agent import LLMAgent
from ms_agent.llm import Message


class OrchestratorAgent(LLMAgent):
    """Master Orchestrator - Coordinates file writing order based on project requirements"""

    async def run(self, user_input, **kwargs):
        query = (
            f'Project Requirements: {user_input}\n\n'
            f'Please generate all planning documents: '
            f'topic.txt, user_story.txt, framework.txt, protocol.txt, file_design.txt, and file_order.txt'
        )

        messages = [
            Message(role='system', content=self.config.prompt.system),
            Message(role='user', content=query),
        ]
        return await super().run(messages, **kwargs)

    async def on_task_end(self, messages: List[Message]):
        assert os.path.isfile(os.path.join(self.output_dir, 'topic.txt'))
        assert os.path.isfile(os.path.join(self.output_dir, 'user_story.txt'))
        assert os.path.isfile(os.path.join(self.output_dir, 'framework.txt'))
        assert os.path.isfile(os.path.join(self.output_dir, 'protocol.txt'))
        assert os.path.isfile(os.path.join(self.output_dir, 'file_design.txt'))
        assert os.path.isfile(os.path.join(self.output_dir, 'file_order.txt'))
