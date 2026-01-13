# Copyright (c) Alibaba, Inc. and its affiliates.
import importlib.util
import os
import sys

from ms_agent.agent import CodeAgent
from omegaconf import DictConfig


class FixAnimation(CodeAgent):

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)

    async def execute_code(self, messages, **kwargs):
        engine = getattr(self.config, 'animation_engine', 'remotion')

        # Add the project root to sys.path to allow importing other steps
        project_root = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))

        if engine == 'manim':
            spec = importlib.util.spec_from_file_location(
                'step9_fix_manim_code.agent',
                os.path.join(project_root, 'step9_fix_manim_code', 'agent.py'))
            module = importlib.util.module_from_spec(spec)
            sys.modules['step9_fix_manim_code.agent'] = module
            spec.loader.exec_module(module)
            FixManimCode = module.FixManimCode

            agent = FixManimCode(self.config, self.tag, self.trust_remote_code,
                                 **kwargs)
            return await agent.execute_code(messages, **kwargs)
        elif engine == 'remotion':
            spec = importlib.util.spec_from_file_location(
                'step9_fix_remotion_code.agent',
                os.path.join(project_root, 'step9_fix_remotion_code',
                             'agent.py'))
            module = importlib.util.module_from_spec(spec)
            sys.modules['step9_fix_remotion_code.agent'] = module
            spec.loader.exec_module(module)
            FixRemotionCode = module.FixRemotionCode

            agent = FixRemotionCode(self.config, self.tag,
                                    self.trust_remote_code, **kwargs)
            return await agent.execute_code(messages, **kwargs)
        else:
            raise ValueError(f'Unknown animation engine: {engine}')
