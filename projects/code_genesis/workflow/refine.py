import os
from typing import List, OrderedDict

import json
from coding import CodingAgent
from ms_agent import LLMAgent
from ms_agent.llm import Message
from ms_agent.utils import get_logger

logger = get_logger()


class RefineAgent(LLMAgent):

    system = """你是一个帮助总结、压缩模型执行历史的机器人。你会被给与模型的历史messages，你需要总结给你的多轮消息，并压缩它们。压缩比例需要达到1:6（30000token压缩到5000token）

你的工作场景是代码编写完成后的修复场景。大模型会不断调用shell等工具，并尝试解决一个大的代码项目中出现的问题。你的工作流程：

1. 你会被给与项目原始需求，技术栈以及文件列表，你需要仔细阅读它们
2. 你会被给与修复历史，其中可能修复了不同问题，也可能在同一个问题上死锁。
    * 对于已经解决的问题，可以保留较少的token或完全移除
    * 未解决问题可以保留较多的token
    * 多次未解决的死锁问题应增加多次未解决的额外标注
    * 保留最后一个未解决问题的历史记录，并提示模型继续解决该问题
    * 你的优化目标：1. 最少的保留token数量 2. 尽量还原未解决问题概况 3. 尽量保留并总结模型的错误轨迹以备后用
3. 返回你总结好的消息历史，不要增加额外内容（例如“让我来总结...”或“下面是对...的总结...”）
"""

    async def compress_memory(self, messages):
        if len(str(messages)) > 32000 and messages[-1].role in ('user',
                                                                'tool'):
            keep_messages = messages[:2]
            keep_messages_tail = []
            i = 0
            for i, message in enumerate(reversed(messages)):
                keep_messages_tail.append(message)
                if message.role == 'assistant':
                    break
            keep_messages_tail = reversed(keep_messages_tail)
            compress_messages = json.dumps(
                [message.to_dict_clean() for message in messages[2:-i - 1]],
                ensure_ascii=False,
                indent=2)
            with open(os.path.join(self.output_dir, 'topic.txt')) as f:
                topic = f.read()
            with open(os.path.join(self.output_dir, 'framework.txt')) as f:
                framework = f.read()
            with open(os.path.join(self.output_dir, 'file_design.txt')) as f:
                file_design = f.read()

            query = (f'原始需求: {topic}\n'
                     f'技术栈: {framework}\n'
                     f'文件设计: {file_design}\n'
                     f'除system和首轮user之外的消息: {compress_messages}')

            _messages = [
                Message(role='system', content=self.system),
                Message(role='user', content=query),
            ]
            _response_message = self.llm.generate(_messages)
            content = _response_message.content
            keep_messages.append(
                Message(
                    role='user',
                    content=
                    f'Intermediate messages are compressed, here is the compressed message:\n{content}\n'
                ))
            messages = keep_messages + list(keep_messages_tail) + [
                Message(
                    role='user', content='历史消息已经压缩，现在根据历史消息和最后的tool调用继续解决问题：')
            ]
            logger.info(f'Compressed messages length: {len(str(messages))}')
            return messages
        else:
            return messages

    async def condense_memory(self, messages):
        return await self.compress_memory(messages)

    async def run(self, messages, **kwargs):
        with open(os.path.join(self.output_dir, 'topic.txt')) as f:
            topic = f.read()
        with open(os.path.join(self.output_dir, 'user_story.txt')) as f:
            user_story = f.read()
        with open(os.path.join(self.output_dir, 'framework.txt')) as f:
            framework = f.read()
        with open(os.path.join(self.output_dir, 'protocol.txt')) as f:
            protocol = f.read()
        with open(os.path.join(self.output_dir, 'tasks.txt')) as f:
            file_info = f.read()

        file_relation = OrderedDict()
        CodingAgent.refresh_file_status(self, file_relation)
        CodingAgent.construct_file_information(self, file_relation, True)
        messages = [
            Message(role='system', content=self.config.prompt.system),
            Message(
                role='user',
                content=f'原始需求(topic.txt): {topic}\n'
                f'LLM规划的用户故事(user_story.txt): {user_story}\n'
                f'技术栈(framework.txt): {framework}\n'
                f'通讯协议(protocol.txt): {protocol}\n'
                f'文件列表:{file_info}\n'
                f'你的shell工具的work_dir（项目输出文件）是{self.output_dir}\n'
                f'请针对项目进行refine:'),
        ]
        return await super().run(messages, **kwargs)

    async def on_task_end(self, messages: List[Message]):
        assert os.path.isfile(os.path.join(self.output_dir, 'framework.txt'))
        assert os.path.isfile(os.path.join(self.output_dir, 'protocol.txt'))
        assert os.path.isfile(os.path.join(self.output_dir, 'modules.txt'))
