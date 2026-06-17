# Copyright (c) ModelScope Contributors. All rights reserved.
"""Unit tests for the data-driven provider layer (no network)."""
import os
import unittest
from unittest.mock import patch

from ms_agent.llm.adapter import ResponseAdapter
from ms_agent.llm.credentials import CredentialResolver
from ms_agent.llm.retry import ErrorCategory, classify_error, smart_retry
from ms_agent.llm.spec import ProviderSpec, get_registry
from ms_agent.llm.types import (LLMResponse, ProviderCapabilities,
                                ProviderCapability, TextBlock, ThinkingBlock,
                                ToolUseBlock, UsageInfo)
from ms_agent.llm.utils import Message, ToolCall
from omegaconf import OmegaConf

from modelscope.utils.test_utils import test_level

EXPECTED_PROVIDERS = {
    'openai', 'anthropic', 'google', 'modelscope', 'zhipu', 'deepseek',
    'dashscope', 'minimax', 'openrouter', 'kimi'
}


class FakeAPIError(Exception):

    def __init__(self, message, status_code=None, retry_after=None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class TestProviderRegistry(unittest.TestCase):

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_builtins_registered(self):
        names = {p.name for p in get_registry().list_providers()}
        self.assertTrue(EXPECTED_PROVIDERS.issubset(names))

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_get_is_case_insensitive(self):
        self.assertEqual('openai', get_registry().get('OpenAI').name)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_resolve_by_model(self):
        reg = get_registry()
        cases = {
            'claude-4-opus': 'anthropic',
            'gpt-4o-mini': 'openai',
            'o3-mini': 'openai',
            'deepseek-reasoner': 'deepseek',
            'glm-4-plus': 'zhipu',
            'gemini-1.5-pro': 'google',
            'Qwen3-235B-A22B': 'modelscope',
        }
        for model, provider in cases.items():
            spec = reg.resolve_by_model(model)
            self.assertIsNotNone(spec, f'{model} did not resolve')
            self.assertEqual(provider, spec.name, f'{model} -> {spec.name}')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_resolve_unknown_returns_none(self):
        self.assertIsNone(get_registry().resolve_by_model('some-random-model'))

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_aliases(self):
        reg = get_registry()
        self.assertEqual('zhipu', reg.get('glm').name)
        self.assertEqual('zhipu', reg.get('GLM').name)
        self.assertEqual('kimi', reg.get('moonshot').name)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_zhipu_uses_glm_env(self):
        spec = get_registry().get('zhipu')
        self.assertIn('GLM_API_KEY', spec.api_key_env)
        self.assertIn('GLM_BASE_URL', spec.base_url_env)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_continue_gen_modes(self):
        reg = get_registry()
        self.assertEqual('prefix', reg.get('deepseek').continue_gen_mode)
        self.assertEqual(['```'], reg.get('deepseek').continue_gen_stop)
        self.assertEqual('partial', reg.get('dashscope').continue_gen_mode)
        self.assertIsNone(reg.get('openai').continue_gen_mode)


class TestCredentialResolver(unittest.TestCase):

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_config_field_priority(self):
        spec = get_registry().get('openai')
        config = OmegaConf.create(
            {'llm': {
                'model': 'gpt-4o',
                'openai_api_key': 'from-config'
            }})
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'from-env'}):
            self.assertEqual('from-config',
                             CredentialResolver.resolve_api_key(spec, config))

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_env_chain_fallback(self):
        spec = get_registry().get('google')  # GOOGLE_API_KEY, GEMINI_API_KEY
        config = OmegaConf.create({'llm': {'model': 'gemini-1.5-pro'}})
        env = {'GEMINI_API_KEY': 'gem-key'}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop('GOOGLE_API_KEY', None)
            self.assertEqual('gem-key',
                             CredentialResolver.resolve_api_key(spec, config))

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_base_url_default_from_spec(self):
        spec = get_registry().get('deepseek')
        config = OmegaConf.create({'llm': {'model': 'deepseek-chat'}})
        self.assertEqual('https://api.deepseek.com/v1',
                         CredentialResolver.resolve_base_url(spec, config))

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_missing_key_returns_none(self):
        spec = ProviderSpec(
            name='nope', display_name='Nope', transport='openai_compat',
            api_key_env=['DEFINITELY_MISSING_ENV_VAR_XYZ'])
        config = OmegaConf.create({'llm': {'model': 'x'}})
        self.assertIsNone(CredentialResolver.resolve_api_key(spec, config))


class TestResponseAdapter(unittest.TestCase):

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_message_to_response(self):
        msg = Message(
            role='assistant',
            content='hello',
            reasoning_content='thinking...',
            tool_calls=[
                ToolCall(
                    id='c1', index=0, type='function', tool_name='mkdir',
                    arguments='{"dir_name": "a"}')
            ],
            prompt_tokens=10, completion_tokens=5, cached_tokens=3,
            reasoning_tokens=2)
        resp = ResponseAdapter.to_response(msg)
        self.assertEqual('hello', resp.text)
        self.assertEqual('thinking...', resp.thinking)
        self.assertEqual(1, len(resp.tool_calls))
        self.assertEqual('mkdir', resp.tool_calls[0].name)
        self.assertEqual({'dir_name': 'a'}, resp.tool_calls[0].arguments)
        self.assertEqual(10, resp.usage.prompt_tokens)
        self.assertEqual(3, resp.usage.cached_tokens)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_response_to_message_serializes_args(self):
        resp = LLMResponse(
            content_blocks=[
                ThinkingBlock(thinking='t'),
                TextBlock(text='answer'),
                ToolUseBlock(id='c1', name='mkdir',
                             arguments={'dir_name': 'a'}),
            ],
            usage=UsageInfo(prompt_tokens=7, completion_tokens=4))
        msg = ResponseAdapter.to_message(resp)
        self.assertEqual('answer', msg.content)
        self.assertEqual('t', msg.reasoning_content)
        self.assertEqual(1, len(msg.tool_calls))
        # arguments must be a JSON string for the legacy agent contract
        self.assertIsInstance(msg.tool_calls[0]['arguments'], str)
        self.assertEqual('mkdir', msg.tool_calls[0]['tool_name'])
        self.assertEqual(7, msg.prompt_tokens)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_round_trip_preserves_core_fields(self):
        msg = Message(
            role='assistant', content='hi', reasoning_content='r',
            tool_calls=[
                ToolCall(id='1', index=0, type='function', tool_name='f',
                         arguments='{"x": 1}')
            ])
        back = ResponseAdapter.to_message(ResponseAdapter.to_response(msg))
        self.assertEqual(msg.content, back.content)
        self.assertEqual(msg.reasoning_content, back.reasoning_content)
        self.assertEqual('f', back.tool_calls[0]['tool_name'])


class TestRetry(unittest.TestCase):

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_classify(self):
        self.assertEqual(ErrorCategory.TRANSIENT,
                         classify_error(FakeAPIError('x', status_code=429)))
        self.assertEqual(ErrorCategory.TRANSIENT,
                         classify_error(FakeAPIError('x', status_code=503)))
        self.assertEqual(ErrorCategory.TRANSIENT,
                         classify_error(FakeAPIError('connection timeout')))
        self.assertEqual(ErrorCategory.TRANSIENT,
                         classify_error(FakeAPIError('Overloaded')))
        self.assertEqual(ErrorCategory.AUTH,
                         classify_error(FakeAPIError('x', status_code=401)))
        self.assertEqual(
            ErrorCategory.QUOTA,
            classify_error(FakeAPIError('insufficient balance')))
        self.assertEqual(ErrorCategory.CLIENT,
                         classify_error(FakeAPIError('x', status_code=400)))

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_auth_not_retried(self):
        calls = {'n': 0}

        @smart_retry(max_attempts=3, base_delay=0.0)
        def fn():
            calls['n'] += 1
            raise FakeAPIError('unauthorized', status_code=401)

        with self.assertRaises(FakeAPIError):
            fn()
        self.assertEqual(1, calls['n'])

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_transient_retried_then_succeeds(self):
        calls = {'n': 0}

        @smart_retry(max_attempts=3, base_delay=0.0)
        def fn():
            calls['n'] += 1
            if calls['n'] < 2:
                raise FakeAPIError('rate limit', status_code=429)
            return 'ok'

        self.assertEqual('ok', fn())
        self.assertEqual(2, calls['n'])


class TestOpenAICompatHelpers(unittest.TestCase):

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_normalize_base_url_strips_endpoint(self):
        from ms_agent.llm.transport.openai_compat import OpenAICompatTransport
        n = OpenAICompatTransport._normalize_base_url
        self.assertEqual('https://openrouter.ai/api/v1',
                         n('https://openrouter.ai/api/v1/chat/completions'))
        self.assertEqual('https://openrouter.ai/api/v1',
                         n('https://openrouter.ai/api/v1/chat/completions/'))
        self.assertEqual('https://api.x.com/v1', n('https://api.x.com/v1'))

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_usage_total_prefers_real_over_none(self):
        from ms_agent.llm.transport.openai_compat import OpenAICompatTransport

        class U:
            def __init__(self, p, c):
                self.prompt_tokens = p
                self.completion_tokens = c

        total = OpenAICompatTransport._usage_total
        self.assertEqual(-1, total(None))
        self.assertEqual(0, total(U(0, 0)))
        self.assertEqual(28, total(U(8, 20)))
        # a real usage chunk should outrank a zeroed finish-chunk usage
        self.assertGreater(total(U(8, 20)), total(U(0, 0)))

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_split_think(self):
        from ms_agent.llm.transport.openai_compat import OpenAICompatTransport
        split = OpenAICompatTransport._split_think
        # closed block
        r, c = split('<think>reasoning here</think>\nThe answer')
        self.assertEqual('reasoning here', r)
        self.assertEqual('The answer', c)
        # not yet closed (mid-stream)
        r, c = split('<think>still thinking')
        self.assertEqual('still thinking', r)
        self.assertEqual('', c)
        # no think block
        r, c = split('just an answer')
        self.assertEqual('', r)
        self.assertEqual('just an answer', c)


class TestTypes(unittest.TestCase):

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_capabilities(self):
        caps = ProviderCapabilities.from_list(['tool_call', 'streaming'])
        self.assertTrue(caps.supports(ProviderCapability.TOOL_CALL))
        self.assertFalse(caps.supports(ProviderCapability.VISION))

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_usage_total(self):
        self.assertEqual(
            15, UsageInfo(prompt_tokens=10, completion_tokens=5).total_tokens)


if __name__ == '__main__':
    unittest.main()
