# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import List, Union

import aiohttp
import json
from ms_agent.agent import CodeAgent
from ms_agent.llm import Message
from ms_agent.tools.video_generator import VideoGenerator
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class GenerateVideo(CodeAgent):

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.num_parallel = getattr(self.config, 't2v_num_parallel', 1)
        self.video_prompts_dir = os.path.join(self.work_dir, 'video_prompts')
        self.videos_dir = os.path.join(self.work_dir, 'videos')
        os.makedirs(self.videos_dir, exist_ok=True)

    async def execute_code(self, messages: Union[str, List[Message]],
                           **kwargs) -> List[Message]:
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)
        video_prompts = []
        for i in range(len(segments)):
            if 'video' in segments[i]:
                with open(
                        os.path.join(self.video_prompts_dir,
                                     f'segment_{i + 1}.txt'), 'r') as f:
                    video_prompts.append(f.read())
            else:
                video_prompts.append(None)
        logger.info('Generating videos.')

        tasks = [(i, segment, prompt)
                 for i, (segment,
                         prompt) in enumerate(zip(segments, video_prompts))]

        # Use ThreadPoolExecutor for parallel execution
        with ThreadPoolExecutor(max_workers=self.num_parallel) as executor:
            futures = [
                executor.submit(self._process_single_video_static, i, segment,
                                prompt, self.config, self.videos_dir)
                for i, segment, prompt in tasks
            ]
            # Wait for all tasks to complete
            for future in futures:
                future.result()

        return messages

    @staticmethod
    def _process_single_video_static(i, segment, prompt, config, videos_dir):
        """Static method for thread pool execution of video generation"""
        import asyncio
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                GenerateVideo._process_single_video_impl(
                    i, segment, prompt, config, videos_dir))
        finally:
            loop.close()

    @staticmethod
    async def _process_single_video_impl(i, segment, prompt, config,
                                         videos_dir):
        if prompt is None:
            logger.info(
                f'Skipping video generation for segment {i + 1} (no video prompt).'
            )
            return

        output_path = os.path.join(videos_dir, f'video_{i + 1}.mp4')
        if os.path.exists(output_path):
            logger.info(
                f'Video already exists for segment {i + 1}: {output_path}')
            return

        logger.info(f'Generating video for segment {i + 1}: {prompt}')
        work_dir = os.path.dirname(videos_dir)
        with open(os.path.join(work_dir, 'audio_info.txt'), 'r') as f:
            audio_infos = json.load(f)

        audio_duration = audio_infos[i]['audio_duration']
        fit_duration = config.text2video.t2v_seconds[0]
        for duration in config.text2video.t2v_seconds:
            fit_duration = duration
            if duration > audio_duration:
                break

        _config = deepcopy(config)
        _config.tools.video_generator = _config.video_generator
        video_generator = VideoGenerator(_config)

        _temp_file = await video_generator.generate_video(prompt, seconds=fit_duration)
        shutil.move(_temp_file, output_path)
