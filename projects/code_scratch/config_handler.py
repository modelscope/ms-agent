from ms_agent.config.config import ConfigLifecycleHandler
from omegaconf import DictConfig


class ConfigHandler(ConfigLifecycleHandler):
    """A handler to customize callbacks and tools for different phases."""

    def task_begin(self, config: DictConfig, tag: str) -> DictConfig:
        if 'worker' in tag:
            config.callbacks = ['callbacks/artifact_callback']
            delattr(config.tools, 'split_task')
        return config
