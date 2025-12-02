import os
import uuid
from io import BytesIO

import aiohttp
from PIL import Image


class DSImageGenerator:

    def __init__(self, config, temp_dir):
        self.config = config
        self.temp_dir = temp_dir
        os.makedirs(self.temp_dir, exist_ok=True)

    async def generate_image(self, positive_prompt, negative_prompt=None, size=None, ratio=None):
        image_generator = self.config.tools.image_generator
        base_url = (getattr(image_generator, 'base_url') or 'https://dashscope.aliyuncs.com/compatible-mode').strip('/')
        api_key = image_generator.api_key
        model_id = image_generator.model
        assert api_key is not None
        task_id = str(uuid.uuid4())[:8]
        output_file = os.path.join(self.temp_dir, f'{task_id}.png')

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }

        base_url = f'{base_url}/v1/chat/completions'

        request_body = {
            'model': model_id,
            'dashscope_extend_params': {
                'provider': 'b',
                'using_native_protocol': True
            },
            'stream': False,
            'contents': {
                'role': 'USER',
                'parts': {
                    'text': positive_prompt
                }
            },
            'generationConfig': {
                'responseModalities': ['TEXT', 'IMAGE'],
                "image_config": {
                    "aspect_ratio": ratio,
                    "image_size": size,
                },
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    base_url,
                    headers=headers,
                    json=request_body
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

                try:
                    image_url = data['candidates'][0]['content']['parts'][-1]['inlineData']['data']
                    async with session.get(image_url) as img_resp:
                        img_content = await img_resp.read()
                        image = Image.open(BytesIO(img_content))
                        image.save(output_file)
                        return output_file
                except KeyError:
                    return f'No image data found in response: {data}'
