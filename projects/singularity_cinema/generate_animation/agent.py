# Copyright (c) ModelScope Contributors. All rights reserved.
import importlib.util
import os
import sys

from ms_agent.agent import CodeAgent
from omegaconf import DictConfig


class GenerateAnimation(CodeAgent):

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)

    async def execute_code(self, messages, **kwargs):
        engine = getattr(self.config, 'animation_engine', 'remotion')
        sys.path.insert(0, os.path.dirname(__file__))
        if engine == 'manim':
            from generate_manim_code import GenerateManimCode
            sys.path.pop(0)
            agent = GenerateManimCode(self.config, self.tag,
                                      self.trust_remote_code, **kwargs)
            return await agent.execute_code(messages, **kwargs)
        elif engine == 'remotion':
            from generate_remotion_code import GenerateRemotionCode
            sys.path.pop(0)
            agent = GenerateRemotionCode(self.config, self.tag,
                                         self.trust_remote_code, **kwargs)
            return await agent.execute_code(messages, **kwargs)
        else:
            raise ValueError(f'Unknown animation engine: {engine}')
