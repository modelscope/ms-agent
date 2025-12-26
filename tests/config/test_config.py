# Copyright (c) Alibaba, Inc. and its affiliates.
import unittest

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


if __name__ == '__main__':
    unittest.main()
