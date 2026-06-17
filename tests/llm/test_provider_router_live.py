# Copyright (c) ModelScope Contributors. All rights reserved.
"""Live tests for the provider router (real API calls).

Routed through ``LLM.from_config`` with ``use_provider_router: true``. API keys
are injected via the environment (loaded from .env) and resolved by each
provider's spec env-chain -- they are never placed in the config or printed.
Each test skips when its credential is absent. Model ids are environment
specific; override via the ``<SERVICE>_TEST_MODEL`` env var if needed.

The Anthropic Messages transport is validated against DeepSeek's
anthropic-compatible endpoint, so no real Anthropic key is required.
"""
import os
import unittest

from ms_agent.llm import LLM
from ms_agent.llm.utils import Message, Tool
from omegaconf import OmegaConf

from modelscope.utils.test_utils import test_level

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
except Exception:
    pass

# Tool calls need room to complete; a too-small budget can truncate a tool
# call mid-arguments and force a fragile continuation on some providers.
MAX_TOKENS = 256

TOOLS = [
    Tool(
        tool_name='mkdir',
        description='Create a directory in the file system',
        parameters={
            'type': 'object',
            'properties': {
                'dir_name': {
                    'type': 'string',
                    'description': 'directory name'
                }
            },
            'required': ['dir_name']
        })
]

# service -> (default model, env key that must be present)
PROVIDERS = {
    'modelscope': ('Qwen/Qwen3-235B-A22B-Instruct-2507', 'MODELSCOPE_API_KEY'),
    'dashscope': ('qwen3.7-plus', 'DASHSCOPE_API_KEY'),
    'deepseek': ('deepseek-v4-flash', 'DEEPSEEK_API_KEY'),
    'zhipu': ('glm-4.6', 'GLM_API_KEY'),
    'kimi': ('moonshot-v1-8k', 'KIMI_API_KEY'),
    'minimax': ('MiniMax-M2', 'MINIMAX_API_KEY'),
    'openrouter': ('qwen/qwen3.7-plus', 'OpenRouter_API_KEY'),
}


def _msgs(text):
    return [
        Message(role='system', content='You are a helpful assistant.'),
        Message(role='user', content=text),
    ]


def _config(service, model, stream=False):
    # Credentials resolved from env by the provider spec; not placed here.
    return OmegaConf.create({
        'llm': {
            'use_provider_router': True,
            'service': service,
            'model': os.getenv(f'{service.upper()}_TEST_MODEL', model),
        },
        'generation_config': {
            'stream': stream,
            'max_tokens': MAX_TOKENS,
        }
    })


class TestProviderRouterLive(unittest.TestCase):

    def _run(self, service):
        model, env_key = PROVIDERS[service]
        if not os.getenv(env_key):
            self.skipTest(f'needs {env_key}')

        # text (non-stream)
        llm = LLM.from_config(_config(service, model))
        res = llm.generate(messages=_msgs('浙江的省会是哪里？只答城市名。'), tools=None)
        self.assertTrue(res.content, f'{service}: empty content')
        self.assertNotIn('<think>', res.content,
                         f'{service}: reasoning leaked into content')

        # stream
        llm = LLM.from_config(_config(service, model, stream=True))
        chunk = None
        for chunk in llm.generate(messages=_msgs('用一句话介绍杭州。'), tools=None):
            pass
        self.assertTrue(chunk and chunk.content, f'{service}: empty stream')

        # tool call
        llm = LLM.from_config(_config(service, model))
        res = llm.generate(messages=_msgs('请创建一个名为 demo 的目录。'), tools=TOOLS)
        self.assertTrue(res.tool_calls, f'{service}: no tool call')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_modelscope(self):
        self._run('modelscope')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_dashscope(self):
        self._run('dashscope')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_deepseek(self):
        self._run('deepseek')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_zhipu(self):
        self._run('zhipu')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_kimi(self):
        self._run('kimi')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_minimax(self):
        self._run('minimax')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_openrouter(self):
        self._run('openrouter')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_continue_gen_accumulates(self):
        if not os.getenv('DASHSCOPE_API_KEY'):
            self.skipTest('needs DASHSCOPE_API_KEY')
        cfg = _config('dashscope', 'qwen3.7-plus')
        cfg.generation_config.max_tokens = 40
        res = LLM.from_config(cfg).generate(
            messages=_msgs('写一段约200字介绍杭州的短文。'), tools=None)
        self.assertGreater(res.api_calls, 1)
        self.assertGreater(res.completion_tokens, 40)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_capabilities_queryable(self):
        if not os.getenv('DEEPSEEK_API_KEY'):
            self.skipTest('needs DEEPSEEK_API_KEY')
        from ms_agent.llm.types import ProviderCapability
        llm = LLM.from_config(_config('deepseek', 'deepseek-v4-flash'))
        self.assertTrue(
            llm.capabilities.supports(ProviderCapability.TOOL_CALL))


class TestAnthropicProtocolLive(unittest.TestCase):
    """Validate the Anthropic Messages transport via DeepSeek's anthropic
    endpoint (https://api.deepseek.com/anthropic)."""

    def _config(self, stream=False):
        return OmegaConf.create({
            'llm': {
                'use_provider_router': True,
                'service': 'anthropic',
                'model': 'deepseek-v4-flash',
                # route the DeepSeek key to the anthropic transport
                'anthropic_api_key': os.environ.get('DEEPSEEK_API_KEY'),
                'anthropic_base_url': 'https://api.deepseek.com/anthropic',
            },
            'generation_config': {
                'stream': stream,
                'max_tokens': MAX_TOKENS,
            }
        })

    @unittest.skipUnless(
        test_level() >= 0 and os.getenv('DEEPSEEK_API_KEY'),
        'needs DEEPSEEK_API_KEY')
    def test_text_no_stream(self):
        llm = LLM.from_config(self._config())
        res = llm.generate(messages=_msgs('浙江的省会是哪里？'), tools=None)
        self.assertTrue(res.content)

    @unittest.skipUnless(
        test_level() >= 0 and os.getenv('DEEPSEEK_API_KEY'),
        'needs DEEPSEEK_API_KEY')
    def test_text_stream(self):
        llm = LLM.from_config(self._config(stream=True))
        chunk = None
        for chunk in llm.generate(messages=_msgs('浙江的省会是哪里？'), tools=None):
            pass
        self.assertTrue(chunk and chunk.content)


if __name__ == '__main__':
    unittest.main()
