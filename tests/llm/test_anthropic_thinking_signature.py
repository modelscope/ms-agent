# Copyright (c) ModelScope Contributors. All rights reserved.
"""Offline regression: a signed thinking block on a NON-streaming Anthropic
reply must survive ``_format_output_message`` so a tool follow-up can replay it.

No client, credential or provider call is involved — completions are synthetic
``SimpleNamespace`` objects and the transport instance skips its constructor.
"""
from types import SimpleNamespace as NS

from ms_agent.llm import multimodal
from ms_agent.llm.transport.anthropic_messages import AnthropicMessagesTransport
from ms_agent.llm.utils import Message

THINKING = 'I should look this up before answering.'
SIGNATURE = 'opaque-signature-abc123'
TOOL_ID = 'toolu-1'


def _completion():
    """A tool-use completion carrying a signed extended-thinking block."""
    return NS(
        id='msg-1',
        model='test-model',
        usage=None,
        stop_reason='tool_use',
        content=[
            NS(type='thinking', thinking=THINKING, signature=SIGNATURE),
            NS(type='tool_use', id=TOOL_ID, name='lookup', input={'q': 'weather'}),
        ])


def _transport():
    transport = AnthropicMessagesTransport.__new__(AnthropicMessagesTransport)
    transport.model = 'test-model'
    transport.provider_id = ''
    transport._vision = multimodal.VisionOptions()
    transport._vision_supported = False
    transport._last_deliveries = []
    transport._active_stream = None
    return transport


def test_nonstream_thinking_signature_is_captured():
    message = AnthropicMessagesTransport._format_output_message(_completion())

    assert message.reasoning_content == THINKING
    assert message.reasoning_signature == SIGNATURE
    assert message.tool_calls and message.tool_calls[0]['id'] == TOOL_ID
    assert message.finish_reason == 'tool_use'


def test_nonstream_thinking_signature_is_replayed_on_tool_followup():
    transport = _transport()
    assistant = AnthropicMessagesTransport._format_output_message(_completion())
    tool_result = Message(role='tool', content='sunny', tool_call_id=TOOL_ID)

    wire = transport._format_input_message([assistant, tool_result])

    assert wire[0]['role'] == 'assistant'
    thinking = wire[0]['content'][0]
    assert thinking['type'] == 'thinking'
    assert thinking['thinking'] == THINKING
    # The provider rejects a tool follow-up whose preceding thinking block
    # dropped its opaque signature; replay must carry it verbatim.
    assert thinking['signature'] == SIGNATURE
    assert wire[1]['role'] == 'user'
    assert wire[1]['content'][0]['type'] == 'tool_result'
