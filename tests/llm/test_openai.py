# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import unittest

from ms_agent.llm.openai_llm import OpenAI
from ms_agent.llm.utils import Message, Tool, ToolCall
from omegaconf import DictConfig, OmegaConf


class OpenaiLLM(unittest.TestCase):
    conf: DictConfig = OmegaConf.create({
        'llm': {
            'model': 'Qwen/Qwen3-235B-A22B',
            'openai_base_url': 'https://api-inference.modelscope.cn/v1',
            'openai_api_key': os.getenv('MODELSCOPE_API_KEY'),
        },
        'generation_config': {
            'stream': False,
            'extra_body': {
                'enable_thinking': False
            },
            'max_tokens': 50
        }
    })
    messages = [
        Message(role='assistant', content='You are a helpful assistant.'),
        Message(role='user', content='浙江的省会是哪里？'),
    ]
    tool_messages = [
        Message(role='assistant', content='You are a helpful assistant.'),
        Message(role='user', content='经度：116.4074，纬度：39.9042是什么地方？'),
    ]
    continue_messages = [
        Message(role='assistant', content='You are a helpful assistant.'),
        Message(role='user', content='写一篇介绍杭州的短文，200字左右。'),
    ]

    tools = [
        Tool(
            server_name='amap-maps',
            tool_name='maps_regeocode',
            description='将一个高德经纬度坐标转换为行政区划地址信息',
            parameters={
                'type': 'object',
                'properties': {
                    'location': {
                        'type': 'string',
                        'description': '经纬度'
                    }
                },
                'required': ['location']
            }),
        Tool(
            tool_name='mkdir',
            description='在文件系统创建目录',
            parameters={
                'type': 'object',
                'properties': {
                    'dir_name': {
                        'type': 'string',
                        'description': '目录名'
                    }
                },
                'required': ['dir_name']
            })
    ]

    def test_call_no_stream(self):
        llm = OpenAI(self.conf)
        res = llm.generate(messages=self.messages, tools=None)
        print(res)
        assert (res.content)

    def test_call_stream(self):
        llm = OpenAI(self.conf)
        res = llm.generate(messages=self.messages, tools=None, stream=True)
        msg = None
        for chunk in res:
            yield chunk
            msg = llm.merge_stream_message(msg, chunk)
        assert (len(msg.content))

    def test_call_thinking(self):
        llm = OpenAI(self.conf)
        res = llm.generate(
            messages=self.messages,
            tools=None,
            stream=True,
            extra_body={'enable_thinking': True})
        msg = None
        for chunk in res:
            yield chunk
            msg = llm.merge_stream_message(msg, chunk)
        assert (msg.reasoning_content)

    def test_continue_run(self):
        llm = OpenAI(self.conf)
        res = llm.generate(messages=self.continue_messages, tools=None)
        print(res)
        assert (len(res.content) > 100)

    def test_call_tool(self):
        llm = OpenAI(self.conf)
        res = llm.generate(messages=self.tool_messages, tools=self.tools)
        print(res)
        assert (len(res.tool_calls))

    def test_call_tool_stream(self):
        llm = OpenAI(self.conf)
        res = llm.generate(
            messages=self.tool_messages,
            tools=self.tools,
            stream=True,
            extra_body={'enable_thinking': False})
        msg = None
        for chunk in res:
            yield chunk
            msg = llm.merge_stream_message(msg, chunk)
        assert (len(msg.tool_calls))


if __name__ == '__main__':
    unittest.main()
