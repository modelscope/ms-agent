# Copyright (c) ModelScope Contributors. All rights reserved.
"""Replay Chat Completions streams through the SDK and public LLM entry point."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from omegaconf import OmegaConf

from ms_agent.llm import LLM
from ms_agent.llm.utils import Message, Tool


def tool_delta(index, arguments=None, call_id=None, name=None):
    delta = {'index': index, 'function': {'arguments': arguments}}
    if call_id is not None:
        delta.update(id=call_id, type='function')
    if name is not None:
        delta['function']['name'] = name
    return delta


def event(delta, finish_reason=None):
    return {
        'id': 'stream-test', 'object': 'chat.completion.chunk',
        'created': 0, 'model': 'test-model',
        'choices': [{'index': 0, 'delta': delta,
                     'finish_reason': finish_reason}],
    }


class StreamToolCallCases:
    use_router = False

    def setUp(self):
        self.requests = []
        self.events = []
        self.json_response = None
        case = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                case.requests.append((self.path, json.loads(body)))
                self.send_response(200)
                if case.json_response is not None:
                    payload = json.dumps(case.json_response).encode()
                    self.send_header('Content-Type', 'application/json')
                else:
                    payload = ''.join('data: ' + json.dumps(item) + '\n\n'
                                      for item in case.events).encode()
                    payload += b'data: [DONE]\n\n'
                    self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={'poll_interval': 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self._close_server)
        proxy = patch.dict('os.environ', {'NO_PROXY': '127.0.0.1'})
        proxy.start()
        self.addCleanup(proxy.stop)
        config = OmegaConf.create({
            'llm': {
                'service': 'openai', 'model': 'test-model',
                'use_provider_router': self.use_router,
                'openai_api_key': 'local-test-key',
                'openai_base_url':
                    f'http://127.0.0.1:{self.server.server_port}/v1',
            },
            'generation_config': {},
        })
        self.llm = LLM.from_config(config)
        self.engine = self.llm.transport if self.use_router else self.llm
        self.addCleanup(self.engine.client.close)
        self.tools = [Tool(
            tool_name='weather', description='Get weather for a city',
            parameters={'type': 'object',
                        'properties': {'city': {'type': 'string'}},
                        'required': ['city']})]

    def _close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())

    def stream(self, deltas):
        self.events = [event(delta) for delta in deltas]
        finish_reason = 'tool_calls' if any(
            delta.get('tool_calls') for delta in deltas) else 'stop'
        self.events.append(event({}, finish_reason))
        self.events.append({
            'id': 'stream-test', 'object': 'chat.completion.chunk',
            'created': 0, 'model': 'test-model', 'choices': [],
            'usage': {'prompt_tokens': 7, 'completion_tokens': 5,
                      'total_tokens': 12},
        })
        messages = list(self.llm.generate(
            [Message(role='user', content='Check the weather')],
            tools=self.tools, stream=True))
        self.assertEqual(len(self.requests), 1)
        path, request = self.requests[0]
        self.assertEqual(path, '/v1/chat/completions')
        self.assertTrue(request['stream'])
        self.assertEqual(request['tools'][0]['function']['name'], 'weather')
        self.assertEqual(messages[-1].prompt_tokens, 7)
        self.assertEqual(messages[-1].completion_tokens, 5)
        return messages

    def assert_calls(self, message, cities):
        self.assertEqual(len(message.tool_calls), len(cities))
        for index, (call, city) in enumerate(zip(message.tool_calls, cities)):
            self.assertEqual(call['index'], index)
            self.assertEqual(call['id'], f'call-{index}')
            self.assertEqual(call['type'], 'function')
            self.assertEqual(call['tool_name'], 'weather')
            self.assertEqual(json.loads(call['arguments']), {'city': city})

    def test_multiple_calls_in_one_later_chunk(self):
        messages = self.stream([
            {'tool_calls': [tool_delta(0, '{', 'call-0', 'weather')]},
            {'tool_calls': [tool_delta(0, '"city":"Paris"}'),
                            tool_delta(1, '{"city":"Tokyo"}',
                                       'call-1', 'weather')]},
        ])
        self.assert_calls(messages[-1], ['Paris', 'Tokyo'])
        self.assertEqual(messages[0].tool_calls[0]['arguments'], '{')

    def test_interleaved_calls(self):
        messages = self.stream([
            {'tool_calls': [tool_delta(0, '{', 'call-0', 'weather')]},
            {'tool_calls': [tool_delta(1, '{', 'call-1', 'weather')]},
            {'tool_calls': [tool_delta(0, '"city":"Paris"}')]},
            {'tool_calls': [tool_delta(1, '"city":"Tokyo"}')]},
        ])
        self.assert_calls(messages[-1], ['Paris', 'Tokyo'])

    def test_multiple_calls_in_first_and_following_chunks(self):
        messages = self.stream([
            {'tool_calls': [tool_delta(0, '{', 'call-0', 'weather'),
                            tool_delta(1, '{', 'call-1', 'weather')]},
            {'tool_calls': [tool_delta(1, '"city":"Tokyo"}'),
                            tool_delta(0, '"city":"Paris"}')]},
        ])
        self.assert_calls(messages[-1], ['Paris', 'Tokyo'])

    def test_sequential_calls_still_work(self):
        messages = self.stream([
            {'tool_calls': [tool_delta(0, '{', 'call-0', 'weather')]},
            {'tool_calls': [tool_delta(0, '"city":"Paris"}')]},
            {'tool_calls': [tool_delta(1, '{', 'call-1', 'weather')]},
            {'tool_calls': [tool_delta(1, '"city":"Tokyo"}')]},
        ])
        self.assert_calls(messages[-1], ['Paris', 'Tokyo'])

    def test_repeated_index_in_first_chunk(self):
        messages = self.stream([
            {'tool_calls': [tool_delta(0, '{', 'call-0', 'weather'),
                            tool_delta(0, '"city":"Paris"}')]},
        ])
        self.assert_calls(messages[-1], ['Paris'])

    def test_none_arguments_then_single_call(self):
        messages = self.stream([
            {'tool_calls': [tool_delta(0, None, 'call-0', 'weather')]},
            {'tool_calls': [tool_delta(0, '{"city":"Paris"}')]},
        ])
        self.assert_calls(messages[-1], ['Paris'])

    def test_metadata_arriving_after_arguments(self):
        messages = self.stream([
            {'tool_calls': [tool_delta(0, '{"city":"Paris"}',
                                       'call-0', 'weather')]},
            {'tool_calls': [tool_delta(1, '{')]},
            {'tool_calls': [tool_delta(1, '"city":"Tokyo"}',
                                       'call-1', 'weather')]},
        ])
        self.assert_calls(messages[-1], ['Paris', 'Tokyo'])
        self.assertEqual(
            messages[-1].to_dict_clean()['tool_calls'][1]['type'], 'function')

    def test_text_before_multiple_calls(self):
        messages = self.stream([
            {'content': 'Checking ', 'reasoning_content': 'Need '},
            {'content': 'weather.', 'reasoning_content': 'two cities.'},
            {'tool_calls': [tool_delta(0, '{"city":"Paris"}',
                                       'call-0', 'weather'),
                            tool_delta(1, '{"city":"Tokyo"}',
                                       'call-1', 'weather')]},
        ])
        self.assert_calls(messages[-1], ['Paris', 'Tokyo'])
        self.assertEqual(messages[-1].content, 'Checking weather.')
        self.assertEqual(messages[-1].reasoning_content, 'Need two cities.')

    def test_text_only_stream(self):
        messages = self.stream([{'content': 'Hello '}, {'content': 'world'}])
        self.assertEqual(messages[-1].content, 'Hello world')
        self.assertFalse(messages[-1].tool_calls)

    def test_non_streaming_calls_still_work(self):
        calls = [tool_delta(index, json.dumps({'city': city}),
                            f'call-{index}', 'weather')
                 for index, city in enumerate(['Paris', 'Tokyo'])]
        for call in calls:
            call.pop('index')
        self.json_response = {
            'id': 'non-stream-test', 'object': 'chat.completion',
            'created': 0, 'model': 'test-model',
            'choices': [{'index': 0, 'finish_reason': 'tool_calls',
                         'message': {'role': 'assistant', 'content': None,
                                     'tool_calls': calls}}],
            'usage': {'prompt_tokens': 7, 'completion_tokens': 5,
                      'total_tokens': 12},
        }
        result = self.llm.generate(
            [Message(role='user', content='Check the weather')],
            tools=self.tools, stream=False)
        self.assert_calls(result, ['Paris', 'Tokyo'])


class TestLegacyStreamToolCalls(StreamToolCallCases, unittest.TestCase):
    pass


class TestRouterStreamToolCalls(StreamToolCallCases, unittest.TestCase):
    use_router = True


if __name__ == '__main__':
    unittest.main()
