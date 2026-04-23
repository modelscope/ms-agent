# Copyright (c) ModelScope Contributors. All rights reserved.
"""Tests for SirchmunkSearch and localsearch tool integration.

Example (full sirchmunk run):
    export TEST_LLM_API_KEY="your-api-key"
    python -m pytest tests/knowledge_search/test_sirschmunk.py
"""
import asyncio
import os
import shutil
import unittest
from pathlib import Path


def _sirchmunk_dir_scanner_available() -> bool:
    try:
        import sirchmunk.scan.dir_scanner  # noqa: F401
        return True
    except ImportError:
        return False

from ms_agent.agent import LLMAgent
from ms_agent.tools.search.sirchmunk_search import SirchmunkSearch
from ms_agent.llm.utils import Message
from ms_agent.tools.tool_manager import ToolManager
from omegaconf import DictConfig

class SirchmunkKnowledgeSearchTest(unittest.TestCase):
    """Sirchmunk config, ToolManager registration"""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path('./test_llm_agent_knowledge')
        cls.test_dir.mkdir(exist_ok=True)
        (cls.test_dir / 'README.md').write_text(
            '# Demo\n\nUserManager.create_user creates a user.\n')

    @classmethod
    def tearDownClass(cls):
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir, ignore_errors=True)
        work_dir = Path('./.sirchmunk')
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

    def _base_config(self) -> DictConfig:
        llm_api_key = os.getenv('TEST_LLM_API_KEY', 'test-api-key')
        llm_base_url = os.getenv('TEST_LLM_BASE_URL',
                                 'https://api.openai.com/v1')
        llm_model_name = os.getenv('TEST_LLM_MODEL_NAME', 'gpt-4o-mini')
        embedding_model_id = os.getenv('TEST_EMBEDDING_MODEL_ID', '')
        embedding_model_cache_dir = os.getenv('TEST_EMBEDDING_MODEL_CACHE_DIR',
                                                '')
        return DictConfig({
            'output_dir':
            './outputs_knowledge_test',
            'llm': {
                'service': 'openai',
                'model': llm_model_name,
                'openai_api_key': llm_api_key,
                'openai_base_url': llm_base_url,
            },
            'generation_config': {
                'temperature': 0.3,
                'max_tokens': 500,
            },
            'tools': {
                'localsearch': {
                    'paths': [str(self.test_dir)],
                    'work_path': './.sirchmunk',
                    'llm_api_key': llm_api_key,
                    'llm_base_url': llm_base_url,
                    'llm_model_name': llm_model_name,
                    'embedding_model': embedding_model_id,
                    'embedding_model_cache_dir': embedding_model_cache_dir,
                    'mode': 'FAST',
                },
            },
        })

    def test_does_not_inject_knowledge_search(self):
        """Local sirchmunk search is no longer merged into the user message here."""
        config = self._base_config()
        agent = LLMAgent(config=config, tag='test-knowledge-agent')
        original = 'How do I use UserManager?'

        async def run():
            messages = [
                Message(role='system', content='You are a helper.'),
                Message(role='user', content=original),
            ]
            messages = await agent.run(messages)
            return messages

        messages = asyncio.run(run())
        print(f'messages: {messages}')

    def test_tool_manager_registers_localsearch(self):
        """When tools.localsearch.paths is set, ToolManager exposes localsearch."""

        async def run():
            config = self._base_config()
            tm = ToolManager(config, trust_remote_code=False)
            await tm.connect()
            tools = await tm.get_tools()
            await tm.cleanup()
            return tools

        tools = asyncio.run(run())
        names = [t['tool_name'] for t in tools]
        self.assertTrue(
            any(n.endswith('localsearch') for n in names),
            f'Expected localsearch in tools, got: {names}',
        )

    @unittest.skipUnless(
        _sirchmunk_dir_scanner_available(),
        'sirchmunk scan not installed',
    )
    def test_localsearch_description_catalog_injects_file_preview(self):
        """Optional: shallow DirectoryScanner summaries appear in tool description."""

        async def run():
            config = self._base_config()
            config.tools.localsearch['description_catalog'] = True
            config.tools.localsearch['description_catalog_cache_ttl_seconds'] = 0
            tm = ToolManager(config, trust_remote_code=False)
            await tm.connect()
            tools = await tm.get_tools()
            await tm.cleanup()
            return tools

        tools = asyncio.run(run())
        loc = next(t for t in tools if t['tool_name'].endswith('localsearch'))
        desc = loc.get('description') or ''
        self.assertIn('Local knowledge catalog', desc)
        self.assertIn('UserManager', desc)

    @unittest.skipUnless(
        os.getenv('TEST_SIRCHMUNK_SMOKE', ''),
        'Set TEST_SIRCHMUNK_SMOKE=1 to run sirchmunk API smoke test',
    )
    def test_sirchmunk_search_query_smoke(self):
        """Optional: run sirchmunk once (needs network / valid API keys)."""
        config = self._base_config()
        searcher = SirchmunkSearch(config)
        result = asyncio.run(searcher.query('UserManager'))
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


if __name__ == '__main__':
    unittest.main()
