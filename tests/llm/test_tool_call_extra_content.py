"""Gemini 3 returns a thought signature on each tool call as
``extra_content.google.thought_signature`` and answers 400 when the next
request replays the call without it, so the field must survive parsing, stream
merging and serialization in both OpenAI-compatible clients."""
import unittest

from openai.types.chat import ChatCompletion, ChatCompletionChunk
from omegaconf import OmegaConf

from ms_agent.llm.openai_llm import OpenAI
from ms_agent.llm.transport.openai_compat import OpenAICompatTransport
from ms_agent.llm.utils import Message

EXTRA_CONTENT = {'google': {'thought_signature': 'sig=='}}


def _completion(extra=EXTRA_CONTENT):
    tool_call = {
        'id': 'call_1',
        'type': 'function',
        'function': {
            'name': 'read_file',
            'arguments': '{"path": "a.txt"}',
        },
    }
    if extra:
        tool_call['extra_content'] = extra
    return ChatCompletion.model_validate({
        'id': 'c1',
        'object': 'chat.completion',
        'created': 0,
        'model': 'm',
        'usage': {
            'prompt_tokens': 1,
            'completion_tokens': 1,
            'total_tokens': 2,
        },
        'choices': [{
            'index': 0,
            'finish_reason': 'tool_calls',
            'message': {
                'role': 'assistant',
                'content': None,
                'tool_calls': [tool_call],
            },
        }],
    })


def _chunk(index, call_id=None, name=None, arguments='', extra=None):
    tool_call = {
        'index': index,
        'id': call_id,
        'type': 'function' if call_id else None,
        'function': {
            'name': name,
            'arguments': arguments,
        },
    }
    if extra:
        tool_call['extra_content'] = extra
    return ChatCompletionChunk.model_validate({
        'id': 'c1',
        'object': 'chat.completion.chunk',
        'created': 0,
        'model': 'm',
        'choices': [{
            'index': 0,
            'delta': {
                'tool_calls': [tool_call],
            },
        }],
    })


def _merge_stream(client, chunks):
    merged = None
    for chunk in chunks:
        merged = client._merge_stream_message(
            client, merged, client._stream_format_output_message(chunk))
    return merged


class TestToolCallExtraContent(unittest.TestCase):
    clients = (OpenAICompatTransport, OpenAI)

    def test_non_stream_round_trip(self):
        for client in self.clients:
            message = client._format_output_message(_completion())
            wire = message.to_dict_clean()['tool_calls'][0]
            self.assertEqual(wire['extra_content'], EXTRA_CONTENT)

    def test_stream_signature_on_any_chunk_of_any_call(self):
        """The signature may arrive on the opening chunk or a later one, and
        a parallel call must keep its own."""
        other = {'google': {'thought_signature': 'other=='}}
        chunks = [
            _chunk(0, 'call_1', 'read_file', '{"path"', EXTRA_CONTENT),
            _chunk(0, arguments=': "a.txt"}'),
            _chunk(1, 'call_2', 'read_file', '{"path"'),
            _chunk(1, arguments=': "b.txt"}', extra=other),
        ]
        for client in self.clients:
            wire = _merge_stream(client, chunks).to_dict_clean()['tool_calls']
            self.assertEqual(wire[0]['extra_content'], EXTRA_CONTENT)
            self.assertEqual(wire[0]['function']['arguments'],
                             '{"path": "a.txt"}')
            self.assertEqual(wire[1]['extra_content'], other)

    def test_other_providers_send_no_extra_field(self):
        """Strict endpoints can reject unknown tool-call fields."""
        for client in self.clients:
            message = client._format_output_message(_completion(extra=None))
            wire = message.to_dict_clean()['tool_calls'][0]
            self.assertNotIn('extra_content', wire)

    def test_next_request_replays_signature(self):
        conf = OmegaConf.create({
            'llm': {
                'model': 'm',
                'openai_base_url': 'http://x',
                'openai_api_key': 'dummy',
            },
            'generation_config': {},
        })
        assistant = OpenAI._format_output_message(_completion())
        tool = Message(role='tool', content='ok', tool_call_id='call_1')
        request = OpenAI(conf)._format_input_message([
            Message(role='user', content='read a.txt'), assistant, tool
        ])
        sent = [m for m in request if m['role'] == 'assistant'][0]
        self.assertEqual(sent['tool_calls'][0]['extra_content'], EXTRA_CONTENT)


if __name__ == '__main__':
    unittest.main()
