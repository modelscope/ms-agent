# Copyright (c) ModelScope Contributors. All rights reserved.
import asyncio
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
from typing import List, Union

import aiohttp
import json
import numpy as np
from ms_agent.agent import CodeAgent
from ms_agent.llm import Message
from ms_agent.tools.image_generator import ImageGenerator
from ms_agent.utils import get_logger
from omegaconf import DictConfig
from PIL import Image

logger = get_logger()


class GenerateImages(CodeAgent):

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.num_parallel = getattr(self.config, 't2i_num_parallel', 1)
        self.fusion = self.fade
        self.illustration_prompts_dir = os.path.join(self.work_dir,
                                                     'illustration_prompts')
        self.images_dir = os.path.join(self.work_dir, 'images')
        os.makedirs(self.images_dir, exist_ok=True)

    async def execute_code(self, messages: Union[str, List[Message]],
                           **kwargs) -> List[Message]:
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)
        illustration_prompts = []
        for i in range(len(segments)):
            illustration_path = os.path.join(self.illustration_prompts_dir,
                                             f'segment_{i+1}.txt')
            if self.config.background == 'image' and os.path.exists(
                    illustration_path):
                with open(illustration_path, 'r') as f:
                    illustration_prompts.append(f.read())
            else:
                illustration_prompts.append(None)
        logger.info('Generating images.')

        tasks = [
            (i, segment, prompt)
            for i, (segment,
                    prompt) in enumerate(zip(segments, illustration_prompts))
        ]

        # Use ThreadPoolExecutor for parallel execution
        with ThreadPoolExecutor(max_workers=self.num_parallel) as executor:
            futures = []
            for i, segment, prompt_text in tasks:
                # Clean background prompt too if it exists
                final_prompt = prompt_text
                if final_prompt:
                    # Remove thinking tags if present
                    final_prompt = re.sub(
                        r'<think>.*?</think>',
                        '',
                        final_prompt,
                        flags=re.DOTALL).strip()

                futures.append(
                    executor.submit(self._process_single_illustration_static,
                                    i, segment, final_prompt, self.config,
                                    self.images_dir))
            # Wait for all tasks to complete
            for future in futures:
                future.result()

        return messages

    @staticmethod
    def _process_single_illustration_static(i, segment, prompt, config,
                                            images_dir):
        """Static method for thread pool execution"""
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                GenerateImages._process_single_illustration_impl(
                    i, segment, prompt, config, images_dir))
            loop.run_until_complete(
                GenerateImages._process_foreground_illustration_impl(
                    i, segment, config, images_dir))
        finally:
            loop.close()

    @staticmethod
    async def _process_single_illustration_impl(i, segment, prompt, config,
                                                images_dir):
        """Implementation of single illustration processing"""
        if config.background != 'image':
            # Generate a 2000x2000 solid color image
            logger.info(
                f'Generating solid color background for segment {i + 1}.')
            output_path = os.path.join(images_dir, f'illustration_{i + 1}.png')
            if not os.path.exists(output_path):
                # Create a 2000x2000 image with the color defined in config.background
                img = Image.new('RGB', (2000, 2000), config.background)
                img.save(output_path)
        else:
            logger.info(f'Generating image for: {prompt}.')
            img_path = os.path.join(images_dir,
                                    f'illustration_{i + 1}_origin.png')
            output_path = os.path.join(images_dir, f'illustration_{i + 1}.png')
            if os.path.exists(output_path):
                return
            if prompt is None:
                return

            _config = deepcopy(config)
            _config.tools.image_generator = _config.image_generator
            image_generator = ImageGenerator(_config)

            kwargs = {}
            if hasattr(_config.image_generator, 'ratio'):
                kwargs['ratio'] = _config.image_generator.ratio
            elif hasattr(_config.image_generator, 'size'):
                kwargs['size'] = _config.image_generator.size

            logger.info(
                f'Generating image. Prompt: {prompt[:50]}... kwargs: {kwargs}')

            _temp_file = await image_generator.generate_image(prompt, **kwargs)

            # Check directly if the return is a valid file path
            if not _temp_file or not os.path.exists(_temp_file):
                logger.error(
                    f'Background image generation failed for segment {i + 1}. Result: {_temp_file}'
                )
                return

            shutil.move(_temp_file, img_path)
            GenerateImages.fade(img_path, output_path, segment)

            try:
                os.remove(img_path)
            except OSError:
                pass

    @staticmethod
    async def _process_foreground_illustration_impl(i, segment, config,
                                                    images_dir):
        """Implementation of foreground illustration processing"""
        if config.foreground != 'image':
            return
        logger.info(f'Generating foreground image for: segment {i}.')

        work_dir = getattr(config, 'output_dir', 'output')
        illustration_prompts_dir = os.path.join(work_dir,
                                                'illustration_prompts')
        foreground_assets = segment.get('foreground', [])

        for idx, _req in enumerate(foreground_assets):
            foreground_image = os.path.join(
                images_dir, f'illustration_{i + 1}_foreground_{idx + 1}.png')
            if os.path.exists(foreground_image):
                continue

            foreground_prompt_path = os.path.join(
                illustration_prompts_dir,
                f'segment_{i+1}_foreground_{idx+1}.txt')

            assert os.path.exists(foreground_prompt_path)

            with open(foreground_prompt_path, 'r') as f:
                prompt_text = f.read()

            # Clean Prompt from Thinking process
            prompt = re.sub(
                r'<think>.*?</think>', '', prompt_text,
                flags=re.DOTALL).strip()

            _config = deepcopy(config)
            _config.tools.image_generator = _config.image_generator
            image_generator = ImageGenerator(_config)

            kwargs = {}
            if hasattr(_config.image_generator, 'ratio'):
                kwargs['ratio'] = _config.image_generator.ratio
            elif hasattr(_config.image_generator, 'size'):
                kwargs['size'] = _config.image_generator.size

            _temp_file = await image_generator.generate_image(prompt, **kwargs)
            if not os.path.exists(_temp_file):
                raise RuntimeError(f'Failed to generate image: {_temp_file}')
            shutil.move(_temp_file, foreground_image)
            # Cleanup temp file if it still exists (shutil.move inside remove_white might differ)
            if os.path.exists(_temp_file):
                os.remove(_temp_file)

    @staticmethod
    def fade(input_image,
             output_image,
             segment,
             fade_factor=0.3,
             brightness_boost=80,
             opacity=1.0):
        # Support both 'manim' and 'remotion' keys for animation detection
        has_animation = segment.get('manim') or segment.get('remotion')
        img = Image.open(input_image).convert('RGBA')
        if has_animation:
            logger.info(
                'Applying fade effect to background image (Animation present)')
            arr = np.array(img, dtype=np.float32)
            arr[..., :3] = arr[..., :3] * fade_factor + brightness_boost
            arr[..., :3] = np.clip(arr[..., :3], 0, 255)
            arr[..., 3] = arr[..., 3] * opacity
            result = Image.fromarray(arr.astype(np.uint8), mode='RGBA')
            result.save(output_image, 'PNG')
            logger.info(f'Faded background saved to: {output_image}')
        else:
            logger.info('No animation - keeping original background')
            shutil.copy(input_image, output_image)
