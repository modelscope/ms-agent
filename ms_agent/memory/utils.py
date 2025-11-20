# Copyright (c) Alibaba, Inc. and its affiliates.
from omegaconf import DictConfig, OmegaConf

from .default_memory import DefaultMemory
from .diversity import Diversity

memory_mapping = {
    'default_memory': DefaultMemory,
    'diversity': Diversity,
}


def get_memory_meta_safe(config: DictConfig,
                         key: str,
                         default_user_id: str | None = None):
    trigger_config = getattr(config, key, None)
    if trigger_config is None:
        return None, None, None, None
    user_id = getattr(trigger_config, 'user_id', default_user_id)
    agent_id = getattr(trigger_config, 'agent_id',
                       None)  # task_end 默认用 self.tag
    run_id = getattr(trigger_config, 'run_id', None)
    memory_type = getattr(trigger_config, 'memory_type', None)
    return user_id, agent_id, run_id, memory_type
