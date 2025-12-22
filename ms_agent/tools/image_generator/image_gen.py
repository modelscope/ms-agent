import os
from typing import Any, Dict

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase


class ImageGenerator(ToolBase):

    def __init__(self, config):
        super().__init__(config)
        self.temp_dir = os.path.join(self.output_dir, '.temp',
                                     'image_generator')
        os.makedirs(self.temp_dir, exist_ok=True)
        image_generator = self.config.image_generator
        if image_generator.type == 'modelscope':
            from .ms_image_gen import MSImageGenerator
            self.generator = MSImageGenerator(self.config, self.temp_dir)
        elif image_generator.type == 'dashscope':
            from .ds_image_gen import DSImageGenerator
            self.generator = DSImageGenerator(self.config, self.temp_dir)
        elif image_generator.type == 'google':
            from .google_image_gen import GoogleImageGenerator
            self.generator = GoogleImageGenerator(self.config, self.temp_dir)
        else:
            raise NotImplementedError()

    async def connect(self) -> None:
        pass

    async def _get_tools_inner(self) -> Dict[str, Any]:
        return {
            'image_generator': [
                Tool(
                    tool_name='generate_image',
                    server_name='image_generator',
                    description=
                    'Generate an image with a positive prompt, and return the image file path.',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'positive_prompt': {
                                'type': 'string',
                                'description':
                                'The prompt to generate the image.'
                            }
                        },
                        'required': ['positive_prompt'],
                        'additionalProperties': False
                    })
            ]
        }

    async def generate_image(self,
                             positive_prompt,
                             negative_prompt=None,
                             **kwargs):
        return await self.generator.generate_image(positive_prompt,
                                                   negative_prompt, **kwargs)

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        return await self.generate_image(**tool_args)
