# Copyright (c) ModelScope Contributors. All rights reserved.
import os
from omegaconf import DictConfig, OmegaConf
from typing import Dict

from ms_agent.memory import Memory, memory_mapping
from ms_agent.utils import get_logger
from ms_agent.utils.constants import DEFAULT_OUTPUT_DIR, DEFAULT_USER

logger = get_logger()


class SharedMemoryManager:
    """Manager for shared memory instances across different agents."""
    _instances: Dict[str, Memory] = {}

    @classmethod
    async def get_shared_memory(cls, config: DictConfig,
                                mem_instance_type: str) -> Memory:
        """Get or create a shared memory instance based on configuration."""
        node = getattr(config.memory, mem_instance_type, OmegaConf.create({}))
        # unified_memory namespaces the user under `namespace.user_id`;
        # legacy memories keep a top-level `user_id`. Honor both.
        user_id: str = getattr(node, 'user_id', None) or getattr(
            getattr(node, 'namespace', OmegaConf.create({})), 'user_id',
            None) or DEFAULT_USER
        # The store roots under the work dir (<output_dir>/.ms_agent/memory for
        # unified_memory), so the share key must isolate per resolved work dir —
        # otherwise two projects on the same model would read/write each
        # other's MEMORY.md through one cached instance.
        path: str = getattr(node, 'path', None) or getattr(
            config, 'output_dir', None) or DEFAULT_OUTPUT_DIR
        path = os.path.abspath(os.path.expanduser(str(path)))
        llm_str: str = getattr(config.llm, 'model', 'default_model')

        key = f'{mem_instance_type}_{user_id}_{llm_str}_{path}'

        if key not in cls._instances:
            logger.info(f'Creating new shared memory instance for key: {key}')
            cls._instances[key] = memory_mapping[mem_instance_type](config)
        else:
            logger.info(
                f'Reusing existing shared memory instance for key: {key}')

        return cls._instances[key]

    @classmethod
    def clear_shared_memory(cls, config: DictConfig, mem_instance_type: str):
        """Clear shared memory instances. If config is provided, clear specific instance."""
        if config is None:
            cls._instances.clear()
            logger.info('Cleared all shared memory instances')
        else:
            user_id = getattr(config, 'user_id', DEFAULT_USER)
            path: str = getattr(config, 'path', DEFAULT_OUTPUT_DIR)
            key = f'{mem_instance_type}_{user_id}_{path}'

            if key in cls._instances:
                del cls._instances[key]
                logger.info(f'Cleared shared memory instance for key: {key}')
            else:
                logger.warning(
                    f'No shared memory instance found for key: {key}')
