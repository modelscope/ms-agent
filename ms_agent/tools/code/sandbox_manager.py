# Copyright (c) Alibaba, Inc. and its affiliates.
from typing import Union

from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class SandboxManagerFactory:
    """Factory class for creating sandbox managers based on configuration"""

    @staticmethod
    async def create_manager(
        config: Union[DictConfig, dict]
    ) -> Union['LocalSandboxManager', 'HttpSandboxManager']:
        """
        Create and initialize a sandbox manager based on configuration.

        Args:
            config: Configuration object or dictionary

        Returns:
            Initialized sandbox manager instance

        Raises:
            ValueError: If sandbox mode is unknown
        """
        from ms_enclave.sandbox.manager import HttpSandboxManager, LocalSandboxManager

        # Extract sandbox configuration
        if isinstance(config, DictConfig):
            sandbox_config = config.get('sandbox', {})
        else:
            raise ValueError(f'Unknown config type: {type(config)}')

        mode = sandbox_config.get('mode', 'local')

        if mode == 'local':
            cleanup_interval = sandbox_config.get('cleanup_interval', 300)
            manager = LocalSandboxManager(cleanup_interval=cleanup_interval)
            logger.info(
                f'Created LocalSandboxManager with cleanup_interval={cleanup_interval}s'
            )

        elif mode == 'http':
            base_url = sandbox_config.get('http_url', 'http://localhost:8000')
            manager = HttpSandboxManager(base_url=base_url)
            logger.info(f'Created HttpSandboxManager with base_url={base_url}')

        else:
            raise ValueError(
                f"Unknown sandbox mode: {mode}. Must be 'local' or 'http'")

        return manager
