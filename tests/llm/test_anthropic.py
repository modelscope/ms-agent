# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import unittest

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.llm.anthropic_llm import Anthropic
from ms_agent.llm.utils import Message, Tool
from omegaconf import DictConfig, OmegaConf

from modelscope.utils.test_utils import test_level

API_CALL_MAX_TOKEN = 50


class OpenaiLLM(unittest.TestCase):
    conf: DictConfig = OmegaConf.create({
        'llm': {
            'model': 'Qwen/Qwen3-Coder-480B-A35B-Instruct',
            'anthropic_api_key': os.getenv('MODELSCOPE_API_KEY'),
            'anthropic_base_url': 'https://api-inference.modelscope.cn',
            'service': 'anthropic'
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
        Message(role='user', content='经度：116.4074，纬度：39.9042是什么地方'),
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
    mcp_config = {
        'mcpServers': {
            'fetch': {
                'type': 'sse',
                'url': os.getenv('MCP_SERVER_FETCH_URL'),
            }
        }
    }

    def setUp(self):
        import asyncio
        from ms_agent.tools.mcp_client import MCPClient

        # warmup mcp server for test
        async def main():
            mcp_client = MCPClient(self.mcp_config)
            await mcp_client.connect()
            mcps = await mcp_client.get_tools()
            assert ('fetch' in mcps)
            await mcp_client.cleanup()

        asyncio.run(main())

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_call_no_stream(self):
        llm = Anthropic(self.conf)
        res = llm.generate(messages=self.messages, tools=None)
        print(res)
        assert (res.content)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_call_stream(self):
        llm = Anthropic(self.conf)
        res = llm.generate(messages=self.messages, tools=None, stream=True)
        for chunk in res:
            print(chunk)
        assert (len(chunk.content))

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_tool_stream(self):
        llm = Anthropic(self.conf)
        res = llm.generate(
            messages=self.tool_messages, tools=self.tools, stream=True)
        for chunk in res:
            print(chunk)
        assert (len(chunk.tool_calls))

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_tool_no_stream(self):
        llm = Anthropic(self.conf)
        res = llm.generate(messages=self.tool_messages, tools=self.tools)
        print(res)
        assert (len(res.tool_calls))

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_agent_multi_round(self):
        import asyncio

        async def main():
            agent = LLMAgent(config=self.conf, mcp_config=self.mcp_config)
            agent.config.callbacks.remove('input_callback')  # noqa
            res = await agent.run('访问www.baidu.com')
            print(res)
            assert ('robots.txt' in res[-1].content)

        asyncio.run(main())

    @unittest.skipUnless(test_level() >= 1, 'skip test in current test level')
    def test_stream_agent_multi_round(self):
        import asyncio
        from copy import deepcopy

        async def main():
            conf2 = deepcopy(self.conf)
            conf2.generation_config.stream = True
            agent = LLMAgent(config=self.conf, mcp_config=self.mcp_config)
            agent.config.callbacks.remove('input_callback')  # noqa
            res = await agent.run('访问www.baidu.com')
            print('res:', res)
            assert ('robots.txt' in res[-1].content)

        asyncio.run(main())


if __name__ == '__main__':
    unittest.main()
