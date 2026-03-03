from typing import List, Union

from ms_agent.agent.code_agent import CodeAgent
from ms_agent.llm import Message


class CustomCodeAgent(CodeAgent):

    async def run(self, inputs: Union[str, List[Message]],
                  **kwargs) -> List[Message]:
        print(f'Code executed in {self.tag}!')
        if isinstance(inputs, str):
            # This example doesn't handle string inputs, so convert to a list of one message
            inputs = [Message(role='user', content=inputs)]
        inputs.append(Message(role='user', content='Calculate1+1'))
        return inputs
