import re
from copy import deepcopy
from typing import List

from ms_agent.utils import get_logger
from omegaconf import DictConfig

from ..llm import LLM, Message
from ..tools import SplitTask
from .base import Memory

logger = get_logger()


class Diversity(Memory):

    div_system1 = """You are an inspiration bot. You will be given an original requirement, and you need to provide keywords that you associate with it. The keywords must meet the following conditions:

1. The keywords you provide should be terms, such as "security", "independent module", "aesthetics", "style", "examples", etc.
2. The keywords you provide should have varying degrees of relevance to the original requirement, ranging from 100% relevant to 1% relevant
3. Keywords should cover all aspects, including technical, non-technical, design, scalability, scenarios, and more
4. You need to carefully consider both the task itself and the topic, as this is very helpful for completing tasks.
    For example:
    * Make a video of LLM: consider both how to make video and the LLM
    * Make a website of cloth, consider both the solution of making a website and cloth
5. You need to provide a total of 10 keywords, separated by commas and wrapped in <result></result> tags
6. Your keywords must be in the same language as the original requirement

Here is the original query:
""" # noqa

    div_system2 = """You are an inspiration bot. You will be given a series of keywords, and you need to provide related words that you associate with based on these keywords. The words must meet the following conditions:

1. For example, if given "website security", you can associate it with "password encryption", "horizontal vulnerabilities", "vertical vulnerabilities", "injection attacks", etc. "Attractiveness" can be associated with "humor", "memes", "accessibility", "examples", etc. "Explanation" can be associated with "audience", "origin", "principles", etc.
2. The words you provide should have varying degrees of relevance to the input keywords, ranging from 100% relevant to 1% relevant
3. You need to provide a total of 20 words (i.e., if the input is 25, you provide 20 words), separated by commas and wrapped in <result></result> tags
4. Your keywords must be in the same language as the input keywords

Here are the keywords:
""" # noqa

    div_system3 = """You are an inspiration bot. You will be given a series of keywords and an original requirement. You need to carefully analyze the relationship between the original requirement and the keywords, and provide your suggestions for completing the original requirement based on the keywords:

1. Some keywords may not be very helpful to the original requirement, or may belong to over-design or distractors - you need to ignore these words
2. You need to think deeply about the useful keywords to provide your suggestions
3. There is another architect to design the solution, your responsibility is to give extra points of the solution related to the keywords, so no need and do not give the design.
4. You need to carefully consider both the task itself and the topic, as this is very helpful for completing tasks.
    For example:
    * Make a video of LLM: consider both how to make video and the LLM
    * Make a website of cloth, consider both the solution of making a website and cloth
5. Your description of the original requirement will be added as prompts and suggestions to the subsequent development of the original requirement
6. Your description must be in the same language as the original requirement
7. Wrap your final suggestions with only one <result></result> wrapper

Here are the original query and the keywords:
""" # noqa

    def __init__(self, config):
        super().__init__(config)
        config.llm.service = config.llm.provider
        self.llm = None
        self.split_task = None
        self.num_split = 5
        self.memory_called = False

    def set_base_config(self, config: DictConfig):
        super().set_base_config(config)
        _config = deepcopy(config)
        _config.save_history = False
        delattr(_config, 'memory')
        delattr(_config, 'tools')
        _config.generation_config.temperature = 1.0
        self.llm = LLM.from_config(_config)
        self.split_task = SplitTask(_config, tag_prefix='diversity-')
        self.num_split = getattr(config, 'num_split', self.num_split)

    async def run(self, messages: List[Message]):
        if self.memory_called:
            return messages
        query = None
        system = None
        for message in messages:
            if message.role == 'system':
                system = message.content
            if message.role == 'user':
                query = message.content
                if system is None:
                    system = query
                break

        assert query is not None
        arguments = []
        for n in range(self.num_split):
            inputs = {
                'system': self.div_system1,
                'query': query,
            }
            arguments.append(inputs)

        arguments = {
            'tasks': arguments,
            'execution_mode': 'parallel',
        }

        results = await self.split_task.call_tool(
            '', tool_name='', tool_args=arguments)
        pattern = r'<result>(.*?)</result>'
        all_keywords = []
        for keywords in re.findall(pattern, results, re.DOTALL):
            all_keywords.extend([
                keyword.strip() for keyword in keywords.split(',')
                if keyword.strip()
            ])

        arguments = []
        _query = ','.join(set(all_keywords))
        logger.info(f'Diversity first round keywords: {_query}')
        for n in range(self.num_split):
            inputs = {
                'system': self.div_system2,
                'query': _query,
            }
            arguments.append(inputs)

        arguments = {
            'tasks': arguments,
            'execution_mode': 'parallel',
        }

        results = await self.split_task.call_tool(
            '', tool_name='', tool_args=arguments)
        pattern = r'<result>(.*?)</result>'
        all_keywords = []
        for keywords in re.findall(pattern, results, re.DOTALL):
            all_keywords.extend([
                keyword.strip() for keyword in keywords.split(',')
                if keyword.strip()
            ])

        _query = ','.join(set(all_keywords))
        logger.info(f'Diversity second round keywords: {_query}')
        _query = (f'Original query: {query}\n'
                  f'Keywords generated by LLMs: {all_keywords}')
        _messages = [
            Message(role='system', content=self.div_system3),
            Message(role='user', content=_query),
        ]
        response_message = self.llm.generate(_messages)
        pattern = r'<result>(.*?)</result>'
        suggestions = []
        for prompt in re.findall(pattern, response_message.content, re.DOTALL):
            suggestions.append(prompt)

        suggestions = '\n'.join(suggestions)
        logger.info(f'Diversity third round suggestions: {suggestions}')

        suggestions = (
            '\nNow Additional suggestions and findings are given to you, '
            'you need to consider these suggestions and carefully process the query:\n'
            f'{suggestions}')
        if system != query:
            system = system + suggestions
            messages[0].content = system
        else:
            query = query + suggestions
            messages[1].content = query
        self.memory_called = True
        return messages
