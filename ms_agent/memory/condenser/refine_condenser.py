from typing import List

import json
from ms_agent.llm import LLM, Message
from ms_agent.memory import Memory


class RefineCondenser(Memory):
    system = """你是一个帮忙总结并缩减模型上下文长度的大模型。你需要遵循以下指引：

1. 你会被给与整体messages，结构是：
    ```
    1. system部分
    2. 用户query部分
    3~N. 中间messages，也是你需要压缩的部分
    N~结尾. 最后一轮assistant回复和后续的tool调用信息
    ```

2. 你需要保留：
    a. 模型执行轨迹
    b. 完成的事项
    c. 解决中的问题
    d. 重要反思和经验

    你的返回格式：
    ```json
    [
        {
            "name": "读取...文件", # 轨迹事项描述
            "description": "文件缩略内容...", # 轨迹内容记录
            "type": "轨迹" # 事项类型
        },
        {
            "name": "存储...代码", # 轨迹事项描述,
            ...
            "type": "轨迹" # 事项类型
        },
        {
            "name": "代码执行错误",
            "description": "由于...导致了编写问题",
            "type": "反思"
        },
        {
            "name": "需要处理...",
            "description": "用户给了重要提示，...",
            "type": "经验"
        },
        {
            "name": "需要处理...",
            ...
            "type": "进行中事项"
        },
    ]
    ```

3. 你需要注意:
    a. 压缩比达到1:6， 即压缩到原来的约六分之一长度
    b. 对当前处理的事务，和对用户原始需求不重要的事项需要移除，反之则保留
    c. 对用户需要继续处理的事务进行额外提示，防止模型在消息压缩后进入死循环
"""

    def __init__(self, config):
        super().__init__(config)
        self.llm: LLM = LLM.from_config(self.config)
        mem_config = self.config.memory.refine_condenser
        if getattr(mem_config, 'system', None):
            self.system = mem_config.system
        self.threshold = getattr(mem_config, 'threshold', 60000)

    async def condense_memory(self, messages):
        if len(str(messages)) > self.threshold and messages[-1].role in (
                'user', 'tool'):
            keep_messages = messages[:2]  # keep system and user
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
            keep_messages_json = json.dumps(
                [message.to_dict_clean() for message in keep_messages],
                ensure_ascii=False,
                indent=2)
            keep_messages_tail_json = json.dumps(
                [message.to_dict_clean() for message in keep_messages_tail],
                ensure_ascii=False,
                indent=2)

            query = (f'# Messages to be retained\n'
                     f'## system and user: {keep_messages_json}\n'
                     f'## Last assistant response: {keep_messages_tail_json}\n'
                     f'# Messages to be compressed'
                     f'## These messages are located between system/user '
                     f'and the last assistant response: {compress_messages}')

            _messages = [
                Message(role='system', content=self.system),
                Message(role='user', content=query),
            ]
            _response_message = self.llm.generate(_messages, stream=False)
            content = _response_message.content
            keep_messages.append(
                Message(
                    role='user',
                    content=
                    f'Intermediate messages are compressed, here is the compressed message:\n{content}\n'
                ))
            messages = keep_messages + list(keep_messages_tail) + [
                Message(
                    role='user',
                    content=
                    'History messages are compressed due to a long sequence, now '
                    'continue solve your problem according to '
                    'the messages and the tool calling:\n')
            ]
            return messages
        else:
            return messages

    async def run(self, messages: List[Message]):
        return await self.condense_memory(messages)
