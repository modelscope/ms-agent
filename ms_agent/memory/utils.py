# Copyright (c) ModelScope Contributors. All rights reserved.
from omegaconf import DictConfig, OmegaConf

from .condenser.code_condenser import CodeCondenser
from .condenser.refine_condenser import RefineCondenser
from .default_memory import DefaultMemory
from .diversity import Diversity

memory_mapping = {
    'default_memory': DefaultMemory,
    'diversity': Diversity,
    'code_condenser': CodeCondenser,
    'refine_condenser': RefineCondenser,
}


def get_memory_meta_safe(config: DictConfig,
                         key: str,
                         default_user_id: str | None = None):
    if not hasattr(config, key):
        return None, None, None, None
    trigger_config = getattr(config, key, OmegaConf.create({}))
    user_id = getattr(trigger_config, 'user_id', default_user_id)
    agent_id = getattr(trigger_config, 'agent_id', None)
    run_id = getattr(trigger_config, 'run_id', None)
    memory_type = getattr(trigger_config, 'memory_type', None)
    return user_id, agent_id, run_id, memory_type
