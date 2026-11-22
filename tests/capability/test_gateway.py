# Copyright (c) ModelScope Contributors. All rights reserved.
"""Capability Gateway tests — registry, --check, MCP list_tools, real tools.

Heavy / long-running project capabilities are not exercised end-to-end here.
Keyed engines (exa/tavily) are skipped when the corresponding env var is absent.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

from ms_agent.capabilities import create_registry
from ms_agent.capabilities.mcp_server import _is_exposed_over_mcp


EXPECTED_MCP_TOOLS = {
    'replace_file_contents',
    'replace_file_lines',
    'lsp_check_directory',
    'lsp_update_and_check',
    'submit_research_task',
    'check_research_progress',
    'get_research_report',
    'deep_research',
    'web_search',
    'delegate_task',
    'submit_agent_task',
    'check_agent_task',
    'get_agent_result',
    'cancel_agent_task',
    'submit_code_genesis_task',
    'check_code_genesis_progress',
    'get_code_genesis_result',
    'code_genesis',
    'submit_fin_research_task',
    'check_fin_research_progress',
    'get_fin_research_report',
    'fin_research',
    'submit_video_generation_task',
    'check_video_generation_progress',
    'get_video_generation_result',
    'video_generation',
    'submit_doc_research_task',
    'check_doc_research_progress',
    'get_doc_research_report',
    'doc_research',
}


class TestCapabilityRegistry(unittest.TestCase):

    def test_create_registry_counts(self):
        registry = create_registry()
        caps = registry.list_all()
        exposed = [c for c in caps if _is_exposed_over_mcp(c)]
        self.assertEqual(len(caps), 31)
        self.assertEqual(len(exposed), 30)
        self.assertEqual({c.name for c in exposed}, EXPECTED_MCP_TOOLS)
        # Parent component is registered but not MCP-exposed.
        parent = registry.get('lsp_code_server')
        self.assertIsNotNone(parent)
        self.assertFalse(_is_exposed_over_mcp(parent))

    def test_lsp_parent_returns_info_not_keyerror(self):
        registry = create_registry()

        async def _run():
            return await registry.invoke('lsp_code_server', {})

        result = asyncio.run(_run())
        self.assertNotIn('error', result)
        self.assertEqual(result.get('component'), 'lsp_code_server')
        self.assertIn('lsp_check_directory', result.get('sub_capabilities', []))

    def test_lsp_missing_backend_actionable_error(self):
        """When pyright-langserver is absent, return an installable hint."""
        import shutil
        if shutil.which('pyright-langserver'):
            self.skipTest('pyright-langserver is installed on this machine')

        registry = create_registry()

        async def _run():
            return await registry.invoke(
                'lsp_check_directory',
                {'directory': '/tmp', 'language': 'python'},
            )

        result = asyncio.run(_run())
        self.assertIn('error', result)
        self.assertIn('pyright', result['error'].lower())
        self.assertIn('install', result['error'].lower())


class TestMcpServerCheck(unittest.TestCase):

    def test_check_json_distinguishes_counts(self):
        proc = subprocess.run(
            [sys.executable, '-m', 'ms_agent.capabilities.mcp_server', '--check'],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(Path(__file__).resolve().parents[2]),
            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[2])},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['registered_total'], 31)
        self.assertEqual(data['mcp_exposed_total'], 30)
        exposed_names = {
            c['name']
            for c in data['capabilities'] if c.get('mcp_exposed')
        }
        self.assertEqual(exposed_names, EXPECTED_MCP_TOOLS)


class TestFilesystemCapability(unittest.TestCase):

    def test_replace_file_contents_and_lines(self):
        registry = create_registry()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'demo.txt'
            path.write_text('alpha\nbeta\n', encoding='utf-8')

            async def _run():
                r1 = await registry.invoke(
                    'replace_file_contents',
                    {
                        'path': 'demo.txt',
                        'source': 'alpha',
                        'target': 'ALPHA',
                    },
                    workspace=tmp,
                )
                r2 = await registry.invoke(
                    'replace_file_lines',
                    {
                        'path': 'demo.txt',
                        'content': '# header',
                        'start_line': 0,
                    },
                    workspace=tmp,
                )
                return r1, r2

            r1, r2 = asyncio.run(_run())
            self.assertIn('result', r1)
            self.assertIn('result', r2)
            text = path.read_text(encoding='utf-8')
            self.assertTrue(text.startswith('# header'))
            self.assertIn('ALPHA', text)


class TestWebSearchCapability(unittest.TestCase):

    @unittest.skipUnless(
        os.environ.get('MS_AGENT_RUN_NETWORK_TESTS') == '1',
        'Set MS_AGENT_RUN_NETWORK_TESTS=1 to exercise the live arXiv API')
    def test_arxiv_search_real(self):
        registry = create_registry()

        async def _run():
            return await registry.invoke(
                'web_search',
                {
                    'query': 'graph neural network',
                    'num_results': 1,
                    'engine_type': 'arxiv',
                },
            )

        result = asyncio.run(_run())
        self.assertEqual(result.get('status'), 'ok', result)
        self.assertEqual(result.get('engine'), 'arxiv')
        self.assertGreaterEqual(result.get('count', 0), 1)

    def test_tavily_missing_key_actionable(self):
        if os.environ.get('TAVILY_API_KEY'):
            self.skipTest('TAVILY_API_KEY is set')
        registry = create_registry()

        async def _run():
            return await registry.invoke(
                'web_search',
                {'query': 'test', 'engine_type': 'tavily', 'num_results': 1},
            )

        result = asyncio.run(_run())
        self.assertIn('error', result)
        self.assertIn('TAVILY_API_KEY', result['error'])


@pytest.mark.asyncio
async def test_mcp_list_tools_count():
    pytest.importorskip('mcp')
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    repo = str(Path(__file__).resolve().parents[2])
    params = StdioServerParameters(
        command=sys.executable,
        args=['-m', 'ms_agent.capabilities.mcp_server'],
        env={**os.environ, 'PYTHONPATH': repo},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert len(names) == 30
            assert names == EXPECTED_MCP_TOOLS


if __name__ == '__main__':
    unittest.main()
