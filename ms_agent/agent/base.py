# Copyright (c) Alibaba, Inc. and its affiliates.
import importlib
import inspect
import os
import sys
from abc import abstractmethod
from typing import Dict, List, Optional, Union

from ms_agent.config import Config
from ms_agent.config.config import ConfigLifecycleHandler
from ms_agent.llm import Message
from omegaconf import DictConfig

DEFAULT_YAML = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'agent.yaml')


class Agent:
    """
    Base class for all agents. Provides core functionality such as configuration loading,
    lifecycle handling via external code, and defining the interface for agent execution.

    The agent can be initialized either with a config object directly or by loading from a config directory or ID.
    If external code (e.g., custom handlers) is involved, the agent must be explicitly trusted via
    `trust_remote_code=True`.

    Args:
        config_dir_or_id (Optional[str]): Path or identifier to load the configuration from.
        config (Optional[DictConfig]): Pre-loaded configuration object.
        env (Optional[Dict[str, str]]): Additional environment variables to inject into the config.
        tag (Optional[str]): A custom tag for identifying this agent run.
        trust_remote_code (bool): Whether to allow loading of external code (e.g., custom handler modules).

    """

    DEFAULT_TAG = 'Agent-default'

    def __init__(self,
                 config_dir_or_id: Optional[str] = None,
                 config: Optional[DictConfig] = None,
                 env: Optional[Dict[str, str]] = None,
                 tag: Optional[str] = None,
                 trust_remote_code: bool = False):
        if config_dir_or_id is not None:
            self.config: DictConfig = Config.from_task(config_dir_or_id, env)
        elif config is not None:
            self.config: DictConfig = config
        else:
            self.config: DictConfig = Config.from_task(DEFAULT_YAML)

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
        """
        Registers a `ConfigLifecycleHandler` based on the configuration's `handler` field.

        This method dynamically imports and instantiates a subclass of `ConfigLifecycleHandler`
        defined in an external module. Requires `trust_remote_code=True` and a valid `local_dir`.

        Raises:
            AssertionError: If the handler cannot be found or loaded due to security restrictions or invalid paths.
        """
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
        """
        Invokes the `task_begin` method of the registered `ConfigLifecycleHandler`.

        This hook is called at the beginning of the task to allow for pre-processing logic
        such as logging, setup, or dynamic messages updates.
        """
        if self.handler is not None:
            self.config = self.handler.task_begin(self.config, self.tag)

    def prepare_config_for_next_step(self):
        """
        Invokes the `task_end` method of the registered `ConfigLifecycleHandler`, if any.

        This hook is typically called between steps to allow for post-processing logic
        and to generate an updated configuration for the next step.

        Returns:
            DictConfig: Updated configuration for the next step, or the original config if no handler exists.
        """
        if self.handler is not None:
            config = self.handler.task_end(self.config, self.tag)
        else:
            config = self.config
        return config

    @abstractmethod
    async def run(self, inputs: Union[str, List[Message]],
                  **kwargs) -> List[Message]:
        """
        Main method to execute the agent.

        This method should define the logic of how the agent processes input and generates output messages.

        Args:
            inputs (Union[str, List[Message]]): Input data for the agent. Can be a raw string prompt,
                                                or a list of previous interaction messages.
            **kwargs: Additional runtime arguments that may affect behavior.

        Returns:
            List[Message]: A list of message objects representing the agent's response or interaction history.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        pass
