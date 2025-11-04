# Copyright (c) Alibaba, Inc.
import os
from collections import defaultdict, deque
from typing import Any, Dict, List, Set

from ms_agent.agent.loader import AgentLoader
from ms_agent.utils import get_logger
from ms_agent.workflow.base import Workflow
from omegaconf import DictConfig

logger = get_logger()


class DagWorkflow(Workflow):
    """Workflow supporting multiple `next` tasks (DAG) with dynamic task execution."""

    WORKFLOW_NAME = 'DagWorkflow'

    def build_workflow(self):
        if not self.config:
            return

        # Build adjacency list graph and in-degree map
        self.graph: Dict[str, List[str]] = defaultdict(list)
        indegree: Dict[str, int] = defaultdict(int)
        tasks: Set[str] = set(self.config.keys())

        for task_name, task_config in self.config.items():
            if 'next' in task_config:
                next_tasks = task_config['next']
                if isinstance(next_tasks, str):
                    next_tasks = [next_tasks]
                for nxt in next_tasks:
                    self.graph[task_name].append(nxt)
                    indegree[nxt] += 1

        self.nodes = set(list(self.graph.keys()) + list(indegree.keys()))

        # Find root tasks (indegree==0)
        self.roots = [
            t for t in tasks if 'next' in self.config[t] and indegree[t] == 0
        ]
        if not self.roots:
            raise ValueError('No root task found for BranchWorkflow')

        # Precompute topological order (Kahn)
        q = deque(self.roots)
        self.topo_order: List[str] = []
        while q:
            node = q.popleft()
            self.topo_order.append(node)
            for child in self.graph.get(node, []):
                indegree[child] -= 1
                if indegree[child] == 0:
                    q.append(child)

        # Build parent map for fast lookup
        self.parents: Dict[str, List[str]] = defaultdict(list)
        for parent, children in self.graph.items():
            for child in children:
                self.parents[child].append(parent)

    async def run(self, inputs: Any, **kwargs):
        """Run tasks in topological order.

        Args:
            inputs: The initial input passed to root tasks (as the same object).

        Returns:
            Dict[str, Any]: mapping of terminal task name to its output.
        """
        outputs: Dict[str, Any] = {}
        for task in self.topo_order:
            # Prepare input for task
            if task in self.roots:
                task_input = inputs
            else:
                parent_outs = [outputs[p] for p in self.parents[task]]
                task_input = parent_outs if len(
                    parent_outs) > 1 else parent_outs[0]

            task_info: DictConfig = getattr(self.config, task)
            agent_cfg_path = os.path.join(self.config.local_dir,
                                          task_info.agent_config)
            if not hasattr(task_info, 'agent'):
                task_info.agent = DictConfig({})
            init_args = getattr(task_info.agent, 'kwargs', {})
            init_args['trust_remote_code'] = self.trust_remote_code
            init_args['mcp_server_file'] = self.mcp_server_file
            init_args['task'] = task
            init_args['load_cache'] = self.load_cache
            init_args['config_dir_or_id'] = agent_cfg_path
            init_args['env'] = self.env
            if 'tag' not in init_args:
                init_args['tag'] = task
            engine = AgentLoader.build(**init_args)
            result = await engine.run(task_input)
            outputs[task] = result

        # Return results of terminal nodes (no outgoing edges)
        terminals = [
            t for t in self.config.keys()
            if t not in self.graph and t in self.nodes
        ]
        return {t: outputs[t] for t in terminals}
