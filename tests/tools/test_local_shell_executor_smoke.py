# Copyright (c) ModelScope Contributors. All rights reserved.
"""Regression: LocalCodeExecutionTool.shell_executor via ToolManager (no LLM / network)."""
import json
import os
import shutil
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent  # noqa: F401 — breaks tools import cycle
from ms_agent.llm.utils import ToolCall
from ms_agent.tools.tool_manager import ToolManager


class TestLocalShellExecutorSmoke(unittest.IsolatedAsyncioTestCase):

    async def test_shell_executor_via_tool_manager(self):
        td = tempfile.mkdtemp()
        try:
            cfg = OmegaConf.create({
                'output_dir': td,
                'tools': {
                    'code_executor': {
                        'mcp': False,
                        'implementation': 'python_env',
                        'include': ['shell_executor'],
                    },
                },
                'tool_call_timeout': 60,
            })
            tm = ToolManager(cfg)
            await tm.connect()
            self.assertIn('code_executor---shell_executor', tm._tool_index)

            tc = ToolCall(
                tool_name='code_executor---shell_executor',
                arguments={'command': 'echo ms_agent_shell_ok'},
                id='regression-call',
            )
            raw = await tm.single_call_tool(tc)
            data = json.loads(raw)
            self.assertTrue(data.get('success'), raw)
            self.assertIn('ms_agent_shell_ok', data.get('output', ''))
            await tm.cleanup()
        finally:
            shutil.rmtree(td, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
