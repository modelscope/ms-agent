# Copyright (c) ModelScope Contributors. All rights reserved.
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Optional, Union

import json
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM, Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


@dataclass
class Pattern:

    name: str
    pattern: str
    tags: List[str] = field(default_factory=list)


class GenerateIllustrationPrompts(CodeAgent):

    # Background prompt generator (t2i)
    system = """你是一名提示词工程师，负责为短视频生成一张背景图。

要求：
- 仅输出一条简洁的英文提示词。不要使用 markdown、JSON 或任何解释说明。
- 背景应具有电影感且风格统一。
- 重要：画面中心区域保持视觉上的干净/留白（安全区），以便叠加动画。
- 避免杂乱和细小难辨的细节。
"""

    # Foreground prompt generator (t2i)
    system_foreground = """你是一名提示词工程师，负责生成单个前景素材。

规则：
- 仅输出一条简洁的英文提示词。不要使用 markdown、JSON 或任何解释说明。
- 丰富的细节：保证图片可以完整表述原需求。
- 不要留白：使用适当的背景填充图像，尽量不要使用白色背景
"""

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.num_parallel = getattr(self.config, 'llm_num_parallel', 10)
        self.illustration_prompts_dir = os.path.join(self.work_dir,
                                                     'illustration_prompts')
        os.makedirs(self.illustration_prompts_dir, exist_ok=True)

    async def execute_code(self, messages: Union[str, List[Message]],
                           **kwargs) -> List[Message]:
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)
        logger.info('Generating illustration prompts.')

        tasks = [(i, segment) for i, segment in enumerate(segments)]

        with ThreadPoolExecutor(max_workers=self.num_parallel) as executor:
            futures = {
                executor.submit(self._generate_illustration_prompts_static, i,
                                segment, self.config,
                                self.illustration_prompts_dir): i
                for i, segment in tasks
            }
            for future in as_completed(futures):
                future.result()
        return messages

    @staticmethod
    def _generate_illustration_prompts_static(i, segment, config,
                                              illustration_prompts_dir):
        """Static method for multiprocessing"""
        llm = LLM.from_config(config)
        max_retries = 10
        if config.background == 'image':
            for attempt in range(max_retries):
                try:
                    GenerateIllustrationPrompts._generate_illustration_impl(
                        llm, i, segment, illustration_prompts_dir)
                    break
                except Exception:
                    time.sleep(2)

        if config.foreground == 'image':
            for attempt in range(max_retries):
                try:
                    GenerateIllustrationPrompts._generate_foreground_impl(
                        llm, i, segment, illustration_prompts_dir)
                    break
                except Exception:
                    time.sleep(2)

    @staticmethod
    def _generate_illustration_impl(llm, i, segment, illustration_prompts_dir):
        if os.path.exists(
                os.path.join(illustration_prompts_dir, f'segment_{i+1}.txt')):
            return

        background_concept = segment.get('background')
        logger.info(
            f'Generating background prompt from plan: {background_concept}')

        with open(
                os.path.join(
                    os.path.dirname(illustration_prompts_dir), 'topic.txt'),
                'r') as f:
            topic = f.read()
        query = (
            f'User original topic: {topic}\n'
            f'Generate a background prompt based on the topic and concept of current segment: {background_concept}.'
        )
        inputs = [
            Message(role='system', content=GenerateIllustrationPrompts.system),
            Message(role='user', content=query),
        ]

        response = llm.generate(inputs).content.strip()

        # Strip thinking tags
        response = re.sub(
            r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()

        with open(
                os.path.join(illustration_prompts_dir, f'segment_{i + 1}.txt'),
                'w') as f:
            f.write(response)

    @staticmethod
    def _generate_foreground_impl(llm, i, segment, illustration_prompts_dir):
        foreground_assets = segment.get('foreground')
        for idx, asset_desc in enumerate(foreground_assets):
            file_path = os.path.join(illustration_prompts_dir,
                                     f'segment_{i+1}_foreground_{idx+1}.txt')
            if os.path.exists(file_path):
                continue

            logger.info(
                f'Generating foreground_{idx} prompt from plan: {asset_desc}')

            with open(
                    os.path.join(
                        os.path.dirname(illustration_prompts_dir),
                        'topic.txt'), 'r') as f:
                topic = f.read()

            query = (f'User original topic: {topic}\n'
                     f'Design a single foreground asset: {asset_desc}\n')

            inputs = [
                Message(
                    role='system',
                    content=GenerateIllustrationPrompts.system_foreground),
                Message(role='user', content=query),
            ]

            response = llm.generate(inputs).content.strip()

            # Strip thinking tags
            response = re.sub(
                r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()

            with open(file_path, 'w') as f:
                f.write(response)
