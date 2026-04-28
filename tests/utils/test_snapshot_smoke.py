# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Smoke tests for the snapshot utility and LLMAgent rollback interface.

No network, no LLM — all tests run fully offline using tempfile directories.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from ms_agent.utils.snapshot import (
    list_snapshots,
    restore_snapshot,
    take_snapshot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def _read(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# ---------------------------------------------------------------------------
# snapshot utility tests
# ---------------------------------------------------------------------------

class TestTakeSnapshot(unittest.TestCase):

    def test_empty_dir_returns_none(self):
        """Nothing to commit → None."""
        with tempfile.TemporaryDirectory() as td:
            result = take_snapshot(td, 'empty')
            self.assertIsNone(result)

    def test_new_file_returns_hash(self):
        """A new file produces a commit hash."""
        with tempfile.TemporaryDirectory() as td:
            _write(os.path.join(td, 'hello.txt'), 'hello')
            h = take_snapshot(td, 'add hello.txt', message_count=2)
            self.assertIsNotNone(h)
            self.assertIsInstance(h, str)
            self.assertGreater(len(h), 0)

    def test_no_change_after_snapshot_returns_none(self):
        """Second snapshot with no changes → None."""
        with tempfile.TemporaryDirectory() as td:
            _write(os.path.join(td, 'f.txt'), 'v1')
            take_snapshot(td, 'first')
            result = take_snapshot(td, 'second — no change')
            self.assertIsNone(result)

    def test_message_truncated_to_120_chars(self):
        """Long messages are truncated in the commit subject."""
        with tempfile.TemporaryDirectory() as td:
            _write(os.path.join(td, 'f.txt'), 'x')
            h = take_snapshot(td, 'A' * 200)
            self.assertIsNotNone(h)
            snaps = list_snapshots(td)
            self.assertEqual(len(snaps[0]['message']), 120)

    def test_snapshot_dir_not_tracked(self):
        """The .ms_agent_snapshots dir itself must not appear in git status."""
        with tempfile.TemporaryDirectory() as td:
            _write(os.path.join(td, 'f.txt'), 'v1')
            take_snapshot(td, 'first')
            # After snapshot, no pending changes (snapshot dir excluded)
            result = take_snapshot(td, 'should be nothing')
            self.assertIsNone(result)


class TestListSnapshots(unittest.TestCase):

    def test_no_repo_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(list_snapshots(td), [])

    def test_returns_snapshots_most_recent_first(self):
        with tempfile.TemporaryDirectory() as td:
            _write(os.path.join(td, 'a.txt'), 'v1')
            h1 = take_snapshot(td, 'first snap', message_count=1)
            _write(os.path.join(td, 'a.txt'), 'v2')
            h2 = take_snapshot(td, 'second snap', message_count=3)

            snaps = list_snapshots(td)
            self.assertEqual(len(snaps), 2)
            # Most recent first
            self.assertEqual(snaps[0]['hash'], h2)
            self.assertEqual(snaps[1]['hash'], h1)

    def test_snapshot_fields(self):
        with tempfile.TemporaryDirectory() as td:
            _write(os.path.join(td, 'b.txt'), 'hello')
            h = take_snapshot(td, 'my message', message_count=5)
            snaps = list_snapshots(td)
            self.assertEqual(len(snaps), 1)
            s = snaps[0]
            self.assertEqual(s['hash'], h)
            self.assertEqual(s['message'], 'my message')
            self.assertEqual(s['message_count'], 5)
            self.assertIn('date', s)

    def test_message_count_default_zero(self):
        """message_count defaults to 0 when not passed."""
        with tempfile.TemporaryDirectory() as td:
            _write(os.path.join(td, 'c.txt'), 'x')
            take_snapshot(td, 'no count')
            snaps = list_snapshots(td)
            self.assertEqual(snaps[0]['message_count'], 0)


class TestRestoreSnapshot(unittest.TestCase):

    def test_no_repo_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            ok, mc = restore_snapshot(td, 'abc1234')
            self.assertFalse(ok)
            self.assertEqual(mc, 0)

    def test_restore_reverts_file_content(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'data.txt')
            _write(path, 'original')
            h1 = take_snapshot(td, 'original state', message_count=2)

            _write(path, 'modified')
            take_snapshot(td, 'modified state', message_count=4)

            self.assertEqual(_read(path), 'modified')

            ok, mc = restore_snapshot(td, h1)
            self.assertTrue(ok)
            self.assertEqual(mc, 2)
            self.assertEqual(_read(path), 'original')

    def test_restore_returns_message_count(self):
        with tempfile.TemporaryDirectory() as td:
            _write(os.path.join(td, 'x.txt'), 'a')
            h = take_snapshot(td, 'snap', message_count=7)
            _write(os.path.join(td, 'x.txt'), 'b')
            take_snapshot(td, 'snap2', message_count=9)

            ok, mc = restore_snapshot(td, h)
            self.assertTrue(ok)
            self.assertEqual(mc, 7)

    def test_restore_deleted_file(self):
        """A file deleted after snapshot is recreated on restore."""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'will_be_deleted.txt')
            _write(path, 'keep me')
            h = take_snapshot(td, 'before delete', message_count=1)

            os.remove(path)
            take_snapshot(td, 'after delete', message_count=2)
            self.assertFalse(os.path.exists(path))

            ok, _ = restore_snapshot(td, h)
            self.assertTrue(ok)
            self.assertTrue(os.path.exists(path))
            self.assertEqual(_read(path), 'keep me')


# ---------------------------------------------------------------------------
# LLMAgent interface tests
# ---------------------------------------------------------------------------

class TestLLMAgentSnapshotInterface(unittest.TestCase):
    """
    Tests for LLMAgent.list_snapshots() and LLMAgent.rollback().
    The LLM and tool_manager are not initialised — we only exercise the
    snapshot-related methods which don't require them.
    """

    def _make_agent(self, output_dir: str):
        from omegaconf import OmegaConf
        from ms_agent.agent.llm_agent import LLMAgent
        cfg = OmegaConf.create({
            'llm': {'model': 'fake', 'api_key': 'fake', 'model_server': 'openai'},
            'output_dir': output_dir,
        })
        agent = LLMAgent(cfg, tag='smoke-test')
        return agent

    def test_list_snapshots_empty(self):
        with tempfile.TemporaryDirectory() as td:
            agent = self._make_agent(td)
            self.assertEqual(agent.list_snapshots(), [])

    def test_list_snapshots_delegates_to_utility(self):
        with tempfile.TemporaryDirectory() as td:
            _write(os.path.join(td, 'f.txt'), 'v1')
            take_snapshot(td, 'snap', message_count=3)

            agent = self._make_agent(td)
            snaps = agent.list_snapshots()
            self.assertEqual(len(snaps), 1)
            self.assertEqual(snaps[0]['message_count'], 3)

    def test_rollback_restores_files_and_truncates_history(self):
        from omegaconf import OmegaConf
        from ms_agent.agent.llm_agent import LLMAgent
        from ms_agent.llm.utils import Message
        from ms_agent.utils import save_history

        with tempfile.TemporaryDirectory() as td:
            agent = self._make_agent(td)

            # Write a file and take a snapshot with message_count=2
            path = os.path.join(td, 'work.txt')
            _write(path, 'v1')
            h1 = take_snapshot(td, '[pre] first task', message_count=2)

            # Save 4 messages to history
            messages = [
                Message(role='system', content='sys'),
                Message(role='user', content='task1'),
                Message(role='assistant', content='done1'),
                Message(role='user', content='task2'),
            ]
            save_history(td, 'smoke-test', agent.config, messages)

            # Modify the file and take a second snapshot
            _write(path, 'v2')
            take_snapshot(td, '[pre] second task', message_count=4)

            self.assertEqual(_read(path), 'v2')

            # Rollback to h1
            ok = agent.rollback(h1)
            self.assertTrue(ok)

            # File should be restored
            self.assertEqual(_read(path), 'v1')

            # History should be truncated to message_count=2
            from ms_agent.utils import read_history
            _, saved = read_history(td, 'smoke-test')
            self.assertIsNotNone(saved)
            self.assertEqual(len(saved), 2)

    def test_rollback_clears_read_cache(self):
        with tempfile.TemporaryDirectory() as td:
            _write(os.path.join(td, 'f.txt'), 'v1')
            h = take_snapshot(td, 'snap', message_count=1)
            _write(os.path.join(td, 'f.txt'), 'v2')
            take_snapshot(td, 'snap2', message_count=2)

            agent = self._make_agent(td)

            # Attach a fake tool with _read_cache
            fake_tool = MagicMock()
            fake_tool._read_cache = {'some/path': {'mtime': 123}}
            fake_manager = MagicMock()
            fake_manager.extra_tools = [fake_tool]
            agent.tool_manager = fake_manager

            agent.rollback(h)
            self.assertEqual(fake_tool._read_cache, {})

    def test_rollback_invalid_hash_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            _write(os.path.join(td, 'f.txt'), 'v1')
            take_snapshot(td, 'snap')

            agent = self._make_agent(td)
            ok = agent.rollback('deadbeef')
            self.assertFalse(ok)

    def test_on_task_begin_auto_snapshots(self):
        """on_task_begin should take a snapshot automatically — no explicit call needed."""
        import asyncio
        from ms_agent.llm.utils import Message

        with tempfile.TemporaryDirectory() as td:
            _write(os.path.join(td, 'work.txt'), 'v1')
            agent = self._make_agent(td)

            messages = [
                Message(role='system', content='sys'),
                Message(role='user', content='do something useful'),
            ]

            # No explicit take_snapshot call — on_task_begin should do it
            asyncio.run(agent.on_task_begin(messages))

            snaps = list_snapshots(td)
            self.assertEqual(len(snaps), 1)
            self.assertIn('do something useful', snaps[0]['message'])
            self.assertEqual(snaps[0]['message_count'], len(messages))

    def test_on_task_begin_no_snapshot_when_disabled(self):
        """enable_snapshots=False suppresses automatic snapshot."""
        import asyncio
        from omegaconf import OmegaConf
        from ms_agent.agent.llm_agent import LLMAgent
        from ms_agent.llm.utils import Message

        with tempfile.TemporaryDirectory() as td:
            _write(os.path.join(td, 'work.txt'), 'v1')
            cfg = OmegaConf.create({
                'llm': {'model': 'fake', 'api_key': 'fake', 'model_server': 'openai'},
                'output_dir': td,
                'enable_snapshots': False,
            })
            agent = LLMAgent(cfg, tag='smoke-test')
            messages = [
                Message(role='system', content='sys'),
                Message(role='user', content='task'),
            ]
            asyncio.run(agent.on_task_begin(messages))
            self.assertEqual(list_snapshots(td), [])


if __name__ == '__main__':
    unittest.main()
