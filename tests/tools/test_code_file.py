# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import unittest

from ms_agent.agent.loader import AgentLoader

from modelscope.utils.test_utils import test_level


class TestCodeFile(unittest.TestCase):

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_code_file(self):

        async def main():
            engine = AgentLoader.build(
                'ms-agent/simple_agent_code', trust_remote_code=True)
            messages = await engine.run('who are you?')
            self.assertTrue('😁' in messages[-1].content)

        asyncio.run(main())


if __name__ == '__main__':
    unittest.main()
