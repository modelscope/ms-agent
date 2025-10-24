# Copyright (c) Alibaba, Inc. and its affiliates.
import unittest

from ms_agent.agent.loader import AgentLoader
from ms_agent.llm.utils import Message, ToolCall
from omegaconf import OmegaConf

from modelscope.utils.test_utils import test_level


class TestDefaultMemory(unittest.TestCase):

    def setUp(self) -> None:
        self.tool_history = [
            Message(
                role='user',
                content=
                'Help me find the coolest sports park in Chaoyang District, Beijing. Remember this location for next'
                'time.'),
            Message(
                role='assistant',
                content=
                '\nThe user wants to find the coolest sports park in Chaoyang District, Beijing. The keyword "cool" '
                'suggests they are not just looking for functionality, but also value high-tech design, interactive '
                'experiences, and trendy elements. Therefore, I need to search for venues that have a futuristic feel, '
                'integrate advanced technology, youth culture, or innovative facilities.\n\nTo solve this, I will take '
                'the following steps:\n'
                '1. Use the awesome_map-search tool to search for sports parks in Chaoyang District, Beijing, focusing '
                'on keywords like "cool", "high-tech", "trendy", etc.\n'
                '2. Filter out the most distinctive, highly-rated parks with strong visual impact\n'
                '3. Provide the name of the sports park.\n\nNow I will call the awesome_map-search tool. This tool is '
                'designed specifically for geo + fun information retrieval, '
                'supports semantic queries, and excels at discovering "hidden gem" locations.',
                tool_calls=[
                    ToolCall(
                        id='call_xyz789CoolPark',
                        type='function',
                        tool_name='awesome_map-search',
                        arguments=
                        '{"query": "Beijing Chaoyang District coolest sports park high-tech trendy must-visit spot", '
                        '"max_results": 1, "result_type":'
                        '"detailed", "include_features": true}')
                ]),
            Message(
                role='tool',
                content=
                '[{"park_name": "Quantum Leap · Chaoyang Future Sports Dome", "address": "No. 8888 Jiuxianqiao Road, '
                'Chaoyang District, Beijing", "features": ["Anti-gravity floating track using magnetic levitation '
                'cushioning tech — running feels like jumping on the moon", "AR extreme climbing wall supporting '
                'virtual scenes such as volcanic apocalypse and interstellar maze", "DJ-powered cycling pods: the '
                'faster you pedal, the more intense the music, with real-time energy waveform visualization", '
                '"AI coach robot \'Tie Ran\', which creates custom workout plans and motivates users in Northeastern '
                'Chinese dialect", "Glow-in-the-dark Tai Chi lake with floating yoga platforms; water contains '
                'eco-friendly bioluminescent algae glowing blue at night"], "special_events": ["Cool Sports Event '
                'every Friday night: laser dodgeball, glow-in-the-dark dance run, robot tug-of-war"], "tips": ["Must '
                'solve 3 fitness puzzles to unlock entry", "Bring a power bank — taking photos too frequently drains '
                'battery quickly"], "rating": 9.9, "opening_hours": "6:00 - 23:00", "admission": "Free"}]'
            ),
            Message(
                role='assistant',
                content=
                '\nThe user wanted to find the coolest sports park in Chaoyang District, Beijing. I have retrieved '
                'relevant information via the awesome_map-search tool.\n\n## 🌟 The Coolest Sports Park in Chaoyang '
                'District, Beijing Revealed: 「Quantum Leap · Chaoyang Future Sports Dome」'
            ),
            Message(role='user', content='Alright, bye!')
        ]

    def tearDown(self):
        import shutil
        shutil.rmtree('output', ignore_errors=True)

    @unittest.skip
    def test_default_memory(self):
        import uuid
        import asyncio

        async def main():
            random_id = str(uuid.uuid4())
            default_memory = OmegaConf.create({
                'memory': [{
                    'path': f'output/{random_id}',
                    'user_id': random_id
                }]
            })
            agent1 = AgentLoader.build(
                'ms-agent/simple_agent_code',
                config=default_memory,
                trust_remote_code=True)
            if hasattr(agent1.config.callbacks, 'input_callback'):
                agent1.config.callbacks.remove('input_callback')  # noqa
            await agent1.run(
                'I am a vegetarian and I drink coffee every morning.')
            del agent1
            print(
                '========== Data preparation completed, starting test ==========='
            )
            agent2 = AgentLoader.build(
                'ms-agent/simple_agent_code',
                config=default_memory,
                trust_remote_code=True)
            if hasattr(agent2.config.callbacks, 'input_callback'):
                agent2.config.callbacks.remove('input_callback')  # noqa
            res = await agent2.run(
                'Please help me plan tomorrow’s three meals.')
            print(res)
            assert ('vegetarian' in res[-1].content.lower()
                    or 'vegan' in res[-1].content.lower()
                    ) and 'coffee' in res[-1].content.lower()

        asyncio.run(main())

    @unittest.skip
    def test_agent_tool(self):
        import uuid
        import asyncio

        async def main():
            random_id = str(uuid.uuid4())
            config = OmegaConf.create({
                'memory': [{
                    'ignore_role': ['system'],
                    'user_id': random_id,
                    'path': f'output/{random_id}'
                }]
            })
            agent1 = AgentLoader.build(
                'ms-agent/simple_agent_code',
                config=config,
                trust_remote_code=True)
            agent1.config.callbacks.remove('input_callback')  # noqa
            await agent1.run(self.tool_history)
            del agent1
            print(
                '========== Data preparation completed, starting test ==========='
            )
            agent2 = AgentLoader.build(
                'ms-agent/simple_agent_code',
                config=config,
                trust_remote_code=True)
            agent2.config.callbacks.remove('input_callback')  # noqa
            res = await agent2.run(
                'What is the location of the coolest sports park in Chaoyang District, Beijing?'
            )
            print(res)
            assert 'Jiuxianqiao Road 8888' in res[
                -1].content or 'No. 8888 Jiuxianqiao Road' in res[-1].content

        asyncio.run(main())

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_overwrite_with_tool(self):
        import uuid
        import asyncio

        async def main():
            tool_history1 = self.tool_history[:-1] + [
                Message(
                    role='user',
                    content=
                    'The sports park you mentioned has already closed down.'),
                Message(
                    role='assistant',
                    content=
                    'The user mentioned that "Quantum Leap · Chaoyang Future Sports Dome" has shut down. Today is '
                    'May 7, 2045. I need to search again for the currently operating coolest sports park. I will use '
                    'the awesome_map-search tool with updated time-sensitive keywords such as "open in 2045" to ensure '
                    'accuracy and timeliness.',
                    tool_calls=[
                        ToolCall(
                            id='call_xyz2045NewPark',
                            type='function',
                            tool_name='awesome_map-search',
                            arguments=
                            '{"query": "Beijing Chaoyang District coolest sports park high-tech trendy must-visit spot '
                            'open in 2045", "max_results": 1, "result_type": "detailed", "include_features": true}'
                        )
                    ]),
                Message(
                    role='tool',
                    content=
                    '[{"park_name": "Stellar Core Dynamics · Chaoyang Metaverse Sports Matrix", '
                    '"address": "No. 99 Aoti South Road, Chaoyang District, Beijing", '
                    '"features": ["Holographic projection tracks that trigger stardust trails with each step", '
                    '"Mind-controlled climbing wall — stronger focus increases adhesion", '
                    '"Gravity-adjustable training pods simulating Mars, Moon, or deep-sea environments", '
                    '"AI virtual coach \'Neo\' with customizable cross-dimensional avatars", '
                    '"Nighttime hoverboard pool using magnetic ground propulsion for wheel-free gliding"], '
                    '"special_events": ["Daily twilight \'Consciousness Awakening Run\': synchronized rhythm via '
                    'brain-computer interface, generating collective lightstorm"], '
                    '"tips": ["Neural compatibility test required in advance", '
                    '"Avoid extreme emotional fluctuations, otherwise system activates calming white noise mode", '
                    '"Wearing conductive sportswear recommended for better interaction"], "rating": 9.8, '
                    '"opening_hours": "5:30 - 24:00", "admission": "Free (entry via brainprint registration)"}]'
                ),
                Message(
                    role='assistant',
                    content=
                    'The latest and coolest sports park in 2045 is: Stellar Core Dynamics · Chaoyang Metaverse Sports '
                    'Matrix. Located at No. 99 Aoti South Road, Chaoyang District, Beijing, it integrates '
                    'brain-computer interfaces, holographic projections, and gravity control technology to deliver an '
                    'immersive futuristic fitness experience. Now open for reservations, free entry via brainprint '
                    'registration.'),
                Message(role='user', content='Got it, thanks.'),
            ]
            tool_history2 = self.tool_history[:-1] + [
                Message(
                    role='user',
                    content=
                    'What is the location of the coolest sports park in Chaoyang District, Beijing?'
                )
            ]
            random_id = str(uuid.uuid4())
            config = OmegaConf.create({
                # 'memory': [{
                #     'ignore_role': ['system'],
                #     'history_mode': 'overwrite',
                #     'path': f'output/{random_id}',
                #     'user_id': random_id,
                # }]
                'memory': [{
                    'ignore_role': ['system'],
                    'history_mode': 'overwrite',
                    'path': f'output/{random_id}',
                    'vector_store': {
                        'service': 'milvus',
                        'url': 'http://c-8fd6ad88d2ddfd58.milvus.aliyuncs.com',
                        'token': 'root:Mcp-playground1',
                        'db_name': 'test'
                    },
                    'user_id': random_id,
                }]
            })
            agent1 = AgentLoader.build(
                'ms-agent/simple_agent_code',
                config=config,
                trust_remote_code=True)
            await agent1.run(tool_history1)
            del agent1
            print(
                '========== Data preparation completed, starting test ==========='
            )
            agent2 = AgentLoader.build(
                'ms-agent/simple_agent_code',
                config=config,
                trust_remote_code=True)
            res = await agent2.run(tool_history2)
            print(res)
            # Assert old info remains due to overwrite mode, new info not persisted
            assert ('Jiuxianqiao Road 8888' in res[-1].content
                    or 'No. 8888 Jiuxianqiao Road' in res[-1].content
                    ) and 'Aoti South Road' not in res[-1].content

        asyncio.run(main())


if __name__ == '__main__':
    unittest.main()
