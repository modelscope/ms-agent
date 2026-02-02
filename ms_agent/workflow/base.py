# Copyright (c) ModelScope Contributors. All rights reserved.
from abc import ABC, abstractmethod
from typing import Dict, Optional

from ms_agent.config import Config
from omegaconf import DictConfig


class Workflow(ABC):
    """Base class for workflows that define a sequence of agent-based processing steps.

    A workflow manages the execution flow of multiple agents, each responsible for
    a specific task in the overall process. Subclasses should implement the `run` method.

    Args:
        config_dir_or_id (str): Path or ID to a directory containing the workflow configuration.
        config (DictConfig): Direct configuration dictionary for the workflow.
        env (Dict[str, str]): Environment variables used when loading the config.
        trust_remote_code (bool): Whether to allow loading of remote code. Defaults to False.
        **kwargs: Additional configuration options, including:
            - load_cache (bool): Whether to use cached results from previous runs. Default is True.
            - mcp_server_file (Optional[str]): Path to an MCP server file if needed. Default is None.
    """

    def __init__(self,
                 config_dir_or_id: Optional[str] = None,
                 config: Optional[DictConfig] = None,
                 env: Optional[Dict[str, str]] = None,
                 trust_remote_code: bool = False,
                 **kwargs):
        if config_dir_or_id is None:
            self.config = config
        else:
            self.config = Config.from_task(config_dir_or_id, env)
        self.config_dir_or_id = config_dir_or_id
        self.trust_remote_code = trust_remote_code
        self.load_cache = kwargs.get('load_cache', False)
        self.mcp_server_file = kwargs.get('mcp_server_file', None)
        self.env = env
        self.workflow_chains = []
        self.build_workflow()

    @abstractmethod
    def build_workflow(self):
        """Build the execution chain based on the configuration."""
        pass

    @abstractmethod
    async def run(self, inputs, **kwargs):
        pass
