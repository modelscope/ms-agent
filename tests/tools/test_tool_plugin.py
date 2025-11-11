# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import os
import unittest

from ms_agent.config import Config
from ms_agent.tools import ToolManager
from ms_agent.tools.mcp_client import MCPClient

from modelscope.utils.test_utils import test_level


class TestToolPlugin(unittest.TestCase):

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_tool_plugin(self):

        async def main():
            config = Config.from_task('ms-agent/simple_tool_plugin')
            tool_manager = ToolManager(config, trust_remote_code=True)
            self.assertTrue(len(tool_manager.extra_tools) == 1)
            await tool_manager.connect()
            await tool_manager.cleanup()

        asyncio.run(main())


if __name__ == '__main__':
    unittest.main()
