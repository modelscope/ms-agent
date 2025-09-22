# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import os
import unittest

from ms_agent.tools.mcp_client import MCPClient

from modelscope.utils.test_utils import test_level


class TestMCPClient(unittest.TestCase):
    mcp_config = {
        'mcpServers': {
            'fetch': {
                'type': 'sse',
                'url': os.getenv('MCP_SERVER_FETCH_URL'),
            }
        }
    }
    mcp_config2 = {
        'mcpServers': {
            'time': {
                'type': 'sse',
                'url': os.getenv('MCP_SERVER_TIME_URL'),
            }
        }
    }

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_outside_init(self):

        async def main():
            async with MCPClient(self.mcp_config) as mcp_client:
                mcps = await mcp_client.get_tools()
                assert ('fetch' in mcps)

                res = await mcp_client.call_tool(
                    server_name='fetch',
                    tool_name='fetch',
                    tool_args={'url': 'http://www.baidu.com'})
                assert ('baidu' in res)

        asyncio.run(main())

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_aenter(self):

        async def main():
            mcp_client = MCPClient(self.mcp_config)
            await mcp_client.__aenter__()
            mcps = await mcp_client.get_tools()
            assert ('fetch' in mcps)
            await mcp_client.__aexit__(None, None, None)

        asyncio.run(main())

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_normal_connect(self):

        async def main():
            mcp_client = MCPClient(self.mcp_config)
            await mcp_client.connect()
            mcps = await mcp_client.get_tools()
            assert ('fetch' in mcps)
            await mcp_client.cleanup()

        asyncio.run(main())

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_add_config(self):

        async def main():
            async with MCPClient(self.mcp_config) as mcp_client:
                await mcp_client.add_mcp_config(self.mcp_config2)
                mcps = await mcp_client.get_tools()
                assert ('fetch' in mcps and 'time' in mcps)

        asyncio.run(main())


if __name__ == '__main__':
    unittest.main()
