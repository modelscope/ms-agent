# Copyright (c) ModelScope Contributors. All rights reserved.
"""Exercise DAG scheduling through local workflow and built-in agent loading."""
import tempfile
import unittest
from pathlib import Path

from omegaconf import OmegaConf

from ms_agent.workflow import DagWorkflow, WorkflowLoader


class TestDagWorkflow(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='ms-agent-dag-')
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.value = {'value': 23}
        OmegaConf.save(
            OmegaConf.create({
                'type': 'CodeAgent',
                'save_history': False,
                'output_dir': str(self.folder / 'output'),
            }), self.folder / 'identity.yaml')

    def build(self, tasks):
        config = {
            'type': 'DagWorkflow',
            **{
                name: dict(entry, agent_config='identity.yaml')
                for name, entry in tasks.items()
            },
        }
        path = self.folder / 'workflow.yaml'
        OmegaConf.save(OmegaConf.create(config), path)
        return WorkflowLoader.build(
            config_dir_or_id=str(path),
            trust_remote_code=False,
            load_cache=False)

    async def check_workflow(self, tasks, expected):
        workflow = self.build(tasks)
        self.assertIsInstance(workflow, DagWorkflow)
        actual = await workflow.run(dict(self.value))
        self.assertEqual(actual, expected)
        self.assertEqual(set(workflow.topo_order), set(tasks))
        # Config.from_task also adds local_dir, name, tools and callbacks.
        # Those entries describe the workflow, not additional agent tasks.
        self.assertEqual(workflow.nodes, set(tasks))

    async def test_single_task(self):
        await self.check_workflow({'only': {}}, {'only': self.value})

    async def test_single_task_with_empty_successors(self):
        await self.check_workflow({'only': {'next': []}},
                                  {'only': self.value})

    async def test_independent_tasks(self):
        await self.check_workflow({'a': {}, 'b': {}},
                                  {'a': self.value, 'b': self.value})

    async def test_independent_tasks_with_empty_successors(self):
        await self.check_workflow({'a': {'next': []}, 'b': {'next': []}},
                                  {'a': self.value, 'b': self.value})

    async def test_connected_and_isolated_tasks(self):
        await self.check_workflow(
            {'solo': {}, 'a': {'next': 'b'}, 'b': {}},
            {'solo': self.value, 'b': self.value})

    async def test_connected_and_isolated_task_with_empty_successors(self):
        await self.check_workflow(
            {'a': {'next': 'b'}, 'b': {}, 'solo': {'next': []}},
            {'b': self.value, 'solo': self.value})

    async def test_chain(self):
        await self.check_workflow({'a': {'next': 'b'}, 'b': {}},
                                  {'b': self.value})

    async def test_fork(self):
        await self.check_workflow(
            {'a': {'next': ['b', 'c']}, 'b': {}, 'c': {}},
            {'b': self.value, 'c': self.value})

    async def test_join(self):
        await self.check_workflow(
            {'a': {'next': 'c'}, 'b': {'next': 'c'}, 'c': {}},
            {'c': [self.value, self.value]})

    async def test_diamond(self):
        await self.check_workflow({
            'a': {'next': ['b', 'c']},
            'b': {'next': 'd'},
            'c': {'next': 'd'},
            'd': {},
        }, {'d': [self.value, self.value]})

    async def test_cycles_without_roots_are_rejected(self):
        for tasks in ({'a': {'next': 'a'}},
                      {'a': {'next': 'b'}, 'b': {'next': 'a'}}):
            with self.subTest(tasks=tasks):
                with self.assertRaisesRegex(ValueError, 'No root task found'):
                    self.build(tasks)


if __name__ == '__main__':
    unittest.main()
