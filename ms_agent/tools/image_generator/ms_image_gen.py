import asyncio
import os
import uuid
from io import BytesIO

import aiohttp
from PIL import Image


class MSImageGenerator:

    def __init__(self, config, temp_dir):
        self.config = config
        self.temp_dir = temp_dir
        os.makedirs(self.temp_dir, exist_ok=True)

    async def generate_image(self, positive_prompt, negative_prompt=None, size=None, **kwargs):
        image_generator = self.config.tools.image_generator
        base_url = (getattr(image_generator, 'base_url') or 'https://api-inference.modelscope.cn').strip('/')
        api_key = image_generator.api_key
        model_id = image_generator.model
        assert api_key is not None
        output_file = os.path.join(self.temp_dir, f'{str(uuid.uuid4())[:8]}.png')

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
                        'prompt': positive_prompt,
                        'negative_prompt': negative_prompt or '',
                        size: size or '',
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
                            image.save(output_file)
                        return output_file

                    elif data['task_status'] == 'FAILED':
                        return 'Generate image failed because of error: {data}'

                poll_interval = min(poll_interval * 1.5, max_poll_interval)
            return (f'Retrieval timeout, consider retry the task, or waiting for '
                    f'longer time(current is {max_wait_time}s).')

    async def call_tool(self, server_name: str, *, tool_name: str, tool_args: dict) -> str:
        return await self.generate_image(**tool_args)