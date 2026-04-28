import os
from typing import Any, Dict

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase


class AudioGenerator(ToolBase):

    def __init__(self, config):
        super().__init__(config)
        self.temp_dir = os.path.join(self.output_dir, '.temp',
                                     'audio_generator')
        os.makedirs(self.temp_dir, exist_ok=True)
        audio_generator = self.config.audio_generator
        if audio_generator.type == 'edge_tts':
            from .edge_tts import EdgeTTSGenerator
            self.generator = EdgeTTSGenerator(self.config, self.temp_dir)
        else:
            raise NotImplementedError()

    async def connect(self) -> None:
        pass

    async def _get_tools_inner(self) -> Dict[str, Any]:
        return {
            'audio_generator': [
                Tool(
                    tool_name='generate_audio',
                    server_name='audio_generator',
                    description=
                    'Generate audio with a prompt, and return the audio file path.',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'text': {
                                'type': 'string',
                                'description': 'The text to generate speech'
                            },
                        },
                        'required': ['text'],
                        'additionalProperties': False
                    })
            ]
        }

    async def generate_audio(self, text, **kwargs):
        return await self.generator.generate_audio(text, **kwargs)

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        return await self.generate_audio(**tool_args)
