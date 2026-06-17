# Copyright (c) ModelScope Contributors. All rights reserved.
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from ms_agent.config import Config
from omegaconf import DictConfig

from modelscope.utils.test_utils import test_level


class TestConfig(unittest.TestCase):

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_safe_get_config(self):
        config = DictConfig(
            {'tools': {
                'file_system': {
                    'system_for_abbreviations': 'test'
                }
            }})
        self.assertEqual(
            'test',
            Config.safe_get_config(
                config, 'tools.file_system.system_for_abbreviations'))
        delattr(config.tools, 'file_system')
        self.assertTrue(
            Config.safe_get_config(
                config, 'tools.file_system.system_for_abbreviations') is None)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_from_task_merges_project_patch(self):
        # A project patch (written by /model) wins over the committed YAML,
        # while the source file stays untouched.
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'agent.yaml'), 'w') as f:
                f.write('llm:\n  service: openai\n  model: base-model\n')
            patch_dir = os.path.join(d, '.ms-agent')
            os.makedirs(patch_dir)
            with open(os.path.join(patch_dir, 'config.yaml'), 'w') as f:
                f.write('llm:\n  model: override-model\n')

            # Isolate from pytest's argv, which Config.parse_args() scans.
            with patch.object(sys, 'argv', ['ms-agent']):
                config = Config.from_task(d)
            self.assertEqual('override-model', config.llm.model)
            # Untouched base key is preserved through the merge.
            self.assertEqual('openai', config.llm.service)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_from_task_without_patch(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'agent.yaml'), 'w') as f:
                f.write('llm:\n  service: openai\n  model: base-model\n')
            with patch.object(sys, 'argv', ['ms-agent']):
                config = Config.from_task(d)
            self.assertEqual('base-model', config.llm.model)


if __name__ == '__main__':
    unittest.main()
