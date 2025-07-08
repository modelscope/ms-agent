# Copyright (c) Alibaba, Inc. and its affiliates.
from typing import List

from ms_agent.llm.openai_llm import OpenAI
from ms_agent.llm.utils import Message, Tool
from omegaconf import DictConfig


class DeepSeek(OpenAI):
    input_msg = {'role', 'content', 'tool_calls', 'prefix'}

    def __init__(self, config: DictConfig):
        super().__init__(
            config,
            base_url=config.llm.deepseek_base_url,
            api_key=config.llm.deepseek_api_key)

    def _call_llm_for_continue_gen(self,
                                   messages: List[Message],
                                   new_message,
                                   tools: List[Tool] = None,
                                   **kwargs):
        # ref: https://api-docs.deepseek.com/zh-cn/guides/chat_prefix_completion
        if messages and messages[-1].to_dict().get('prefix', False):

            messages[-1].reasoning_content += new_message.reasoning_content
            messages[-1].content += new_message.content
            if new_message.tool_calls:
                if messages[-1].tool_calls:
                    messages[-1].tool_calls += new_message.tool_calls
                else:
                    messages[-1].tool_calls = new_message.tool_calls
        else:
            messages.append(new_message)
            messages[-1].prefix = True

        messages = self.format_input_message(messages)
        stop = kwargs.pop('stop', []).append('```')
        return self._call_llm(
            messages=messages, tools=tools, stop=stop, **kwargs)


if __name__ == '__main__':
    import os
    from omegaconf import OmegaConf

    # 创建一个嵌套的字典结构
    conf: DictConfig = OmegaConf.create({
        'llm': {
            'model': 'deepseek-reasoner',
            'deepseek_base_url': 'https://api.deepseek.com/beta/v1',
            'deepseek_api_key': os.getenv('DEEPSEEK_API_KEY'),
            'openai_base_url': 'https://api-inference.modelscope.cn/v1',
            'openai_api_key': os.getenv('MODELSCOPE_API_KEY'),
            'generation_config': {
                'stream': True,
                'max_tokens': 500,
            }
        }
    })

    messages = [
        Message(role='assistant', content='You are a helpful assistant.'),
        # Message(role='user', content='经度：116.4074，纬度：39.9042是什么地方。用这个名字作为目录名'),
        # Message(role='user', content='请你简单介绍杭州'),
        Message(role='user', content='创建2个文件夹，一个叫a,一个叫b'),
    ]

    # tools = [
    #     # Tool(server_name='amap-maps', tool_name='maps_regeocode',
    #       description='将一个高德经纬度坐标转换为行政区划地址信息',
    #       parameters={'type': 'object', 'properties': {'location': {'type': 'string', 'description': '经纬度'}},
    #       'required': ['location']}),
    #     Tool(tool_name='mkdir', description='在文件系统创建目录', parameters={'type': 'object', 'properties':
    #     {'dir_name': {'type': 'string', 'description': '目录名'}}, 'required': ['dir_name']})
    # ]
    tools = None

    # 打印配置
    print(OmegaConf.to_yaml(conf))

    llm = DeepSeek(conf)

    # res = llm.generate(messages=messages, tools=tools, extra_body={'enable_thinking': False})
    # for chunk in res:
    #     print(chunk)

    # kwargs覆盖conf
    message = llm.generate(
        messages=messages,
        tools=tools,
        stream=False,
        extra_body={'enable_thinking': False})
    print(message)
    messages.append(message)
    # messages.append(Message(role='tool', content='北京市朝阳区崔各庄阿里巴巴朝阳科技园'))
    # message = llm.generate(messages=messages, tools=tools, stream=False, extra_body={'enable_thinking': False})
    # print(message)
