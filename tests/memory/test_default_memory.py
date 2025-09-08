# Copyright (c) Alibaba, Inc. and its affiliates.
import math
import os
import unittest

import json
from ms_agent.agent import LLMAgent
from ms_agent.agent.memory.default_memory import DefaultMemory
from ms_agent.llm.utils import Message, ToolCall
from omegaconf import DictConfig, OmegaConf

from modelscope.utils.test_utils import test_level


class TestDefaultMemory(unittest.TestCase):

    def setUp(self) -> None:
        self.tool_history = [
            Message(role='user', content='帮我找到北京市朝阳区最炫酷的运动公园。我标记一下，下次去。'),
            Message(
                role='assistant',
                content=
                '\n用户希望找到北京市朝阳区最炫酷的运动公园，关键词是‘炫酷’，说明用户追求的不仅是功能性，更看重科技感、设计感、互动体验'
                '和潮流元素。因此，我需要搜索具备未来感、融合高科技、潮流文化或创新设施的运动场所。\n\n为了解决这个问题，我将采取以下步'
                '骤：\n1. 使用awesome_map-search工具搜索北京市朝阳区的运动公园，重点关注‘炫酷’‘科技感’‘潮流’等关键词\n2. 筛选出最'
                '具特色、评价最高、视觉冲击力强的公园\n3. 提供运动公园名称。\n\n现在我将调用awesome_map-search工具进行搜索，该工具'
                '专为地理+趣味性信息检索设计，支持语义化查询，尤其擅长发现‘宝藏地点’。\n',
                tool_calls=[
                    ToolCall(
                        id='call_xyz789CoolPark',
                        type='function',
                        tool_name='awesome_map-search',
                        arguments=
                        '{"query": "北京市朝阳区 最炫酷 运动公园 科技感 潮流 打卡圣地", "max_results": 1, "result_type":'
                        '"detailed", "include_features": true}')
                ]),
            Message(
                role='tool',
                content=
                '[{"park_name": "量子跃动·朝阳未来运动穹顶", "address": "北京市朝阳区酒仙桥路8888号", "features": ["反重力悬'
                '浮跑道，采用磁悬浮缓震技术，跑步如在月球上跳跃", "AR极限攀岩墙，支持末日火山、星际迷宫等虚拟场景", "DJ动感骑行舱，踩'
                '得越快音乐越炸，实时生成能量波形图", "AI教练机器人\'铁燃\'，可定制训练计划并用东北话激励用户", "夜光太极湖与漂浮瑜伽'
                '平台，湖水含环保夜光藻类，夜晚泛蓝光"], "special_events": ["每周五晚举办炫酷运动会：激光躲避球、荧光舞步跑、机器人'
                '拔河"], "tips": ["需完成3道运动谜题解锁入场", "禁止穿拖鞋跑步，否则AI会播放《凉凉》", "建议携带充电宝，拍照太频繁易'
                '没电"], "rating": 9.9, "opening_hours": "6:00 - 23:00", "admission": "免费"}]'
            ),
            Message(
                role='assistant',
                content=
                '\n用户希望找到北京市朝阳区最炫酷的运动公园。我已经通过awesome_map-search工具获取了相关信息。\n\n## 🌟 北京市朝阳区最炫酷运动公园揭晓：「量子跃动·朝阳未来运动穹顶」'
            ),
            Message(role='user', content='好的，拜拜')
        ]

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_default_memory(self):
        import uuid
        import asyncio

        async def main():
            random_id = str(uuid.uuid4())
            default_memory = OmegaConf.create({'memory': {}})
            agent1 = LLMAgent(config=default_memory, task=random_id)
            agent1.config.callbacks.remove('input_callback')  # noqa
            await agent1.run('我是素食主义者，我每天早上喝咖啡')
            del agent1

            agent2 = LLMAgent(config=default_memory, task=random_id)
            agent2.config.callbacks.remove('input_callback')  # noqa
            res = await agent2.run('请帮我准备明天的三餐食谱')
            print(res)
            assert ('素' in res[-1].content and '咖啡' in res[-1].content)

        asyncio.run(main())

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_agent_tool(self):
        import uuid
        import asyncio

        async def main():
            random_id = str(uuid.uuid4())
            config = OmegaConf.create({'memory': {'ignore_role': ['system']}})
            agent1 = LLMAgent(config=OmegaConf.create(config), task=random_id)
            agent1.config.callbacks.remove('input_callback')  # noqa
            await agent1.run(self.tool_history)
            del agent1

            agent2 = LLMAgent(config=OmegaConf.create(config), task=random_id)
            agent2.config.callbacks.remove('input_callback')  # noqa
            res = await agent2.run('北京市朝阳区最炫酷的运动公园的地点')
            print(res)
            assert ('酒仙桥路8888号' in res[-1].content)

        asyncio.run(main())

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_overwrite_with_tool(self):
        # Retry starting from an intermediate node
        pass


if __name__ == '__main__':
    unittest.main()
