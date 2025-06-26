# Copyright (c) Alibaba, Inc. and its affiliates.
import importlib
import inspect
import os
import sys
from typing import Dict, Optional

from omegaconf import DictConfig

from . import Agent
from .code import Code


class CodeAgent(Agent):

    def __init__(self,
                 config_dir_or_id: Optional[str] = None,
                 config: Optional[DictConfig] = None,
                 env: Optional[Dict[str, str]] = None,
                 *,
                 code_file: str,
                 **kwargs):
        super().__init__(
            config_dir_or_id,
            config,
            env,
            tag=kwargs.get('tag'),
            trust_remote_code=kwargs.get('trust_remote_code', False))
        self.code_file = code_file

    async def run(self, inputs, **kwargs):
        """Run the agent.

        Args:
            inputs(`Union[str, List[Message]]`): The inputs can be a prompt string,
                or a list of messages from the previous agent
        Returns:
            The final messages
        """
        assert self.trust_remote_code, (
            f'[External Code]A code file is required to run in the CodeAgent: {self.code_file}'
            f'\nThis is external code, if you trust this code file, '
            f'please specify `--trust_remote_code true`')
        subdir = os.path.dirname(self.code_file)
        code_file = os.path.basename(self.code_file)
        local_dir = self.config.local_dir
        assert local_dir is not None, 'Using external py files, but local_dir cannot be found.'
        if subdir:
            subdir = os.path.join(local_dir, subdir)
        if local_dir not in sys.path:
            sys.path.insert(0, local_dir)
        if subdir and subdir not in sys.path:
            sys.path.insert(0, subdir)
        code_module = importlib.import_module(code_file)
        module_classes = {
            name: cls
            for name, cls in inspect.getmembers(code_module, inspect.isclass)
        }
        for name, cls in module_classes.items():
            if cls.__bases__[0] is Code and cls.__module__ == code_file:
                instance = cls(self.config)
                messages = await instance.run(inputs, **kwargs)
                return messages
        return inputs
