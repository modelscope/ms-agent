from ms_agent.config.config import ConfigLifecycleHandler
from omegaconf import DictConfig


class ConfigHandler(ConfigLifecycleHandler):
    """A handler to customize callbacks and tools for different phases."""

    def task_begin(self, config: DictConfig, tag: str) -> DictConfig:
        if tag == 'Architecture':
            if '235' in config.llm.model:
                # 235B model works better with an arch review
                config.callbacks = ['codes/coding_callback']
            else:
                config.callbacks = ['codes/coding_callback']
        elif tag == 'Refiner':
            config.callbacks = ['codes/eval_callback', 'codes/coding_callback']
        elif 'worker' in tag:
            config.callbacks = ['codes/artifact_callback']
            delattr(config.tools, 'split_task')
            config.tools.file_system = DictConfig({
                'mcp':
                False,
                'exclude': ['create_directory', 'write_file', 'list_files']
            })
        return config
