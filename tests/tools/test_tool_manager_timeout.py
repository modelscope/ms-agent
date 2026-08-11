# Copyright (c) ModelScope Contributors. All rights reserved.
import os
import sys
import unittest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from ms_agent.agent.llm_agent import LLMAgent  # noqa: F401 — breaks tools import cycle

from ms_agent.tools.tool_manager import (
    effective_tool_wait_seconds,
    parse_timeout_from_tool_args,
)


class TestToolManagerTimeout(unittest.TestCase):

    def test_parse_timeout(self):
        self.assertIsNone(parse_timeout_from_tool_args(None))
        self.assertIsNone(parse_timeout_from_tool_args({}))
        self.assertIsNone(parse_timeout_from_tool_args({'timeout': None}))
        self.assertEqual(parse_timeout_from_tool_args({'timeout': 45}), 45.0)
        self.assertEqual(parse_timeout_from_tool_args({'timeout': '90'}), 90.0)
        self.assertIsNone(parse_timeout_from_tool_args({'timeout': True}))

    def test_effective_wait(self):
        self.assertEqual(
            effective_tool_wait_seconds(
                {},
                default_sec=120,
                max_sec=600,
            ),
            120.0,
        )
        self.assertEqual(
            effective_tool_wait_seconds(
                {'timeout': 30},
                default_sec=120,
                max_sec=600,
            ),
            30.0,
        )
        self.assertEqual(
            effective_tool_wait_seconds(
                {'timeout': 9999},
                default_sec=120,
                max_sec=600,
            ),
            600.0,
        )
        self.assertEqual(
            effective_tool_wait_seconds(
                {},
                default_sec=900,
                max_sec=600,
            ),
            600.0,
        )


if __name__ == '__main__':
    unittest.main()
