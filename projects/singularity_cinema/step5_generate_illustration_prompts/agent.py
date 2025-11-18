# Copyright (c) Alibaba, Inc. and its affiliates.
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Union

import json
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM, Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger(__name__)


@dataclass
class Pattern:

    name: str
    pattern: str
    tags: List[str] = field(default_factory=list)


class GenerateIllustrationPrompts(CodeAgent):

    system = """You are a scene description expert for AI knowledge science videos. Based on the given knowledge point or storyboard, generate a detailed English description for creating an appropriately styled illustration with an AI/technology theme. Requirements:

- The illustration must depict only ONE scene, not multiple scenes, not comic panels, not split images. Absolutely do NOT use any comic panels, split frames, multiple windows, or any kind of visual separation. Each image is a single, unified scene.
- All elements must appear together in the same space, with no borders, no frames, and no visual separation.
- All characters and elements must be fully visible, not cut off or overlapped.
- Only add clear, readable English text in the image if it is truly needed to express the knowledge point or scene meaning, such as AI, Token, LLM, or any other relevant English word. Do NOT force the use of any specific word in every scene. If no text is needed, do not include any text.
- All text in the image must be clear, readable, and not distorted, garbled, or random.
- The scene can include rich, relevant, and layered minimalist tech/AI/futuristic elements (e.g., computer, chip, data stream, AI icon, screen, etc.), and simple decorative elements to enhance atmosphere, but do not let elements overlap or crowd together.
- All elements should be relevant to the main theme and the meaning of the current subtitle segment.
- The image output should be a square, and its background should be **pure white**
- Image content should be uncluttered, with clear individual elements
- Unless necessary, do not generate text, as text may be generated incorrectly, creating an AI-generated feel
- The image panel size is 1920*1080, so you need to concentrate elements within a relatively flat image area. Elements at the top and bottom will be cropped
- The images need to accurately convey the meaning expressed by the text. Later, these images will be combined with text to create educational/knowledge-based videos
- Output 80-120 words in English, only the scene description, no style keywords, and only use English text in the image if it is truly needed for the scene.

Only return the prompt itself, do not add any other explainations or marks."""  # noqa

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.num_parallel = getattr(self.config, 'llm_num_parallel', 10)
        self.style = getattr(self.config.text2image, 't2i_style', 'realistic')
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
                                segment, self.config, self.style, self.system,
                                self.illustration_prompts_dir): i
                for i, segment in tasks
            }
            for future in as_completed(futures):
                future.result()
        return messages

    @staticmethod
    def _generate_illustration_prompts_static(i, segment, config, style,
                                              system,
                                              illustration_prompts_dir):
        """Static method for multiprocessing"""
        llm = LLM.from_config(config)
        GenerateIllustrationPrompts._generate_illustration_impl(
            llm, i, segment, style, system, illustration_prompts_dir)
        GenerateIllustrationPrompts._generate_foreground_impl(
            llm, i, segment, system, illustration_prompts_dir)

    @staticmethod
    def _generate_illustration_impl(llm, i, segment, style, system,
                                    illustration_prompts_dir):
        if os.path.exists(
                os.path.join(illustration_prompts_dir, f'segment_{i+1}.txt')):
            return
        background = segment['background']
        manim_query = ''
        if segment.get('manim'):
            manim_query = (
                f'There is a manim animation at the front of the generated image: {segment["manim"]}, '
                f'you need to make the image background not steal the focus from the manim animation.'
            )
        query = (f'The style required from user is: {style}, '
                 f'illustration based on: {segment["content"]}, '
                 f'{manim_query}, '
                 f'Requirements from the storyboard designer: {background}')
        logger.info(
            f'Generating illustration prompt for : {segment["content"]}.')
        inputs = [
            Message(role='system', content=system),
            Message(role='user', content=query),
        ]
        _response_message = llm.generate(inputs)
        response = _response_message.content
        prompt = response.strip()
        with open(
                os.path.join(illustration_prompts_dir, f'segment_{i + 1}.txt'),
                'w') as f:
            f.write(prompt)

    @staticmethod
    def _generate_foreground_impl(llm, i, segment, system,
                                  illustration_prompts_dir):
        foreground = segment['foreground']
        for idx, _req in enumerate(foreground):
            if os.path.exists(
                    os.path.join(illustration_prompts_dir,
                                 f'segment_{i+1}_foreground_{idx+1}.txt')):
                return
            manim_query = ''
            if segment.get('manim'):
                manim_query = (
                    f'There is a manim animation which will use this generated image: {segment["manim"]}'
                )
            query = (f'illustration based on: {segment["content"]}, '
                     f'{manim_query}, '
                     f'Requirements from the storyboard designer: {_req}')
            logger.info(
                f'Generating foreground_{idx} illustration prompt for : {segment["content"]}.'
            )
            inputs = [
                Message(role='system', content=system),
                Message(role='user', content=query),
            ]
            _response_message = llm.generate(inputs)
            response = _response_message.content
            prompt = response.strip()
            with open(
                    os.path.join(illustration_prompts_dir,
                                 f'segment_{i+1}_foreground_{idx+1}.txt'),
                    'w') as f:
                f.write(prompt)
