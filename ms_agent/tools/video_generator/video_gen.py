import os
from typing import Dict, Any

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase


class VideoGenerator(ToolBase):

    def __init__(self, config):
        super().__init__(config)
        self.temp_dir = os.path.join(self.output_dir, '.temp', 'video_generator')
        os.makedirs(self.temp_dir, exist_ok=True)
        video_generator = self.config.video_generator
        if video_generator.type == 'dashscope':
            from .ds_video_gen import DSVideoGenerator
            self.generator = DSVideoGenerator(self.config, self.temp_dir)
        else:
            raise NotImplementedError()

    async def connect(self) -> None:
        pass

    async def _get_tools_inner(self) -> Dict[str, Any]:
        return {
            'video_generator': [
                Tool(
                    tool_name='generate_video',
                    server_name='video_generator',
                    description=
                    'Generate a video with a positive prompt, and return the video file path.',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'positive_prompt': {
                                'type':
                                    'string',
                                'description':
                                    'The prompt to generate the image.'
                            },
                            'seconds': {
                                'type':
                                    'integer',
                                'description':
                                    'The generated video seconds, supported is 4/8/12'
                            }
                        },
                        'required': ['positive_prompt'],
                        'additionalProperties': False
                    })
            ]
        }

    async def generate_video(self, positive_prompt, **kwargs):
        return await self.generator.generate_video(positive_prompt, **kwargs)

    async def call_tool(self, server_name: str, *, tool_name: str, tool_args: dict) -> str:
        return await self.generate_video(**tool_args)