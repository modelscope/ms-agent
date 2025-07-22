# Copyright (c) Alibaba, Inc. and its affiliates.
import math
import os
import unittest

from ms_agent.llm.openai_llm import OpenAI
from ms_agent.llm.utils import Message, Tool, ToolCall
from omegaconf import DictConfig, OmegaConf

API_CALL_MAX_TOKEN = 50


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
            'max_tokens': API_CALL_MAX_TOKEN
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
        for chunk in res:
            print(chunk)
        assert (len(chunk.content))

    def test_call_thinking(self):
        llm = OpenAI(self.conf)
        res = llm.generate(
            messages=self.messages,
            tools=None,
            stream=True,
            extra_body={'enable_thinking': True})
        for chunk in res:
            print(chunk)
        assert (chunk.reasoning_content)

    def test_continue_run(self):
        llm = OpenAI(self.conf)
        res = llm.generate(messages=self.continue_messages, tools=None)
        print(res)
        assert (res.completion_tokens > 100)

    def test_call_tool(self):
        llm = OpenAI(self.conf)
        res = llm.generate(messages=self.tool_messages, tools=self.tools)
        print(res)
        assert (len(res.tool_calls))

    def test_call_apis_count(self):
        llm = OpenAI(self.conf)
        res = llm.generate(messages=self.messages, tools=None)
        print(res)
        assert res.api_calls == 1

    def test_call_apis_count_stream(self):
        llm = OpenAI(self.conf)
        res = llm.generate(messages=self.messages, stream=True, tools=None)
        for chunk in res:
            print(chunk)
        assert chunk.api_calls == 1

    def test_call_apis_count_continue(self):
        llm = OpenAI(self.conf)
        res = llm.generate(messages=self.continue_messages, tools=None)
        print(res)
        assert math.ceil(res.completion_tokens
                         / API_CALL_MAX_TOKEN) == res.api_calls

    def test_call_apis_count_continue_stream(self):
        llm = OpenAI(self.conf)
        res = llm.generate(
            messages=self.continue_messages, stream=True, tools=None)
        for chunk in res:
            print(chunk)
        assert math.ceil(chunk.completion_tokens
                         / API_CALL_MAX_TOKEN) == chunk.api_calls

    def test_call_tool_stream(self):
        llm = OpenAI(self.conf)
        res = llm.generate(
            messages=self.tool_messages,
            tools=self.tools,
            stream=True,
            extra_body={'enable_thinking': False})
        for chunk in res:
            print(chunk)
        assert (len(chunk.tool_calls))


if __name__ == '__main__':
    unittest.main()
