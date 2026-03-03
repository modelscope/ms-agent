import os
import shutil
import tempfile
import unittest
from pathlib import Path

from ms_agent.tools.code_server.lsp_code_server import LSPCodeServer
from omegaconf import DictConfig


class TestLSP(unittest.TestCase):

    def setUp(self):
        print(('Testing %s.%s' % (type(self).__name__, self._testMethodName)))
        self.tmp_dir = tempfile.TemporaryDirectory().name
        if not os.path.exists(self.tmp_dir):
            os.makedirs(self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)
        super().tearDown()

    async def test_lsp(self):
        output_dir = self.tmp_dir
        os.makedirs(output_dir, exist_ok=True)
        lsp_config = DictConfig({
            'workspace_dir': str(output_dir),
            'output_dir': str(output_dir)
        })
        lsp_server = LSPCodeServer(lsp_config)
        await lsp_server.connect()

        await lsp_server._check_directory('', 'python')

        os.makedirs(os.path.join(output_dir, 'pkg1'), exist_ok=True)

        with open(os.path.join(output_dir, 'pkg1', 'test.py'), 'w') as f:
            f.write('')

        result = await lsp_server._update_and_check(
            os.path.join('pkg1', 'test.py'), '', 'python')
        self.assertTrue(not result)

        with open(os.path.join(output_dir, 'pkg1', '__init__.py'), 'w') as f:
            f.write('from .test import *')

        result = await lsp_server._update_and_check(
            os.path.join('pkg1', '__init__.py'), 'from .test import *',
            'python')
        self.assertTrue(not result)


if __name__ == '__main__':
    unittest.main()
