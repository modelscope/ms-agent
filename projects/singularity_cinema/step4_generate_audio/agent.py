# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import os
import shutil
from copy import deepcopy
from dataclasses import dataclass, field
from typing import List

import edge_tts
import json
import numpy as np
from moviepy import AudioClip, AudioFileClip
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM
from ms_agent.llm.openai_llm import OpenAI
from ms_agent.tools.audio_generator import AudioGenerator
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


@dataclass
class Pattern:

    name: str
    pattern: str
    tags: List[str] = field(default_factory=list)


class GenerateAudio(CodeAgent):

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.llm: OpenAI = LLM.from_config(self.config)
        self.tts_dir = os.path.join(self.work_dir, 'audio')
        os.makedirs(self.tts_dir, exist_ok=True)
        self.voices = self.config.voices

    async def execute_code(self, messages, **kwargs):
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)
        logger.info('Generating audios.')

        tasks = []
        audio_paths = []
        for i, segment in enumerate(segments):
            logger.info(f'Generating audio for: {segment.get("content")}')
            audio_path = os.path.join(self.tts_dir, f'segment_{i + 1}.mp3')
            audio_paths.append(audio_path)
            tasks.append(self.generate_audio(segment, audio_path))
        audio_durations = await asyncio.gather(*tasks)
        assert len(audio_durations) == len(audio_paths)
        audio_info = []
        for audio_path, audio_duration in zip(audio_paths, audio_durations):
            audio_info.append({
                'audio_path': audio_path,
                'audio_duration': audio_duration,
            })
        with open(os.path.join(self.work_dir, 'audio_info.txt'), 'w') as f:
            f.write(json.dumps(audio_info, indent=4, ensure_ascii=False))
        return messages

    @staticmethod
    async def create_silent_audio(output_path, duration=5.0):

        def make_frame(t):
            return np.array([0.0, 0.0])

        audio = AudioClip(make_frame, duration=duration, fps=44100)
        audio.write_audiofile(output_path, verbose=False, logger=None)
        audio.close()

    async def audio_generate(self, text, output_file, speaker='male'):
        voice_dict = self.voices.get(speaker)
        voice = voice_dict.voice
        rate = voice_dict.get('rate', '+0%')
        pitch = voice_dict.get('pitch', '+0Hz')
        output_dir = os.path.dirname(output_file) or '.'
        os.makedirs(output_dir, exist_ok=True)
        _config = deepcopy(self.config)
        _config.tools.audio_generator = _config.audio_generator
        _temp_file = await AudioGenerator(self.config).generate_audio(
            text, speaker=voice, rate=rate, pitch=pitch)
        shutil.move(_temp_file, output_file)

    @staticmethod
    def get_audio_duration(audio_path):
        audio_clip = AudioFileClip(audio_path)
        duration = audio_clip.duration
        audio_clip.close()
        return duration

    async def generate_audio(self, segment, audio_path):
        tts_text = segment.get('content', '').strip()
        logger.info(f'Generating audio for {tts_text}')
        if os.path.exists(audio_path):
            return self.get_audio_duration(audio_path)
        if tts_text:
            await self.audio_generate(tts_text, audio_path, self.config.voice)
            return self.get_audio_duration(audio_path)
        else:
            await self.create_silent_audio(audio_path, duration=2.0)
            return 2.0
