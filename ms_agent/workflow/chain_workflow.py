# Copyright (c) Alibaba, Inc. and its affiliates.
import os

from ms_agent.agent.loader import AgentLoader
from ms_agent.utils import get_logger
from ms_agent.workflow.base import Workflow
from omegaconf import DictConfig

logger = get_logger()


class ChainWorkflow(Workflow):
    """A workflow implementation that executes tasks in a sequential chain."""

    WORKFLOW_NAME = 'ChainWorkflow'

    def build_workflow(self):
        if not self.config:
            return

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
            config = getattr(task_info, 'agent_config', agent_config)
            assert isinstance(config, str)
            if not hasattr(task_info, 'agent'):
                task_info.agent = DictConfig({})
            init_args = getattr(task_info.agent, 'kwargs', {})
            init_args.pop('trust_remote_code', None)
            init_args['trust_remote_code'] = self.trust_remote_code
            init_args['mcp_server_file'] = self.mcp_server_file
            init_args['task'] = task
            init_args['load_cache'] = self.load_cache
            init_args['config_dir_or_id'] = os.path.join(
                self.config.local_dir, config)
            init_args['env'] = self.env
            if 'tag' not in init_args:
                init_args['tag'] = task
            engine = AgentLoader.build(**init_args)
            inputs = await engine.run(inputs)
            agent_config = engine.config
        return inputs
