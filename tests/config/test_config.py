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
    def test_from_task_does_not_leak_config_dir_patch(self):
        # A patch in the config file's own directory must NOT be merged by
        # from_task: overrides are anchored to the work dir, not the config
        # file's folder, so running a shared/template config never picks up
        # (or scatters) overrides in that folder.
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'agent.yaml'), 'w') as f:
                f.write('llm:\n  service: openai\n  model: base-model\n')
            patch_dir = os.path.join(d, '.ms_agent')
            os.makedirs(patch_dir)
            with open(os.path.join(patch_dir, 'config.yaml'), 'w') as f:
                f.write('llm:\n  model: override-model\n')

            with patch.object(sys, 'argv', ['ms-agent']):
                config = Config.from_task(d)
            # from_task leaves the committed model intact (no config-dir merge).
            self.assertEqual('base-model', config.llm.model)

    def test_work_dir_patch_merges(self):
        # The project patch is anchored to the work dir and applied by the
        # agent (BaseAgent.__init__ via ConfigResolver._load_project_patch).
        from omegaconf import OmegaConf

        from ms_agent.config.resolver import ConfigResolver
        with tempfile.TemporaryDirectory() as work:
            patch_dir = os.path.join(work, '.ms_agent')
            os.makedirs(patch_dir)
            with open(os.path.join(patch_dir, 'config.yaml'), 'w') as f:
                f.write('llm:\n  model: override-model\n')
            base = OmegaConf.create(
                {'llm': {'service': 'openai', 'model': 'base-model'}})
            patch_cfg = ConfigResolver()._load_project_patch(work)
            self.assertIsNotNone(patch_cfg)
            merged = OmegaConf.merge(base, patch_cfg)
            self.assertEqual('override-model', merged.llm.model)
            self.assertEqual('openai', merged.llm.service)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_from_task_without_patch(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'agent.yaml'), 'w') as f:
                f.write('llm:\n  service: openai\n  model: base-model\n')
            with patch.object(sys, 'argv', ['ms-agent']):
                config = Config.from_task(d)
            self.assertEqual('base-model', config.llm.model)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_parse_args_ignores_bare_separator(self):
        # A bare '--' separator must not be parsed as an empty-key override
        # (without the len(key) > 2 guard this yields {'': 'v'}).
        with patch.object(sys, 'argv', ['ms-agent', '--', '--', 'v']):
            parsed = Config.parse_args()
        self.assertNotIn('', parsed)


if __name__ == '__main__':
    unittest.main()
