# Copyright (c) Alibaba, Inc. and its affiliates.
import json
import math
import os
import unittest

from ms_agent.agent import LLMAgent

from ms_agent.agent.memory.default_memory import DefaultMemory
from ms_agent.llm.utils import Message, Tool
from omegaconf import DictConfig, OmegaConf

from modelscope.utils.test_utils import test_level


class TestDefaultMemory(unittest.TestCase):
    def setUp(self) -> None:
        self.config = {
            'memory': {
                'conversation_id': 'default_id',
                'persist': True,
                'compress': True,
                'is_retrieve': True,
                'history_mode': 'add',
                'llm': {
                    'provider': 'openai',
                    'model': 'qwen3-235b-a22b-instruct-2507',
                    'openai_base_url':
                        'https://dashscope.aliyuncs.com/compatible-mode/v1',
                    'api_key': os.getenv('DASHSCOPE_API_KEY'),
                },
                'embedder': {
                    'provider': 'openai',
                    'config': {
                        'api_key': os.getenv('DASHSCOPE_API_KEY'),
                        'openai_base_url':
                            'https://dashscope.aliyuncs.com/compatible-mode/v1',
                        'model': 'text-embedding-v4',
                    }
                }
            }
        }
        history_file = os.getenv('TEST_MEMORY_LONG_HISTORY_MESSAGES', 'openai_format_test_case1.json')
        with open(history_file, 'r') as f:
            data = json.load(f)
        self.history_messages = data

    @unittest.skip#Unless(test_level() >= 0, 'skip test in current test level')
    def test_default(self):
        config = OmegaConf.create({})
        memory = DefaultMemory(config)
        memory.add(self.history_messages)
        res = memory.search(self.query)
        print(res)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_agent_use_memory(self):
        import os
        import yaml
        import asyncio
        current_dir = os.path.dirname(os.path.abspath(__file__))
        default_config_path = f'{current_dir}/../../ms_agent/agent/agent.yaml'
        with open(default_config_path, 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)
        config['memory'] = self.config['memory']
        config['local_dir'] = current_dir
        config['llm']['modelscope_api_key'] = os.getenv('MODELSCOPE_API_KEY')
        async def main():
            agent = LLMAgent(config=OmegaConf.create(config))
            res = await agent.run('使用bun会对新项目的影响大吗，有哪些新特性')
            print(res)

        asyncio.run(main())


    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_compress_persist_add(self):
        # 使用压缩的持久能记录用户历史偏好的，不记录tool的
        pass

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_compress_persist_remove(self):
        # 中间节点开始retry
        pass

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_diff_base_api(self):
        pass

if __name__ == '__main__':
    unittest.main()