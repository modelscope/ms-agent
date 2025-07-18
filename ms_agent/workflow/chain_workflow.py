# Copyright (c) Alibaba, Inc. and its affiliates.
import os.path
from typing import Dict, Optional, Type

from ms_agent.agent import Agent
from ms_agent.config import Config
from ms_agent.utils import get_logger
from ms_agent.workflow.base import Workflow
from omegaconf import DictConfig

logger = get_logger()


class ChainWorkflow(Workflow):
    """A workflow implementation that executes tasks in a sequential chain.

    Tasks are defined in a configuration dictionary where each task specifies its next task(s).
    The chain starts from the task that is not listed as the 'next' of any other task.

    Args:
        config_dir_or_id (Optional[str]): Path or ID to a directory containing the workflow configuration.
        config (Optional[DictConfig]): Direct configuration dictionary for the workflow.
        env (Optional[Dict[str, str]]): Environment variables used when loading the config.
        trust_remote_code (Optional[bool]): Whether to allow loading of remote code. Defaults to False.
        **kwargs: Additional configuration options, including:
            - load_cache (bool): Whether to use cached results from previous runs. Default is True.
            - mcp_server_file (Optional[str]): Path to an MCP server file if needed. Default is None.
    """

    def __init__(self,
                 config_dir_or_id: Optional[str] = None,
                 config: Optional[DictConfig] = None,
                 env: Optional[Dict[str, str]] = None,
                 trust_remote_code: Optional[bool] = False,
                 **kwargs):
        if config_dir_or_id is None:
            self.config = config
        else:
            self.config = Config.from_task(config_dir_or_id, env)
        self.trust_remote_code = trust_remote_code or False
        self.load_cache = kwargs.get('load_cache', False)
        self.mcp_server_file = kwargs.get('mcp_server_file', None)
        self.workflow_chains = []
        self.build_workflow()

    def build_workflow(self):
        """
        Build the execution chain based on the configuration.

        Parses the workflow configuration to determine the order of tasks.
        Each task may specify a 'next' field indicating which task follows.
        This method constructs a list of task names representing the execution flow.

        Raises:
            ValueError: If no starting task can be determined (i.e., no task without a predecessor).
        """
        if not self.config:
            return []

        has_next = set()
        start_task = None
        for task_name, task_config in self.config.items():
            if 'next' in task_config:
                next_tasks = task_config['next']
                if isinstance(next_tasks, str):
                    has_next.add(next_tasks)
                else:
                    assert len(
                        next_tasks
                    ) == 1, 'ChainWorkflow only supports one next task'
                    has_next.update(next_tasks)

        for task_name in self.config.keys():
            if task_name not in has_next:
                start_task = task_name
                break

        if start_task is None:
            raise ValueError('No start task found')

        result = []
        current_task = start_task

        while current_task:
            result.append(current_task)
            next_task = None
            task_config = self.config[current_task]
            if 'next' in task_config:
                next_tasks = task_config['next']
                if isinstance(next_tasks, str):
                    next_task = next_tasks
                else:
                    next_task = next_tasks[0]

            current_task = next_task
        self.workflow_chains = result

    async def run(self, inputs, **kwargs):
        """
        Execute the chain of tasks sequentially.

        For each task in the built workflow chain:
        - Determine the agent type and instantiate it.
        - Run the agent with the provided inputs.
        - Pass the result as input to the next agent.

        Args:
            inputs (Any): Initial input data for the first task in the chain.
            **kwargs: Additional keyword arguments passed to each agent's run method.

        Returns:
            Any: The final output after executing all tasks in the chain.
        """
        agent_config = None
        for task in self.workflow_chains:
            task_info = getattr(self.config, task)
            agent_cls: Type[Agent] = self.find_agent(task_info.agent.name)
            _cfg = getattr(task_info, 'agent_config', agent_config)
            init_args = getattr(task_info.agent, 'kwargs', {})
            init_args.pop('trust_remote_code', None)
            init_args['trust_remote_code'] = self.trust_remote_code
            init_args['mcp_server_file'] = self.mcp_server_file
            init_args['task'] = task
            init_args['load_cache'] = self.load_cache
            if isinstance(_cfg, str):
                if agent_config is not None:
                    logger.info(
                        f'Task {task} has its own config: {_cfg}, '
                        f'the config from the previous task will be ignored.')
                agent = agent_cls(
                    config_dir_or_id=os.path.join(self.config.local_dir, _cfg),
                    **init_args)
            else:
                agent = agent_cls(config=_cfg, **init_args)
            inputs = await agent.run(inputs, **kwargs)
            agent_config = agent.prepare_config_for_next_step()
        return inputs
