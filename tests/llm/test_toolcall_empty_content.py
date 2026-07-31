"""P1: a tool-call-only assistant turn carries NO 'Let me do a tool calling.'
placeholder anymore — it stays empty and each provider serializes it to the
canonical empty representation (OpenAI family: content null; Anthropic:
tool_use block with no text block). Covers all supported providers."""
import unittest

from omegaconf import OmegaConf

from ms_agent.llm.anthropic_llm import Anthropic
from ms_agent.llm.dashscope_llm import DashScope
from ms_agent.llm.deepseek_llm import DeepSeek
from ms_agent.llm.modelscope_llm import ModelScope
from ms_agent.llm.openai_llm import OpenAI
from ms_agent.llm.utils import Message

PLACEHOLDER = 'Let me do a tool calling.'


def _assistant_toolcall_empty():
    return [
        Message(role='user', content='hi'),
        Message(role='assistant', content='', tool_calls=[
            {'id': 'c1', 'type': 'function', 'tool_name': 't',
                         'arguments': '{}', 'index': 0},
        ]),
    ]


class TestOpenAIFamilyEmptyToolCall(unittest.TestCase):
    def _openai(self):
        conf = OmegaConf.create({
            'llm': {'model': 'm', 'openai_base_url': 'http://x',
                    'openai_api_key': 'dummy'},
            'generation_config': {},
        })
        return OpenAI(conf)

    def test_empty_content_serializes_as_null_no_placeholder(self):
        out = self._openai()._format_input_message(_assistant_toolcall_empty())
        asst = [m for m in out if m.get('role') == 'assistant'][-1]
        # canonical `content: null` (not an empty string), tool_calls preserved.
        self.assertIsNone(asst['content'])
        self.assertTrue(asst.get('tool_calls'))
        self.assertNotIn(PLACEHOLDER, str(out))  # no leaked placeholder

    def test_derived_providers_inherit_formatter(self):
        # DeepSeek / DashScope / ModelScope reuse OpenAI's _format_input_message
        # unchanged, so the fix applies to them too.
        for cls in (DeepSeek, DashScope, ModelScope):
            self.assertIs(cls._format_input_message,
                          OpenAI._format_input_message)

    def test_nonempty_content_with_tool_calls_kept(self):
        # A real narration before a tool call must survive untouched.
        msgs = [
            Message(role='user', content='hi'),
            Message(role='assistant', content='让我查一下',
                    tool_calls=[{'id': 'c1', 'type': 'function',
                                 'tool_name': 't', 'arguments': '{}',
                                 'index': 0}]),
        ]
        out = self._openai()._format_input_message(msgs)
        asst = [m for m in out if m.get('role') == 'assistant'][-1]
        self.assertEqual(asst['content'], '让我查一下')


class TestAnthropicEmptyToolCall(unittest.TestCase):
    def _anthropic(self):
        conf = OmegaConf.create({
            'llm': {'model': 'm', 'anthropic_base_url': 'http://x',
                    'anthropic_api_key': 'dummy'},
            'generation_config': {},
        })
        return Anthropic(conf)

    def test_toolcall_only_has_tool_use_no_text_no_placeholder(self):
        out = self._anthropic()._format_input_message(
            _assistant_toolcall_empty())
        asst = [m for m in out if m.get('role') == 'assistant'][-1]
        block_types = [b.get('type') for b in asst['content']]
        self.assertIn('tool_use', block_types)   # the call is carried
        self.assertNotIn('text', block_types)    # no empty text / placeholder
        self.assertNotIn(PLACEHOLDER, str(out))


class TestRouterTransportsEmptyToolCall(unittest.TestCase):
    """The NEW data-driven provider layer (router transports — what the webui
    actually runs with use_provider_router=true) must serialize an empty
    tool-call turn the same canonical way as the legacy adapters."""

    def test_openai_compat_transport_content_null(self):
        from ms_agent.llm.transport.openai_compat import OpenAICompatTransport
        t = OpenAICompatTransport(model='m', api_key='dummy',
                                  base_url='http://x')
        out = t._format_input_message(_assistant_toolcall_empty())
        asst = [m for m in out if m.get('role') == 'assistant'][-1]
        self.assertIsNone(asst['content'])       # canonical null, not ''
        self.assertTrue(asst.get('tool_calls'))
        self.assertNotIn(PLACEHOLDER, str(out))

    def test_openai_compat_transport_keeps_real_narration(self):
        from ms_agent.llm.transport.openai_compat import OpenAICompatTransport
        t = OpenAICompatTransport(model='m', api_key='dummy',
                                  base_url='http://x')
        msgs = [
            Message(role='user', content='hi'),
            Message(role='assistant', content='让我查一下',
                    tool_calls=[{'id': 'c1', 'type': 'function',
                                 'tool_name': 't', 'arguments': '{}',
                                 'index': 0}]),
        ]
        out = t._format_input_message(msgs)
        asst = [m for m in out if m.get('role') == 'assistant'][-1]
        self.assertEqual(asst['content'], '让我查一下')

    def test_anthropic_messages_transport_tool_use_no_text(self):
        from ms_agent.llm.transport.anthropic_messages import \
            AnthropicMessagesTransport
        t = AnthropicMessagesTransport(model='m', api_key='dummy',
                                       base_url='http://x')
        out = t._format_input_message(_assistant_toolcall_empty())
        asst = [m for m in out if m.get('role') == 'assistant'][-1]
        block_types = [b.get('type') for b in asst['content']]
        self.assertIn('tool_use', block_types)
        self.assertNotIn('text', block_types)
        self.assertNotIn(PLACEHOLDER, str(out))


if __name__ == '__main__':
    unittest.main()
