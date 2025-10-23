# Copyright (c) Alibaba, Inc. and its affiliates.
from omegaconf import DictConfig, OmegaConf

from .default_memory import DefaultMemory

memory_mapping = {'default_memory': DefaultMemory}


def get_memory_meta_safe(config: DictConfig, key: str):
    trigger_config = getattr(config, key, OmegaConf.create({}))
    user_id = getattr(trigger_config, 'user_id', None)
    agent_id = getattr(trigger_config, 'agent_id',
                       None)  # task_end 默认用 self.tag
    run_id = getattr(trigger_config, 'run_id', None)
    memory_type = getattr(trigger_config, 'memory_type', None)
    return user_id, agent_id, run_id, memory_type
