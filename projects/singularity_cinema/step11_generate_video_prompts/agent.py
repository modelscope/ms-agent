# Copyright (c) Alibaba, Inc. and its affiliates.
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Union

import json
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM, Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class GenerateVideoPrompts(CodeAgent):

    system = ("""
You are an expert in creating scene descriptions for video generation. Based on given knowledge points or
storyboard scripts, generate detailed English descriptions for creating text-to-video content that align with
specified themes and styles.

Requirements:
- The generated video must depict only one scene, not multiple scenes.
- Video content needs to be clearly dynamic; avoid static feelings or stationary characters with only camera motion.
- Set appropriate scene changes based on the specified video length.
- Only add clear, readable text when it is truly necessary to express the knowledge point or scene meaning.
    Do not force specific words in every scene. If text is not needed, do not include it.
- All text in the video must be clear and readable and must not be distorted.
- All elements should be relevant to the theme and the meaning of the current subtitle segment.
- Video panel size is 1920*1080.
- The video needs to accurately reflect the text requirements.
- Output approximately 200 words in English.
- Return ONLY the prompt description. Do not include style keywords unless requested, and do not add
    explanations or markers.
    """)

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.num_parallel = getattr(self.config, 'llm_num_parallel', 10)
        self.video_prompts_dir = os.path.join(self.work_dir, 'video_prompts')
        os.makedirs(self.video_prompts_dir, exist_ok=True)

    async def execute_code(self, messages: Union[str, List[Message]],
                           **kwargs) -> List[Message]:
        if not self.config.use_text2video:
            return messages
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)
        with open(os.path.join(self.work_dir, 'topic.txt'), 'r') as f:
            topic = f.read()
        logger.info('Generating video prompts.')

        tasks = [(i, segment) for i, segment in enumerate(segments)]

        with ThreadPoolExecutor(max_workers=self.num_parallel) as executor:
            futures = {
                executor.submit(self._generate_video_prompts_static, i,
                                segment, self.config, topic, self.system,
                                self.video_prompts_dir): i
                for i, segment in tasks if 'video' in segment
            }
            for future in as_completed(futures):
                future.result()
        return messages

    @staticmethod
    def _generate_video_prompts_static(i, segment, config, topic, system,
                                       video_prompts_dir):
        llm = LLM.from_config(config)
        GenerateVideoPrompts._generate_video_prompt_impl(
            llm, i, segment, topic, system, video_prompts_dir, config)

    @staticmethod
    def _generate_video_prompt_impl(llm, i, segment, topic, system,
                                    video_prompts_dir, config):
        if os.path.exists(
                os.path.join(video_prompts_dir, f'segment_{i+1}.txt')):
            return

        work_dir = os.path.dirname(video_prompts_dir)
        with open(os.path.join(work_dir, 'audio_info.txt'), 'r') as f:
            audio_infos = json.load(f)

        audio_duration = audio_infos[i]['audio_duration']
        fit_duration = config.video_generator.seconds[0]
        for duration in config.video_generator.seconds:
            if duration > audio_duration:
                fit_duration = duration
                break

        video = segment['video']
        query = (f'The user original request is: {topic}, '
                 f'illustration based on: {segment["content"]}, '
                 f'Video duration: {fit_duration}, '
                 f'Requirements from the storyboard designer: {video}')
        logger.info(f'Generating video prompt for : {segment["content"]}.')
        inputs = [
            Message(role='system', content=system),
            Message(role='user', content=query),
        ]
        _response_message = llm.generate(inputs)
        response = _response_message.content
        prompt = response.strip()
        with open(
                os.path.join(video_prompts_dir, f'segment_{i + 1}.txt'),
                'w') as f:
            f.write(prompt)
