# Copyright (c) Alibaba, Inc. and its affiliates.
import argparse
import os.path
from abc import abstractmethod
from copy import deepcopy
from typing import Any, Dict, Union

from ms_agent.utils import get_logger
from omegaconf import DictConfig, ListConfig, OmegaConf
from omegaconf.basecontainer import BaseContainer

from modelscope import snapshot_download
from .env import Env

logger = get_logger()


class ConfigLifecycleHandler:

    def task_begin(self, config: DictConfig, tag: str) -> DictConfig:
        """Modify config when the task begins.

        Args:
            config(`DictConfig`): The config instance
            tag(`str`): The agent tag, you can handle multiple agents' config in one handler

        Returns:
            `DictConfig`: The modified config

        """
        return config

    def task_end(self, config: DictConfig, tag: str) -> DictConfig:
        """Modify config when the task ends, and config will be passed to the next agent in the workflow.

        If the next agent has its own config, this function will have no effect.

        Args:
            config(`DictConfig`): The config instance
            tag(`str`): The agent tag, you can handle multiple agents' config in one handler

        Returns:
            `DictConfig`: The modified config
        """
        return config


class Config:
    """All tasks begin from a config"""

    tag: str = ''
    supported_config_names = [
        'workflow.yaml', 'workflow.yml', 'agent.yaml', 'agent.yml'
    ]

    @classmethod
    def from_task(cls,
                  config_dir_or_id: str,
                  env: Dict[str, str] = None) -> Union[DictConfig, ListConfig]:
        """Read a task config file and return a config object.

        Args:
            config_dir_or_id: The local task directory or an id in the modelscope repository.
            env: The extra environment variables except ones already been included
                in the environment or in the `.env` file.

        Returns:
            The config object.
        """
        if not os.path.exists(config_dir_or_id):
            config_dir_or_id = snapshot_download(config_dir_or_id)

        config = None
        name = None
        if os.path.isfile(config_dir_or_id):
            config = OmegaConf.load(config_dir_or_id)
            name = os.path.basename(config_dir_or_id)
            config_dir_or_id = os.path.dirname(config_dir_or_id)
        else:
            for _name in Config.supported_config_names:
                config_file = os.path.join(config_dir_or_id, _name)
                if os.path.exists(config_file):
                    config = OmegaConf.load(config_file)
                    name = _name
                    break

        assert config is not None, (
            f'Cannot find any valid config file in {config_dir_or_id}, '
            f'supported configs are: {Config.supported_config_names}')
        envs = Env.load_env(env)
        cls._update_config(config, envs)
        _dict_config = cls.parse_args()
        cls._update_config(config, _dict_config)
        config.local_dir = config_dir_or_id
        config.name = name
        config = cls.fill_missing_fields(config)
        return config

    @staticmethod
    def fill_missing_fields(config: DictConfig) -> DictConfig:
        if not hasattr(config, 'tools') or config.tools is None:
            config.tools = DictConfig({})
        if not hasattr(config, 'callbacks') or config.callbacks is None:
            config.callbacks = ListConfig([])
        return config

    @staticmethod
    def is_workflow(config: DictConfig) -> bool:
        assert config.name is not None, 'Cannot find a valid name in this config'
        return config.name in ['workflow.yaml', 'workflow.yml']

    @staticmethod
    def parse_args() -> Dict[str, Any]:
        arg_parser = argparse.ArgumentParser()
        args, unknown = arg_parser.parse_known_args()
        _dict_config = {}
        if unknown:
            for idx in range(1, len(unknown) - 1, 2):
                key = unknown[idx]
                value = unknown[idx + 1]
                assert key.startswith(
                    '--'), f'Parameter not correct: {unknown}'
                _dict_config[key[2:]] = value
        return _dict_config

    @staticmethod
    def _update_config(config: Union[DictConfig, ListConfig],
                       extra: Dict[str, str] = None):
        if not extra:
            return config

        def traverse_config(_config: Union[DictConfig, ListConfig, Any]):
            if isinstance(_config, DictConfig):
                for name, value in _config.items():
                    if isinstance(value, BaseContainer):
                        traverse_config(value)
                    else:
                        # Find the key in extra that matches name (case-insensitive)
                        key_match = next(
                            (key
                             for key in extra if key.lower() == name.lower()),
                            None)
                        if key_match is not None:
                            logger.info(f'Replacing {name} with extra value.')
                            setattr(_config, name, extra[key_match])
                        if (isinstance(value, str) and value.startswith('<')
                                and value.endswith('>')
                                and value[1:-1] in extra):
                            logger.info(f'Replacing {value} with extra value.')
                            setattr(_config, name, extra[name])

            elif isinstance(_config, ListConfig):
                for idx in range(len(_config)):
                    value = _config[idx]
                    if isinstance(value, BaseContainer):
                        traverse_config(value)
                    else:
                        if (isinstance(value, str) and value.startswith('<')
                                and value.endswith('>')
                                and value[1:-1] in extra):
                            logger.info(f'Replacing {value} with extra value.')
                            _config[idx] = extra[value[1:-1]]

        traverse_config(config)
        return None

    @staticmethod
    def convert_mcp_servers_to_json(
            config: Union[DictConfig,
                          ListConfig]) -> Dict[str, Dict[str, Any]]:
        """Convert the mcp servers to json mcp config."""
        servers = {'mcpServers': {}}
        if getattr(config, 'tools', None):
            for server, server_config in config.tools.items():
                if getattr(server_config, 'mcp', True):
                    servers['mcpServers'][server] = deepcopy(server_config)
        return servers
