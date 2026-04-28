# Copyright (c) ModelScope Contributors. All rights reserved.

import os
import sys

from ms_agent.agent import CodeAgent
from omegaconf import DictConfig


class RenderAnimation(CodeAgent):

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
            from render_manim import RenderManim
            sys.path.pop(0)
            agent = RenderManim(self.config, self.tag, self.trust_remote_code,
                                **kwargs)
            return await agent.execute_code(messages, **kwargs)
        elif engine == 'remotion':
            from render_remotion import RenderRemotion
            sys.path.pop(0)
            agent = RenderRemotion(self.config, self.tag,
                                   self.trust_remote_code, **kwargs)
            return await agent.execute_code(messages, **kwargs)
        else:
            raise ValueError(f'Unknown animation engine: {engine}')
