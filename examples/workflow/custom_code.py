from typing import Union, List

from ms_agent.agent.code_agent import Code
from ms_agent.llm import Message


class CustomCodeAgent(Code):

    async def run(self, inputs: Union[str, List[Message]], **kwargs) -> List[Message]:
        print(f'Code executed in {self.tag}!')
        inputs.append(Message(role='user', content='Calculate1+1'))