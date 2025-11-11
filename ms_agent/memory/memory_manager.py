# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
from typing import Any, Dict, List, Optional

from ms_agent.llm.utils import Message
from ms_agent.memory import Memory, memory_mapping
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class SharedMemoryManager:
    """Manager for shared memory instances across different agents."""
    _instances: Dict[str, Memory] = {}

    @classmethod
    def get_shared_memory(cls, config: DictConfig) -> Memory:
        """Get or create a shared memory instance based on configuration."""
        # Create a unique key based on memory configuration
        user_id: str = getattr(config, 'user_id', 'default_user')
        path: str = getattr(config, 'path', 'output')
        mem_instance_type: str = getattr(config, 'name')

        key = f'{mem_instance_type}_{user_id}_{path}'

        if key not in cls._instances:
            logger.info(f'Creating new shared memory instance for key: {key}')
            cls._instances[key] = memory_mapping[mem_instance_type](config)
        else:
            logger.info(
                f'Reusing existing shared memory instance for key: {key}')

        return cls._instances[key]

    @classmethod
    def clear_shared_memory(cls, config: DictConfig = None):
        """Clear shared memory instances. If config is provided, clear specific instance."""
        if config is None:
            cls._instances.clear()
            logger.info('Cleared all shared memory instances')
        else:
            user_id = getattr(config, 'user_id', 'default_user')
            path: str = getattr(config, 'path', 'output')
            key = f'{user_id}_{path}'

            if key in cls._instances:
                del cls._instances[key]
                logger.info(f'Cleared shared memory instance for key: {key}')
            else:
                logger.warning(
                    f'No shared memory instance found for key: {key}')
