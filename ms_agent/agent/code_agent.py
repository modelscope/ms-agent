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
    """
    An agent that dynamically loads and executes a Python class from an external code file.

    This agent is designed to run custom logic defined in external `.py` files. It requires the user to explicitly trust
    remote or external code by setting `trust_remote_code=True`. The agent will locate the specified code file,
    load it into the current environment, and instantiate the first class extending `Code` found in that module.

    Args:
        config_dir_or_id (Optional[str]): Path or identifier to load the configuration from.
        config (Optional[DictConfig]): Pre-loaded configuration object.
        env (Optional[Dict[str, str]]): Additional environment variables to inject into the config.
        code_file (str): Path to the Python module containing the code logic to be executed.
        **kwargs: Additional keyword arguments passed to the parent Agent constructor.

    Raises:
        AssertionError: If required directories are missing or if external code execution is not trusted.
    """

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
        """
        Load and execute the external code module.

        This method verifies that external code execution is allowed (`trust_remote_code=True`),
        adds relevant paths to `sys.path`, imports the module, finds the appropriate class,
        instantiates it, and runs its `run()` method with the provided input.

        Args:
            inputs (Union[str, List[Message]]): Input data for the agent. Can be a raw string prompt,
                                               or a list of previous interaction messages.
            **kwargs: Additional runtime arguments passed to the code's `run()` method.

        Returns:
            List[Message]: A list of message objects representing the agent's response or interaction history.

        Raises:
            AssertionError: If no suitable class extending `Code` is found in the module.
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
