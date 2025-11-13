# Copyright (c) Alibaba, Inc. and its affiliates.
from typing import Union

from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class SandboxManagerFactory:
    """Factory class for creating sandbox managers based on configuration"""

    @staticmethod
    def ensure_local_image_exists(image: str) -> bool:
        """
        Check if the image exists in the local Docker registry.
        Meanwhile, this operation also triggers Docker's index refresh,
        preventing failures when retrieving an image by its name.

        Args:
            image (str): The name of the image to check.

        Returns:
            bool: True if the image exists, False otherwise.

        Raises:
            RuntimeError: If there's an error checking image existence.
        """
        import docker

        try:
            client = docker.from_env()
            image_exists = any(image in img.tags
                               for img in client.images.list() if img.tags)
            if image_exists:
                logger.info(f'Image exists in local Docker registry: {image}')
            else:
                logger.info(
                    f'Image does not exist in local Docker registry: {image}')
            return image_exists
        except Exception as e:
            logger.error(f'Error checking if image exists: {e}')
            raise RuntimeError(f'Failed to check image existence: {e}')

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
        if isinstance(config, DictConfig) and hasattr(
                config, 'tools') and hasattr(config.tools, 'code_executor'):
            sandbox_config = getattr(config.tools.code_executor, 'sandbox', {})
        else:
            raise ValueError(f'Unknown config type: {type(config)}')

        mode = sandbox_config.get('mode', 'local')
        image = sandbox_config.get('image', '')
        logger.info(f'Sandbox config: {sandbox_config}')

        if mode == 'local':
            cleanup_interval = sandbox_config.get('cleanup_interval', 300)
            manager = LocalSandboxManager(cleanup_interval=cleanup_interval)
            logger.info(
                f'Created LocalSandboxManager with cleanup_interval={cleanup_interval}s'
            )

            if image:
                try:
                    if not SandboxManagerFactory.ensure_local_image_exists(
                            image):
                        raise ValueError(
                            f'Image "{image}" does not exist in local Docker registry'
                        )
                except RuntimeError as e:
                    raise ValueError(f'Error checking if image exists: {e}')
            else:
                logger.warning(
                    'No image specified for LocalSandboxManager, using default'
                )

        elif mode == 'http':
            base_url = sandbox_config.get('http_url', 'http://localhost:8000')
            manager = HttpSandboxManager(base_url=base_url)
            logger.info(f'Created HttpSandboxManager with base_url={base_url}')

        else:
            raise ValueError(
                f"Unknown sandbox mode: {mode}. Must be 'local' or 'http'")

        return manager
