import os
import sys
from typing import List, OrderedDict

from coding import CodingAgent
from ms_agent import LLMAgent
from ms_agent.llm import Message
from ms_agent.memory.condenser.refine_condenser import RefineCondenser
from ms_agent.utils import get_logger
from ms_agent.utils.constants import DEFAULT_TAG
from omegaconf import DictConfig

logger = get_logger()


class RefineAgent(LLMAgent):

    def __init__(self,
                 config: DictConfig = DictConfig({}),
                 tag: str = DEFAULT_TAG,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.refine_condenser = RefineCondenser(config)

    async def condense_memory(self, messages):
        return await self.refine_condenser.run([m for m in messages])

    async def run(self, messages, **kwargs):
        with open(os.path.join(self.output_dir, 'topic.txt')) as f:
            topic = f.read()
        with open(os.path.join(self.output_dir, 'framework.txt')) as f:
            framework = f.read()
        with open(os.path.join(self.output_dir, 'protocol.txt')) as f:
            protocol = f.read()
        with open(os.path.join(self.output_dir, 'tasks.txt')) as f:
            file_info = f.read()

        file_relation = OrderedDict()
        CodingAgent.refresh_file_status(self, file_relation)
        CodingAgent.construct_file_information(self, file_relation, False)
        messages = [
            Message(role='system', content=self.config.prompt.system),
            Message(
                role='user',
                content=f'Original requirements (topic.txt): {topic}\n'
                f'Tech stack (framework.txt): {framework}\n'
                f'Communication protocol (protocol.txt): {protocol}\n'
                f'File list:\n{file_info}\n'
                f'Your shell tool workspace_dir is {self.output_dir}; '
                f'all tools should use this directory as the current working directory.\n'
                f'Python executable: {sys.executable}\n'
                f'Please refine the project and deploy it to EdgeOne Pages:'),
        ]
        return await super().run(messages, **kwargs)

    async def after_tool_call(self, messages: List[Message]):
        has_tool_call = len(messages[-1].tool_calls) > 0
        if not has_tool_call:
            query = input('>>>')
            messages.append(Message(role='user', content=query))
