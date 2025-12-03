# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import os
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
            ilustration_path = os.path.join(self.illustration_prompts_dir,
                                            f'segment_{i+1}.txt')
            if self.config.background == 'image' and os.path.exists(
                    ilustration_path):
                with open(ilustration_path, 'r') as f:
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
            futures = [
                executor.submit(self._process_single_illustration_static, i,
                                segment, prompt, self.config, self.images_dir,
                                self.fusion.__name__)
                for i, segment, prompt in tasks
            ]
            # Wait for all tasks to complete
            for future in futures:
                future.result()

        return messages

    @staticmethod
    def _process_single_illustration_static(i, segment, prompt, config,
                                            images_dir, fusion_name):
        """Static method for thread pool execution"""
        import asyncio
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                GenerateImages._process_single_illustration_impl(
                    i, segment, prompt, config, images_dir, fusion_name))
            loop.run_until_complete(
                GenerateImages._process_foreground_illustration_impl(
                    i, segment, config, images_dir))
        finally:
            loop.close()

    @staticmethod
    async def _process_single_illustration_impl(i, segment, prompt, config,
                                                images_dir, fusion_name):
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

            _temp_file = await image_generator.generate_image(prompt, ratio=_config.image_generator.ratio)
            shutil.move(_temp_file, img_path)
            if fusion_name == 'keep_only_black_for_folder':
                GenerateImages.keep_only_black_for_folder(
                    img_path, output_path, segment)
            else:
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
        foreground = segment.get('foreground', [])
        work_dir = getattr(config, 'output_dir', 'output')
        illustration_prompts_dir = os.path.join(work_dir,
                                                'illustration_prompts')
        for idx, _req in enumerate(foreground):
            foreground_image = os.path.join(
                images_dir, f'illustration_{i + 1}_foreground_{idx + 1}.png')
            if os.path.exists(foreground_image):
                continue

            foreground_prompt_path = os.path.join(
                illustration_prompts_dir,
                f'segment_{i+1}_foreground_{idx+1}.txt')
            with open(foreground_prompt_path, 'r') as f:
                prompt = f.read()

            _config = deepcopy(config)
            _config.tools.image_generator = _config.image_generator
            image_generator = ImageGenerator(_config)

            _temp_file = await image_generator.generate_image(prompt, ratio=_config.image_generator.ratio)
            shutil.move(_temp_file, foreground_image)

    @staticmethod
    def fade(input_image,
             output_image,
             segment,
             fade_factor=0.3,
             brightness_boost=80,
             opacity=1.0):
        manim = segment.get('manim')
        img = Image.open(input_image).convert('RGBA')
        if manim:
            logger.info(
                'Applying fade effect to background image (Manim animation present)'
            )
            arr = np.array(img, dtype=np.float32)
            arr[..., :3] = arr[..., :3] * fade_factor + brightness_boost
            arr[..., :3] = np.clip(arr[..., :3], 0, 255)
            arr[..., 3] = arr[..., 3] * opacity
            result = Image.fromarray(arr.astype(np.uint8), mode='RGBA')
            result.save(output_image, 'PNG')
            logger.info(f'Faded background saved to: {output_image}')
        else:
            logger.info('No Manim animation - keeping original background')
            shutil.copy(input_image, output_image)

    @staticmethod
    def keep_only_black_for_folder(input_image,
                                   output_image,
                                   segment,
                                   threshold=80):
        img = Image.open(input_image).convert('RGBA')
        arr = np.array(img)

        logger.info(f'Process image: {input_image}')
        logger.info(f'  Size: {img.size}')
        logger.info(f'  Mode: {img.mode}')
        logger.info(
            f'  Color range: R[{arr[..., 0].min()}-{arr[..., 0].max()}], G[{arr[..., 1].min()}-{arr[..., 1].max()}]'
            f', B[{arr[..., 2].min()}-{arr[..., 2].max()}]')

        gray = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
        mask = gray < threshold

        transparent_pixels = np.sum(mask)
        total_pixels = mask.size
        transparency_ratio = transparent_pixels / total_pixels
        logger.info(
            f'Black pixels detected: {transparent_pixels}/{total_pixels} ({transparency_ratio:.1%})'
        )

        arr[..., 3] = np.where(mask, 255, 0)

        img2 = Image.fromarray(arr, 'RGBA')
        img2.save(output_image, 'PNG')
        output_img = Image.open(output_image)
        output_arr = np.array(output_img)
        if output_img.mode == 'RGBA':
            alpha_channel = output_arr[..., 3]
            unique_alpha = np.unique(alpha_channel)
            logger.info(f'Transparent value: {unique_alpha}')
        else:
            logger.warn(f'Output image is not RGBA mode: {output_img.mode}')
