# Copyright (c) ModelScope Contributors. All rights reserved.
"""Tests for SirchmunkSearch knowledge search integration via LLMAgent.

These tests verify the sirchmunk-based knowledge search functionality
through the LLMAgent entry point, including verification that
search_result and searching_detail fields are properly populated.

To run these tests, you need to set the following environment variables:
    - TEST_LLM_API_KEY: Your LLM API key
    - TEST_LLM_BASE_URL: Your LLM API base URL (optional, default: OpenAI)
    - TEST_LLM_MODEL_NAME: Your LLM model name (optional)
    - TEST_EMBEDDING_MODEL_ID: Embedding model ID (optional)
    - TEST_EMBEDDING_MODEL_CACHE_DIR: Embedding model cache directory (optional)

Example:
    export TEST_LLM_API_KEY="your-api-key"
    export TEST_LLM_BASE_URL="https://api.openai.com/v1"
    export TEST_LLM_MODEL_NAME="gpt-4o"
    export TEST_EMBEDDING_MODEL_ID="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    export TEST_EMBEDDING_MODEL_CACHE_DIR="/tmp/embedding_cache"
    python -m pytest tests/knowledge_search/test_sirschmunk.py
"""
import asyncio
import os
import shutil
import unittest
from pathlib import Path

from ms_agent.knowledge_search import SirchmunkSearch
from ms_agent.agent import LLMAgent
from ms_agent.config import Config
from omegaconf import DictConfig

from modelscope.utils.test_utils import test_level


class SirchmunkLLMAgentIntegrationTest(unittest.TestCase):
    """Test cases for SirchmunkSearch integration with LLMAgent.

    These tests verify that when LLMAgent runs a query that triggers
    knowledge search, the Message objects have search_result and
    searching_detail fields properly populated.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        # Create test directory with sample files
        cls.test_dir = Path('./test_llm_agent_knowledge')
        cls.test_dir.mkdir(exist_ok=True)

        # Create sample documentation
        (cls.test_dir / 'README.md').write_text('''
# Test Project Documentation

## Overview
This is a test project for knowledge search integration.

## API Reference

### UserManager
The UserManager class handles user operations:
- create_user: Create a new user account
- delete_user: Delete an existing user
- update_user: Update user information
- get_user: Retrieve user details

### AuthService
The AuthService class handles authentication:
- login: Authenticate user credentials
- logout: End user session
- refresh_token: Refresh authentication token
- verify_token: Validate authentication token
''')

        (cls.test_dir / 'config.py').write_text('''
"""Configuration module."""

class Config:
    """Application configuration."""

    def __init__(self):
        self.database_url = "postgresql://localhost:5432/mydb"
        self.secret_key = "your-secret-key"
        self.debug_mode = False

    def load_from_env(self):
        """Load configuration from environment variables."""
        import os
        self.database_url = os.getenv("DATABASE_URL", self.database_url)
        self.secret_key = os.getenv("SECRET_KEY", self.secret_key)
        return self
''')

    @classmethod
    def tearDownClass(cls):
        """Clean up test fixtures."""
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir, ignore_errors=True)
        work_dir = Path('./.sirchmunk')
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

    def _get_agent_config(self):
        """Create agent configuration with knowledge search."""
        llm_api_key = os.getenv('TEST_LLM_API_KEY', 'test-api-key')
        llm_base_url = os.getenv('TEST_LLM_BASE_URL', 'https://api.openai.com/v1')
        llm_model_name = os.getenv('TEST_LLM_MODEL_NAME', 'gpt-4o-mini')
        # Read from TEST_* env vars (for test-specific config)
        # These can be set from .env file which uses TEST_* prefix
        embedding_model_id = os.getenv('TEST_EMBEDDING_MODEL_ID', '')
        embedding_model_cache_dir = os.getenv('TEST_EMBEDDING_MODEL_CACHE_DIR', '')

        config = DictConfig({
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
            'knowledge_search': {
                'name': 'SirchmunkSearch',
                'paths': [str(self.test_dir)],
                'work_path': './.sirchmunk',
                'llm_api_key': llm_api_key,
                'llm_base_url': llm_base_url,
                'llm_model_name': llm_model_name,
                'embedding_model': embedding_model_id,
                'embedding_model_cache_dir': embedding_model_cache_dir,
                'mode': 'FAST',
            }
        })
        return config

    @unittest.skipUnless(test_level() >= 1, 'skip test in current test level')
    def test_llm_agent_with_knowledge_search(self):
        """Test LLMAgent using knowledge search.

        This test verifies that:
        1. LLMAgent can be initialized with SirchmunkSearch configuration
        2. Running a query produces a valid response
        3. User message has searching_detail and search_result populated
        4. searching_detail contains expected keys (logs, mode, paths)
        5. search_result is a list
        """
        config = self._get_agent_config()
        agent = LLMAgent(config=config, tag='test-knowledge-agent')

        # Test query that should trigger knowledge search
        query = 'How do I use UserManager to create a user?'

        async def run_agent():
            result = await agent.run(query)
            return result

        result = asyncio.run(run_agent())

        # Verify result
        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)

        # Check that assistant message exists
        assistant_message = [m for m in result if m.role == 'assistant']
        self.assertTrue(len(assistant_message) > 0)

        # Check that user message has search_result and searching_detail populated
        user_messages = [m for m in result if m.role == 'user']
        self.assertTrue(len(user_messages) > 0, "Expected at least one user message")

        # The first user message should have search details after do_rag processing
        user_msg = user_messages[0]
        self.assertTrue(
            hasattr(user_msg, 'searching_detail'),
            "User message should have searching_detail attribute"
        )
        self.assertTrue(
            hasattr(user_msg, 'search_result'),
            "User message should have search_result attribute"
        )

        # Check that searching_detail is a dict with expected keys
        self.assertIsInstance(
            user_msg.searching_detail, dict,
            "searching_detail should be a dictionary"
        )
        self.assertIn('logs', user_msg.searching_detail)
        self.assertIn('mode', user_msg.searching_detail)
        self.assertIn('paths', user_msg.searching_detail)

        # Check that search_result is a list (may be empty if no relevant docs found)
        self.assertIsInstance(
            user_msg.search_result, list,
            "search_result should be a list"
        )


if __name__ == '__main__':
    unittest.main()
