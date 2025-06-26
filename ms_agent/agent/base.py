# Copyright (c) Alibaba, Inc. and its affiliates.
import importlib
import inspect
import sys
from abc import abstractmethod
from typing import Dict, List, Optional, Union

from ms_agent.config import Config
from ms_agent.config.config import ConfigLifecycleHandler
from ms_agent.llm import Message
from omegaconf import DictConfig


class Agent:
    """The base Agent class.

    Args:
        config_dir_or_id (`Optional[str]`): The directory or id of the config file.
        config (`Optional[DictConfig]`): The configuration object.
        env (`Optional[Dict[str, str]]`): The extra environment variables.
    """

    DEFAULT_TAG = 'Agent-default'

    def __init__(self,
                 config_dir_or_id: Optional[str] = None,
                 config: Optional[DictConfig] = None,
                 env: Optional[Dict[str, str]] = None,
                 tag: Optional[str] = None,
                 trust_remote_code: bool = False):
        if config_dir_or_id is None:
            self.config: DictConfig = config
        else:
            self.config: DictConfig = Config.from_task(config_dir_or_id, env)
        if tag is None:
            self.tag = getattr(config, 'tag', None) or self.DEFAULT_TAG
        else:
            self.tag = tag
        self.config.tag = self.tag
        self.trust_remote_code = trust_remote_code
        self.config.trust_remote_code = trust_remote_code
        self.handler: Optional[ConfigLifecycleHandler] = None
        self._register_config_handler()

    def _register_config_handler(self):
        handler_file = getattr(self.config, 'handler', None)
        if handler_file is not None:
            local_dir = self.config.local_dir
            assert self.trust_remote_code, (
                f'[External Code]A Config Lifecycle handler '
                f'registered in the config: {handler_file}. '
                f'\nThis is external code, if you trust this workflow, '
                f'please specify `--trust_remote_code true`')
            assert local_dir is not None, 'Using external py files, but local_dir cannot be found.'
            if local_dir not in sys.path:
                sys.path.insert(0, local_dir)

            handler_module = importlib.import_module(handler_file)
            module_classes = {
                name: cls
                for name, cls in inspect.getmembers(handler_module,
                                                    inspect.isclass)
            }
            for name, cls in module_classes.items():
                # Find cls which base class is `Callback`
                if cls.__bases__[
                        0] is ConfigLifecycleHandler and cls.__module__ == handler_file:
                    self.handler = cls()
            assert self.handler is not None, 'Config Lifecycle handler registered, but cannot be initialized.'

    def _task_begin(self):
        if self.handler is not None:
            self.config = self.handler.task_begin(self.config, self.tag)

    def prepare_config_for_next_step(self):
        """Call ConfigLifecycleHandler.task_end to prepare config for the next step.

        Returns:
            The new config for next step.
        """
        if self.handler is not None:
            config = self.handler.task_end(self.config, self.tag)
        else:
            config = self.config
        return config

    @abstractmethod
    async def run(self, inputs: Union[str, List[Message]],
                  **kwargs) -> List[Message]:
        """Run the agent.

        Args:
            inputs(`Union[str, List[Message]]`): The inputs can be a prompt string,
                or a list of messages from the previous agent
        Returns:
            The final messages
        """
        pass
