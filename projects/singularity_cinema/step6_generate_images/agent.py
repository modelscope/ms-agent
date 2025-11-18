# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import List, Union

import aiohttp
import json
import numpy as np
from ms_agent.agent import CodeAgent
from ms_agent.llm import Message
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
        self.style = getattr(self.config.text2image, 't2i_style', 'realistic')
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
            with open(
                    os.path.join(self.illustration_prompts_dir,
                                 f'segment_{i+1}.txt'), 'r') as f:
                illustration_prompts.append(f.read())
        logger.info('Generating images.')

        tasks = [
            (i, segment, prompt)
            for i, (segment,
                    prompt) in enumerate(zip(segments, illustration_prompts))
        ]

        # Use ThreadPoolExecutor with asyncio event loop
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=self.num_parallel) as executor:
            futures = [
                loop.run_in_executor(executor,
                                     self._process_single_illustration_static,
                                     i, segment, prompt, self.config,
                                     self.images_dir, self.fusion.__name__)
                for i, segment, prompt in tasks
            ]
            await asyncio.gather(*futures)

        return messages

    @staticmethod
    def _process_single_illustration_static(i, segment, prompt, config,
                                            images_dir, fusion_name):
        """Static method for multiprocessing"""
        import asyncio
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
        logger.info(f'Generating image for: {prompt}.')
        img_path = os.path.join(images_dir, f'illustration_{i + 1}_origin.png')
        output_path = os.path.join(images_dir, f'illustration_{i + 1}.png')
        if os.path.exists(output_path):
            return

        await GenerateImages._generate_images_impl(prompt, img_path, config)

        if fusion_name == 'keep_only_black_for_folder':
            GenerateImages.keep_only_black_for_folder(img_path, output_path,
                                                      segment)
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
        logger.info(f'Generating foreground image for: segment {i}.')
        foreground = segment['foreground']
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
            await GenerateImages._generate_images_impl(prompt,
                                                       foreground_image,
                                                       config)

    @staticmethod
    async def _generate_images_impl(prompt,
                                    img_path,
                                    config,
                                    negative_prompt=None):
        """Implementation of image generation"""
        base_url = config.text2image.t2i_base_url.strip('/')
        api_key = config.text2image.t2i_api_key
        model_id = config.text2image.t2i_model
        assert api_key is not None

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    f'{base_url}/v1/images/generations',
                    headers={
                        **headers, 'X-ModelScope-Async-Mode': 'true'
                    },
                    json={
                        'model': model_id,
                        'prompt': prompt,
                        'negative_prompt': negative_prompt or '',
                        'size': '1664x1664'
                    }) as resp:
                resp.raise_for_status()
                task_id = (await resp.json())['task_id']

            max_wait_time = 600  # 10 min
            poll_interval = 2
            max_poll_interval = 10
            elapsed_time = 0

            while elapsed_time < max_wait_time:
                await asyncio.sleep(poll_interval)
                elapsed_time += poll_interval

                async with session.get(
                        f'{base_url}/v1/tasks/{task_id}',
                        headers={
                            **headers, 'X-ModelScope-Task-Type':
                            'image_generation'
                        }) as result:
                    result.raise_for_status()
                    data = await result.json()

                    if data['task_status'] == 'SUCCEED':
                        img_url = data['output_images'][0]
                        async with session.get(img_url) as img_resp:
                            img_content = await img_resp.read()
                            image = Image.open(BytesIO(img_content))
                            image.save(img_path)
                        return img_path

                    elif data['task_status'] == 'FAILED':
                        raise RuntimeError(
                            f'Generate image failed because of error: {data}')

                poll_interval = min(poll_interval * 1.5, max_poll_interval)

    @staticmethod
    def fade(input_image, output_image, segment):
        manim = segment.get('manim')
        img = Image.open(input_image).convert('RGBA')
        if manim:
            logger.info(
                'Applying fade effect to background image (Manim animation present)'
            )
            arr = np.array(img, dtype=np.float32)
            fade_factor = 0.5  # Reduce color intensity to 50%
            brightness_boost = 60  # Add brightness to lighten the image
            arr[..., :3] = arr[..., :3] * fade_factor + brightness_boost
            arr[..., :3] = np.clip(arr[..., :3], 0, 255)
            arr[..., 3] = arr[..., 3] * 0.7  # Reduce opacity to 70%
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
