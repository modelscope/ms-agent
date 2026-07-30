# Copyright (c) Alibaba, Inc. and its affiliates.
import argparse
import os.path
from abc import abstractmethod
from copy import deepcopy
from omegaconf import DictConfig, ListConfig, OmegaConf
from omegaconf.basecontainer import BaseContainer
from typing import Any, Dict, Union

from modelscope import snapshot_download
from ms_agent.prompting import apply_prompt_files
from ms_agent.utils import get_logger
from ..utils.constants import TOOL_PLUGIN_NAME
from .env import Env

logger = get_logger()

# Ambient shell/system environment variables that must NOT act as config
# overrides. ``_update_config`` matches config leaf keys against env names
# case-insensitively, so without this a config key like ``path`` (e.g. a skill
# source ``sources[].path``) gets silently clobbered by the shell's ``$PATH``
# (``home``←``HOME``, ``user``←``USER``, ... likewise). Legitimate overrides
# (``OPENAI_API_KEY`` → ``llm.openai_api_key``, ``<placeholder>`` substitution,
# explicit ``--key value`` argv) are unaffected — only these ambient names are
# dropped from the env-derived override source.
_SHELL_ENV_BLOCKLIST = frozenset({
    'PATH',
    'HOME',
    'USER',
    'LOGNAME',
    'SHELL',
    'PWD',
    'OLDPWD',
    'TERM',
    'LANG',
    'LANGUAGE',
    'LC_ALL',
    'LC_CTYPE',
    'TMPDIR',
    'TMP',
    'TEMP',
    'EDITOR',
    'VISUAL',
    'PAGER',
    'DISPLAY',
    'HOSTNAME',
    'HOST',
    'MAIL',
    'SHLVL',
    'COLUMNS',
    'LINES',
    'IFS',
    'PS1',
    'PS2',
    'MANPATH',
    'LD_LIBRARY_PATH',
    'DYLD_LIBRARY_PATH',
    'PYTHONPATH',
    'CONDA_PREFIX',
    'CONDA_DEFAULT_ENV',
    'VIRTUAL_ENV',
    'SSH_AUTH_SOCK',
    'COLORTERM',
    'TERM_PROGRAM',
    'TERM_SESSION_ID',
    'XPC_SERVICE_NAME',
})


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
        # Drop ambient shell vars so they can't clobber same-named config keys
        # (e.g. skills sources[].path <- $PATH). See _SHELL_ENV_BLOCKLIST.
        envs = {
            k: v
            for k, v in envs.items() if k.upper() not in _SHELL_ENV_BLOCKLIST
        }
        cls._update_config(config, envs)
        _dict_config = cls.parse_args()
        cls._update_config(config, _dict_config)
        config.local_dir = config_dir_or_id
        config.name = name
        # The project-level config patch (persisted /model overrides etc.) is
        # merged by the agent from <work_dir>/.ms_agent/config.yaml, anchored to
        # the work dir — NOT here from the config file's own directory, which
        # would leak/scatter overrides when a shared or packaged template config
        # is run from a different working directory. See BaseAgent.__init__.
        config = cls.fill_missing_fields(config)
        # Prompt files: resolve config.prompt.system from prompts/ directory
        # if user didn't specify inline prompt.system.
        try:
            if isinstance(config, DictConfig):
                config = apply_prompt_files(config)
        except Exception:
            # Never block config loading due to prompt resolving.
            pass
        return config

    @staticmethod
    def fill_missing_fields(config: DictConfig) -> DictConfig:
        if not hasattr(config, 'tools') or config.tools is None:
            config.tools = DictConfig({})
        if not hasattr(config, 'callbacks') or config.callbacks is None:
            config.callbacks = ListConfig([])
        return config

    @staticmethod
    def safe_get_config(config: Union[DictConfig, ListConfig],
                        dotted_path: str,
                        default: Any = None) -> Any:
        """Safely read a dotted config path, returning ``default`` if missing.

        Example::

            Config.safe_get_config(cfg, 'tools.file_system.include', [])
        """
        try:
            value = OmegaConf.select(config, dotted_path, default=default)
        except Exception:
            return default
        return value if value is not None else default

    @staticmethod
    def is_workflow(config: DictConfig) -> bool:
        assert config.name is not None, 'Cannot find a valid name in this config'
        return config.name in [
            'workflow.yaml', 'workflow.yml', 'simple_workflow.yaml',
            'simple_workflow.yml'
        ]

    @staticmethod
    def parse_args() -> Dict[str, Any]:
        """Best-effort extraction of ad-hoc ``--key value`` overrides from argv.

        This is called by :meth:`from_task` for every config load, including
        embedded / non-CLI contexts (pytest, WebUI/Server, TUI). It therefore
        must never raise on argv shapes it does not recognize: it scans for
        well-formed ``--key value`` pairs and silently ignores everything else
        (subcommands, pytest flags, positional test paths, ``-x`` short flags).
        Unknown override keys are harmless downstream — ``_update_config`` only
        replaces config paths that already exist.
        """
        arg_parser = argparse.ArgumentParser(add_help=False)
        _, unknown = arg_parser.parse_known_args()
        _dict_config: Dict[str, Any] = {}
        idx = 0
        while idx < len(unknown):
            key = unknown[idx]
            if (key.startswith('--') and len(key) > 2
                    and idx + 1 < len(unknown)
                    and not unknown[idx + 1].startswith('--')):
                _dict_config[key[2:]] = unknown[idx + 1]
                idx += 2
            else:
                idx += 1
        return _dict_config

    @staticmethod
    def _update_config(config: Union[DictConfig, ListConfig],
                       extra: Dict[str, str] = None):
        if not extra:
            return config

        def traverse_config(_config: Union[DictConfig, ListConfig, Any],
                            path: str = ''):
            if isinstance(_config, DictConfig):
                for name, value in _config.items():
                    current_path = f'{path}.{name}' if path else name

                    if isinstance(value, BaseContainer):
                        traverse_config(value, current_path)
                    else:
                        if current_path in extra:
                            logger.info(
                                f'Replacing {current_path} with extra value.')
                            # Convert temperature to float and max_tokens to int if they're numeric strings
                            value_to_set = extra[current_path]
                            if name == 'temperature' and isinstance(
                                    value_to_set, str):
                                try:
                                    value_to_set = float(value_to_set)
                                except (ValueError, TypeError):
                                    pass
                            elif name == 'max_tokens' and isinstance(
                                    value_to_set, str):
                                try:
                                    value_to_set = int(value_to_set)
                                except (ValueError, TypeError):
                                    pass
                            setattr(_config, name, value_to_set)
                        # Find the key in extra that matches name (case-insensitive)
                        elif (key_match := next(
                            (key
                             for key in extra if key.lower() == name.lower()),
                                None)) is not None:
                            logger.info(f'Replacing {name} with extra value.')
                            # Convert temperature to float and max_tokens to int if they're numeric strings
                            value_to_set = extra[key_match]
                            if name == 'temperature' and isinstance(
                                    value_to_set, str):
                                try:
                                    value_to_set = float(value_to_set)
                                except (ValueError, TypeError):
                                    pass
                            elif name == 'max_tokens' and isinstance(
                                    value_to_set, str):
                                try:
                                    value_to_set = int(value_to_set)
                                except (ValueError, TypeError):
                                    pass
                            setattr(_config, name, value_to_set)
                        # Handle placeholder replacement like <api_key>
                        elif (isinstance(value, str) and value.startswith('<')
                              and value.endswith('>')
                              and value[1:-1] in extra):
                            logger.info(f'Replacing {value} with extra value.')
                            setattr(_config, name, extra[value[1:-1]])

            elif isinstance(_config, ListConfig):
                for idx in range(len(_config)):
                    value = _config[idx]
                    if isinstance(value, BaseContainer):
                        traverse_config(value, path)
                    else:
                        if (isinstance(value, str) and value.startswith('<')
                                and value.endswith('>')
                                and value[1:-1] in extra):
                            logger.info(f'Replacing {value} with extra value.')
                            _config[idx] = extra[value[1:-1]]

        traverse_config(config)

        for key, value in extra.items():
            if '.' in key and not key.startswith('tools.'):
                parts = key.split('.')
                current = config
                # Navigate/create nested structure
                for i, part in enumerate(parts[:-1]):
                    if not hasattr(current,
                                   part) or getattr(current, part) is None:
                        setattr(current, part, DictConfig({}))
                    current = getattr(current, part)
                final_key = parts[-1]
                if not hasattr(current, final_key) or getattr(
                        current, final_key) is None:
                    logger.info(f'Adding new config key: {key}')
                    # Convert temperature to float and max_tokens to int if they're numeric strings
                    value_to_set = value
                    if final_key == 'temperature' and isinstance(
                            value_to_set, str):
                        try:
                            value_to_set = float(value_to_set)
                        except (ValueError, TypeError):
                            pass
                    elif final_key == 'max_tokens' and isinstance(
                            value_to_set, str):
                        try:
                            value_to_set = int(value_to_set)
                        except (ValueError, TypeError):
                            pass
                    setattr(current, final_key, value_to_set)

        return None

    @staticmethod
    def convert_mcp_servers_to_json(
            config: Union[DictConfig,
                          ListConfig]) -> Dict[str, Dict[str, Any]]:
        """Convert the mcp servers to json mcp config."""
        servers = {'mcpServers': {}}
        if getattr(config, 'tools', None):
            for server, server_config in config.tools.items():
                if server == TOOL_PLUGIN_NAME:
                    continue
                if getattr(server_config, 'mcp', True):
                    servers['mcpServers'][server] = deepcopy(server_config)
        return servers
