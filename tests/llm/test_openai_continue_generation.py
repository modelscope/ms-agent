# Copyright (c) ModelScope Contributors. All rights reserved.
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from omegaconf import OmegaConf

from ms_agent.llm.openai_llm import OpenAI
from ms_agent.llm.utils import Message, ToolCall


def _make_completion(
    content: str = '',
    finish_reason: str = 'stop',
    tool_calls: list[dict] | None = None,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
):
    """Build a minimal OpenAI chat completion object for tests."""
    message = SimpleNamespace(
        content=content,
        reasoning_content='',
        tool_calls=[
            SimpleNamespace(
                id=tc['id'],
                type='function',
                function=SimpleNamespace(
                    name=tc['tool_name'],
                    arguments=tc['arguments'],
                ),
                index=tc.get('index', idx),
            ) for idx, tc in enumerate(tool_calls or [])
        ] or None,
    )
    choice = SimpleNamespace(finish_reason=finish_reason, message=message)
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    return SimpleNamespace(choices=[choice], usage=usage, id='test-completion-id')


def _make_stream_chunk(
    content: str = '',
    finish_reason: str | None = None,
    tool_call: dict | None = None,
):
    """Build a single streaming chunk."""
    delta_tool_calls = None
    if tool_call:
        delta_tool_calls = [
            SimpleNamespace(
                id=tool_call['id'],
                type='function',
                function=SimpleNamespace(
                    name=tool_call['tool_name'],
                    arguments=tool_call['arguments'],
                ),
                index=tool_call.get('index', 0),
            )
        ]
    delta = SimpleNamespace(
        content=content,
        reasoning_content='',
        tool_calls=delta_tool_calls,
    )
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    usage = SimpleNamespace(prompt_tokens=0, completion_tokens=0)
    return SimpleNamespace(choices=[choice], usage=usage, id='test-chunk-id')


class OpenAIContinueGenerationTests(unittest.TestCase):

    def _make_llm(self):
        conf = OmegaConf.create({
            'llm': {
                'model': 'test-model',
                'openai_base_url': 'http://localhost:9999/v1',
                'openai_api_key': 'sk-test',
            },
            'generation_config': {
                'stream': False,
            },
        })
        return OpenAI(conf)

    def test_continue_generate_returns_early_when_tool_calls_present(self):
        """A truncated assistant message with tool_calls must not be continued."""
        llm = self._make_llm()
        messages = [
            Message(role='system', content='You are a helpful assistant.'),
            Message(role='user', content='Write a long report.'),
        ]
        completion = _make_completion(
            content="I'll write the report",
            finish_reason='length',
            tool_calls=[{
                'id': 'call_abc',
                'tool_name': 'write_file',
                'arguments': '{"path": "/tmp/report.md"}',
            }],
        )

        result = llm._continue_generate(messages, completion)

        self.assertEqual(result.content, "I'll write the report")
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0]['id'], 'call_abc')
        # No continuation means _call_llm should not have been invoked.
        self.assertEqual(len(messages), 2)
        self.assertFalse(messages[-1].to_dict().get('partial', False))

    def test_continue_generate_still_continues_text_only_truncation(self):
        """A text-only truncated message should still enter the continue path."""
        llm = self._make_llm()
        messages = [
            Message(role='system', content='You are a helpful assistant.'),
            Message(role='user', content='Write a long report.'),
        ]
        continued_completion = _make_completion(
            content=' continued text',
            finish_reason='stop',
        )
        initial_completion = _make_completion(
            content='first part',
            finish_reason='length',
        )

        def fake_continue(messages, new_message, tools, **kwargs):
            # Mimic the real _call_llm_for_continue_gen side effects.
            messages.append(new_message)
            messages[-1].partial = True
            return continued_completion

        with patch.object(llm, '_call_llm_for_continue_gen', side_effect=fake_continue) as mock_continue:
            result = llm._continue_generate(messages, initial_completion)

        mock_continue.assert_called_once()
        self.assertEqual(result.content, 'first part continued text')

    def test_stream_continue_generate_returns_early_when_tool_calls_present(self):
        """A truncated streaming message with tool_calls must not be continued."""
        llm = self._make_llm()
        messages = [
            Message(role='system', content='You are a helpful assistant.'),
            Message(role='user', content='Write a long report.'),
        ]
        chunks = [
            _make_stream_chunk(content="I'll "),
            _make_stream_chunk(content='write the report'),
            _make_stream_chunk(
                content='',
                tool_call={
                    'id': 'call_abc',
                    'tool_name': 'write_file',
                    'arguments': '{"path": "/tmp/report.md"}',
                },
            ),
            _make_stream_chunk(finish_reason='length'),
        ]

        with patch.object(llm, '_call_llm_for_continue_gen') as mock_continue:
            yielded = list(llm._stream_continue_generate(messages, iter(chunks)))

        mock_continue.assert_not_called()
        final_message = yielded[-1]
        self.assertEqual(final_message.content, "I'll write the report")
        self.assertEqual(len(final_message.tool_calls), 1)
        self.assertEqual(final_message.tool_calls[0]['id'], 'call_abc')

    def test_stream_continue_generate_still_continues_text_only_truncation(self):
        """A text-only truncated stream should still enter the continue path."""
        llm = self._make_llm()
        messages = [
            Message(role='system', content='You are a helpful assistant.'),
            Message(role='user', content='Write a long report.'),
        ]
        initial_chunks = [
            _make_stream_chunk(content='first part'),
            _make_stream_chunk(finish_reason='length'),
        ]
        continued_chunks = [
            _make_stream_chunk(content=' continued'),
            _make_stream_chunk(finish_reason='stop'),
        ]

        def fake_continue(messages, message, tools, **kwargs):
            # Mimic the real _call_llm_for_continue_gen side effects.
            messages.append(message)
            messages[-1].partial = True
            return iter(continued_chunks)

        with patch.object(llm, '_call_llm_for_continue_gen', side_effect=fake_continue) as mock_continue:
            yielded = list(llm._stream_continue_generate(messages, iter(initial_chunks)))

        mock_continue.assert_called_once()
        self.assertEqual(yielded[-1].content, 'first part continued')

    def test_continue_generate_merges_and_returns_when_tool_calls_on_subsequent_run(self):
        """If a subsequent continuation run returns tool calls, it must merge and return the accumulated message."""
        llm = self._make_llm()
        messages = [
            Message(role='system', content='You are a helpful assistant.'),
            Message(role='user', content='Write a long report.'),
        ]
        initial_completion = _make_completion(
            content='first part',
            finish_reason='length',
        )
        continued_completion = _make_completion(
            content=' continued with tool',
            finish_reason='stop',
            tool_calls=[{
                'id': 'call_abc',
                'tool_name': 'write_file',
                'arguments': '{"path": "/tmp/report.md"}',
            }],
        )

        def fake_continue(messages, new_message, tools, **kwargs):
            # Mimic the real _call_llm_for_continue_gen side effects.
            messages.append(new_message)
            messages[-1].partial = True
            return continued_completion

        with patch.object(llm, '_call_llm_for_continue_gen', side_effect=fake_continue):
            result = llm._continue_generate(messages, initial_completion)

        self.assertEqual(result.content, 'first part continued with tool')
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0]['id'], 'call_abc')
        self.assertEqual(len(messages), 2)
        self.assertFalse(result.partial)

    def test_stream_continue_generate_merges_when_tool_calls_on_subsequent_run(self):
        """If a subsequent streaming continuation run returns tool calls, it must merge and clear partial flag."""
        llm = self._make_llm()
        messages = [
            Message(role='system', content='You are a helpful assistant.'),
            Message(role='user', content='Write a long report.'),
        ]
        initial_chunks = [
            _make_stream_chunk(content='first part'),
            _make_stream_chunk(finish_reason='length'),
        ]
        continued_chunks = [
            _make_stream_chunk(content=' continued'),
            _make_stream_chunk(
                content='',
                tool_call={
                    'id': 'call_abc',
                    'tool_name': 'write_file',
                    'arguments': '{"path": "/tmp/report.md"}',
                },
            ),
            _make_stream_chunk(finish_reason='length'),
        ]

        def fake_continue(messages, message, tools, **kwargs):
            # Mimic the real _call_llm_for_continue_gen side effects.
            messages.append(message)
            messages[-1].partial = True
            return iter(continued_chunks)

        with patch.object(llm, '_call_llm_for_continue_gen', side_effect=fake_continue):
            yielded = list(llm._stream_continue_generate(messages, iter(initial_chunks)))

        self.assertEqual(yielded[-1].content, 'first part continued')
        self.assertEqual(len(yielded[-1].tool_calls), 1)
        self.assertEqual(yielded[-1].tool_calls[0]['id'], 'call_abc')
        self.assertFalse(messages[-1].partial)


if __name__ == '__main__':
    unittest.main()
