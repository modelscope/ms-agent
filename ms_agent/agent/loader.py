# Copyright (c) Alibaba, Inc. and its affiliates.
import importlib
import inspect
import os
import sys
from typing import Dict, Optional

from ms_agent.config.config import Config
from ms_agent.utils.constants import DEFAULT_AGENT_FILE, DEFAULT_TAG
from omegaconf import DictConfig, OmegaConf

from .base import Agent


class AgentLoader:

    @classmethod
    def build(cls,
              config_dir_or_id: Optional[str] = None,
              config: Optional[DictConfig] = None,
              env: Optional[Dict[str, str]] = None,
              tag: Optional[str] = None,
              trust_remote_code: bool = False,
              **kwargs) -> Agent:
        agent_config: Optional[DictConfig] = None
        if config_dir_or_id is not None:
            if not os.path.exists(config_dir_or_id):
                from modelscope import snapshot_download
                config_dir_or_id = snapshot_download(config_dir_or_id)
            agent_config: DictConfig = Config.from_task(config_dir_or_id, env)
        if config is not None:
            if agent_config is not None:
                agent_config = OmegaConf.merge(agent_config, config)
            else:
                agent_config = config

        if tag is None:
            agent_tag = getattr(agent_config, 'tag', None) or DEFAULT_TAG
        else:
            agent_tag = tag
        agent_config.tag = agent_tag
        agent_config.trust_remote_code = trust_remote_code
        if getattr(agent_config, 'local_dir',
                   None) is None and config_dir_or_id is not None:
            agent_config.local_dir = config_dir_or_id

        from .llm_agent import LLMAgent
        from .code_agent import CodeAgent
        agent_type = LLMAgent.AGENT_NAME
        if 'code_file' in kwargs:
            code_file = kwargs.pop('code_file')
        elif agent_config is not None:
            agent_type = getattr(agent_config, 'type',
                                 '').lower() or agent_type.lower()
            code_file = getattr(agent_config, 'code_file', None)
        else:
            assert getattr(agent_config, 'local_dir', None) is not None
            code_file = os.path.join(
                getattr(agent_config, 'local_dir', ''), DEFAULT_AGENT_FILE)

        if code_file is not None:
            agent_instance = cls._load_external_code(agent_config, code_file,
                                                     **kwargs)
        else:
            assert agent_config is not None
            if agent_type == LLMAgent.AGENT_NAME.lower():
                agent_instance = LLMAgent(agent_config, agent_tag,
                                          trust_remote_code, **kwargs)
            elif agent_type == CodeAgent.AGENT_NAME.lower():
                agent_instance = CodeAgent(agent_config, agent_tag,
                                           trust_remote_code, **kwargs)
            else:
                raise ValueError(f'Unknown agent type: {agent_type}')
        return agent_instance

    @classmethod
    def _load_external_code(cls, config, code_file, **kwargs) -> 'Agent':
        assert code_file is not None, 'Code file cannot be None'
        assert config.trust_remote_code, (
            f'[External Code]A code file is required to run in the LLMAgent: {code_file}'
            f'\nThis is external code, if you trust this code file, '
            f'please specify `--trust_remote_code true`')
        subdir = os.path.dirname(code_file)
        code_file = os.path.basename(code_file)
        local_dir = config.local_dir
        assert local_dir is not None, 'Using external py files, but local_dir cannot be found.'
        if subdir:
            subdir = os.path.join(local_dir, subdir)  # noqa
        if local_dir not in sys.path:
            sys.path.insert(0, local_dir)
        subdir_inserted = False
        if subdir and subdir not in sys.path:
            sys.path.insert(0, subdir)
            subdir_inserted = True
        if code_file.endswith('.py'):
            code_file = code_file[:-3]
        if code_file in sys.modules:
            del sys.modules[code_file]
        code_module = importlib.import_module(code_file)
        module_classes = {
            name: agent_cls
            for name, agent_cls in inspect.getmembers(code_module,
                                                      inspect.isclass)
        }
        agent_instance = None
        for name, agent_cls in module_classes.items():
            if Agent in agent_cls.__mro__[
                    1:] and agent_cls.__module__ == code_file:
                agent_instance = agent_cls(
                    config,
                    config.tag,
                    trust_remote_code=config.trust_remote_code,
                    **kwargs)
                break
        assert agent_instance is not None, f'Cannot find a proper agent class in the external code file: {code_file}'
        if subdir_inserted:
            sys.path.pop(0)
        return agent_instance
