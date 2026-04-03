# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Smoke tests for TaskManager and AgentTool dynamic/background mode.
No network, no LLM — all tests run fully offline.
"""
import asyncio
import os
import sys
import unittest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from ms_agent.utils.task_manager import BackgroundTask, TaskManager


# ---------------------------------------------------------------------------
# TaskManager unit tests
# ---------------------------------------------------------------------------

class TestTaskManager(unittest.IsolatedAsyncioTestCase):

    async def test_register_and_complete(self):
        tm = TaskManager()
        task_id = tm.register('agent', 'my_tool', 'do something')
        self.assertIn(task_id, tm._tasks)
        self.assertEqual(tm._tasks[task_id].status, 'running')

        await tm.complete(task_id, 'great result')
        self.assertEqual(tm._tasks[task_id].status, 'completed')
        self.assertEqual(tm._tasks[task_id].result, 'great result')

        notifications = tm.drain_notifications()
        self.assertEqual(len(notifications), 1)
        self.assertIn('<status>completed</status>', notifications[0])
        self.assertIn('great result', notifications[0])
        self.assertIn(task_id, notifications[0])

    async def test_register_and_fail(self):
        tm = TaskManager()
        task_id = tm.register('agent', 'my_tool', 'do something')
        await tm.fail(task_id, 'something went wrong')
        self.assertEqual(tm._tasks[task_id].status, 'failed')

        notifications = tm.drain_notifications()
        self.assertEqual(len(notifications), 1)
        self.assertIn('<status>failed</status>', notifications[0])
        self.assertIn('something went wrong', notifications[0])

    def test_kill(self):
        tm = TaskManager()
        task_id = tm.register('agent', 'my_tool', 'do something')
        tm.kill(task_id)
        self.assertEqual(tm._tasks[task_id].status, 'killed')
        # kill again is a no-op
        tm.kill(task_id)
        self.assertEqual(tm._tasks[task_id].status, 'killed')

    def test_kill_all(self):
        tm = TaskManager()
        ids = [tm.register('agent', 'tool', f'task {i}') for i in range(3)]
        tm.kill_all()
        for tid in ids:
            self.assertEqual(tm._tasks[tid].status, 'killed')

    def test_drain_empty(self):
        tm = TaskManager()
        self.assertEqual(tm.drain_notifications(), [])

    async def test_drain_multiple(self):
        tm = TaskManager()
        id1 = tm.register('agent', 'tool_a', 'task a')
        id2 = tm.register('agent', 'tool_b', 'task b')
        await tm.complete(id1, 'result a')
        await tm.fail(id2, 'error b')
        notifications = tm.drain_notifications()
        self.assertEqual(len(notifications), 2)
        # drain again should be empty
        self.assertEqual(tm.drain_notifications(), [])

    def test_get_task(self):
        tm = TaskManager()
        task_id = tm.register('shell', 'bash', 'run script')
        task = tm.get_task(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task.task_type, 'shell')
        self.assertIsNone(tm.get_task('nonexistent'))

    def test_running_tasks(self):
        tm = TaskManager()
        id1 = tm.register('agent', 'tool', 'task 1')
        id2 = tm.register('agent', 'tool', 'task 2')
        tm.kill(id2)
        running = tm.running_tasks()
        self.assertEqual(len(running), 1)
        self.assertEqual(running[0].task_id, id1)

    async def test_notification_xml_structure(self):
        tm = TaskManager()
        task_id = tm.register('agent', 'searcher_tool', 'search for X')
        await tm.complete(task_id, 'found Y')
        notif = tm.drain_notifications()[0]
        self.assertTrue(notif.startswith('<task-notification>'))
        self.assertTrue(notif.strip().endswith('</task-notification>'))
        self.assertIn('<task-id>', notif)
        self.assertIn('<task-type>agent</task-type>', notif)
        self.assertIn('<tool-name>searcher_tool</tool-name>', notif)
        self.assertIn('<description>search for X</description>', notif)
        self.assertIn('<status>completed</status>', notif)
        self.assertIn('<result>found Y</result>', notif)
        self.assertIn('<duration_s>', notif)


# ---------------------------------------------------------------------------
# AgentTool dynamic spec (merged SplitTask) — schema validation only
# ---------------------------------------------------------------------------

class TestAgentToolDynamicSpec(unittest.TestCase):

    def _make_config(self):
        from omegaconf import OmegaConf
        return OmegaConf.create({
            'tag': 'test-agent',
            'output_dir': '/tmp/test_agent_tool',
            'tools': {
                'split_task': {
                    'tag_prefix': 'worker-',
                    'run_in_thread': False,
                    'run_in_process': False,
                }
            }
        })

    def test_split_task_spec_registered(self):
        from ms_agent.tools.agent_tool import AgentTool
        config = self._make_config()
        tool = AgentTool(config)
        self.assertTrue(tool.enabled)
        self.assertIn('split_to_sub_task', tool._specs)

    def test_split_task_spec_is_dynamic(self):
        from ms_agent.tools.agent_tool import AgentTool
        config = self._make_config()
        tool = AgentTool(config)
        spec = tool._specs['split_to_sub_task']
        self.assertTrue(spec.dynamic)
        self.assertFalse(spec.run_in_process)

    def test_split_task_parameters_schema(self):
        from ms_agent.tools.agent_tool import AgentTool
        config = self._make_config()
        tool = AgentTool(config)
        spec = tool._specs['split_to_sub_task']
        props = spec.parameters['properties']
        self.assertIn('tasks', props)
        self.assertIn('execution_mode', props)
        # execution_mode must have enum
        self.assertIn('enum', props['execution_mode'])
        self.assertIn('parallel', props['execution_mode']['enum'])
        self.assertIn('sequential', props['execution_mode']['enum'])

    def test_dynamic_mode_in_agent_tools_definitions(self):
        from ms_agent.tools.agent_tool import AgentTool
        from omegaconf import OmegaConf
        config = OmegaConf.create({
            'tag': 'test-agent',
            'output_dir': '/tmp/test_agent_tool',
            'tools': {
                'agent_tools': {
                    'definitions': [{
                        'tool_name': 'my_dynamic_tool',
                        'mode': 'dynamic',
                        'description': 'A dynamic tool',
                    }]
                }
            }
        })
        tool = AgentTool(config)
        self.assertIn('my_dynamic_tool', tool._specs)
        self.assertTrue(tool._specs['my_dynamic_tool'].dynamic)


# ---------------------------------------------------------------------------
# TaskControlTool unit tests
# ---------------------------------------------------------------------------

class TestTaskControlTool(unittest.IsolatedAsyncioTestCase):

    def _make_tool(self):
        from ms_agent.tools.task_control_tool import TaskControlTool
        from omegaconf import OmegaConf
        config = OmegaConf.create({'output_dir': '/tmp'})
        tool = TaskControlTool(config)
        tm = TaskManager()
        tool.set_task_manager(tm)
        return tool, tm

    async def test_list_tasks_empty(self):
        tool, _ = self._make_tool()
        result = await tool.call_tool('task_control', tool_name='list_tasks', tool_args={})
        self.assertEqual(result, 'No background tasks registered.')

    async def test_list_tasks_with_entries(self):
        import json
        tool, tm = self._make_tool()
        tm.register('agent', 'searcher', 'search X')
        result = await tool.call_tool('task_control', tool_name='list_tasks', tool_args={})
        rows = json.loads(result)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['tool_name'], 'searcher')
        self.assertEqual(rows[0]['status'], 'running')

    async def test_cancel_task(self):
        tool, tm = self._make_tool()
        task_id = tm.register('agent', 'searcher', 'search X')
        result = await tool.call_tool('task_control', tool_name='cancel_task',
                                      tool_args={'task_id': task_id})
        self.assertIn('cancelled', result)
        self.assertEqual(tm.get_task(task_id).status, 'killed')

    async def test_cancel_nonexistent(self):
        tool, _ = self._make_tool()
        result = await tool.call_tool('task_control', tool_name='cancel_task',
                                      tool_args={'task_id': 'bad-id'})
        self.assertIn('not found', result)

    async def test_cancel_already_done(self):
        tool, tm = self._make_tool()
        task_id = tm.register('agent', 'searcher', 'search X')
        tm.kill(task_id)
        result = await tool.call_tool('task_control', tool_name='cancel_task',
                                      tool_args={'task_id': task_id})
        self.assertIn('already', result)


if __name__ == '__main__':
    unittest.main()
