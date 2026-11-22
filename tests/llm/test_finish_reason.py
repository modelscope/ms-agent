# Copyright (c) ModelScope Contributors. All rights reserved.
"""Offline finish-reason regressions: no clients, credentials or API calls."""
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import pytest

from ms_agent.llm.anthropic_llm import Anthropic
from ms_agent.llm.openai_llm import OpenAI
from ms_agent.llm.transport.anthropic_messages import AnthropicMessagesTransport
from ms_agent.llm.transport.openai_compat import OpenAICompatTransport
from ms_agent.llm.utils import Message, collect_response

CHAT_ENGINES = [OpenAI, OpenAICompatTransport]
ANTHROPIC_ENGINES = [Anthropic, AnthropicMessagesTransport]
CONTINUATION_MODES = [(OpenAI, 'partial'),
                      (OpenAICompatTransport, 'partial'),
                      (OpenAICompatTransport, 'prefix')]


def _unused_create(*, stream=False, max_tokens=None):
    raise AssertionError('Tests must not call a model client')


def _engine(cls, mode=None):
    # Skip constructors entirely: no credential resolution or HTTP client.
    engine = cls.__new__(cls)
    engine.model = 'test-model'
    engine.args = {}
    engine.max_continue_runs = 1
    engine._active_stream = None
    engine.client = NS(chat=NS(completions=NS(create=_unused_create)))
    if cls is OpenAI:
        engine._use_responses_api = False
        engine._responses_state_mode = 'stateless'
    elif cls is OpenAICompatTransport:
        engine.continue_gen_mode = mode
        engine._continue_flag = mode or 'partial'
        engine.continue_gen_stop = []
        engine._strip_reasoning_tags = False
    return engine


def _completion(text='##', reason='stop', response_id='r1'):
    return NS(
        id=response_id,
        model='test-model',
        usage=NS(prompt_tokens=100, completion_tokens=2048),
        choices=[NS(
            finish_reason=reason,
            message=NS(content=text, reasoning_content='', tool_calls=[]))])


def _chunk(text='', reason=None, response_id='r1', choices=True):
    return NS(
        id=response_id,
        usage=None,
        choices=[NS(
            finish_reason=reason,
            delta=NS(content=text, reasoning_content='', tool_calls=[]))]
        if choices else [])


def _stream(text='##', reason='stop', response_id='r1'):
    finish = _chunk(reason=reason, response_id=response_id)
    finish.choices[0].delta = None  # A terminal chunk need not carry any delta.
    trailer = _chunk(choices=False, response_id=response_id)
    trailer.usage = NS(prompt_tokens=100, completion_tokens=2048)
    return iter([_chunk(text, response_id=response_id), finish, trailer])


@pytest.mark.parametrize('reason', ['', 'stop', 'length', 'tool_calls'])
def test_message_finish_reason_is_output_only(reason):
    legacy = Message(**{'role': 'assistant', 'content': '##'})
    assert legacy.finish_reason == ''
    legacy.finish_reason = reason
    assert Message(**legacy.to_dict()).finish_reason == reason
    assert legacy.to_dict_clean() == {'role': 'assistant', 'content': '##'}


@pytest.mark.parametrize('max_calls', [0, 1])
@pytest.mark.parametrize('cls', CHAT_ENGINES)
@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('reason', ['stop', 'length', None])
def test_generate_does_not_infer_finish_from_text_or_token_count(cls, stream,
                                                               reason, max_calls):
    engine = _engine(cls)
    engine.max_continue_runs = 5
    completion = _stream(reason=reason) if stream else _completion(reason=reason)
    with patch.object(engine, '_call_llm', return_value=completion) as call:
        result = collect_response(engine.generate(
            [Message('user', 'summarize')], stream=stream,
            max_tokens=2048, max_continue_runs=max_calls))
    assert result.content == '##'
    assert result.completion_tokens == 2048
    assert result.finish_reason == (reason or '')
    call.assert_called_once()  # Metadata must not introduce retries/continuation.
    assert call.call_args.kwargs['max_tokens'] == 2048


def test_typed_adapter_preserves_truncation():
    from ms_agent.llm.adapter import ResponseAdapter

    message = Message('assistant', 'partial', finish_reason='length')
    response = ResponseAdapter.to_response(message)
    assert response.finish_reason == 'length'
    assert ResponseAdapter.to_message(response).finish_reason == 'length'


@pytest.mark.parametrize('cls', CHAT_ENGINES)
@pytest.mark.parametrize('reason,expected', [
    ('stop', 'stop'), ('length', 'length'), ('max_tokens', 'length'),
    ('tool_calls', 'tool_calls'), ('content_filter', 'content_filter'),
    ('vendor_reason', 'vendor_reason'), (None, '')])
def test_chat_formatters_preserve_explicit_reasons(cls, reason, expected):
    assert cls._format_output_message(
        _completion(reason=reason)).finish_reason == expected
    assert cls._stream_format_output_message(
        _chunk(reason=reason)).finish_reason == expected
    missing = _completion()
    del missing.choices[0].finish_reason
    assert cls._format_output_message(missing).finish_reason == ''


@pytest.mark.parametrize('cls', CHAT_ENGINES)
@pytest.mark.parametrize('reason', ['stop', 'length'])
@pytest.mark.parametrize('text_in_finish', [False, True])
def test_chat_stream_finish_and_usage_trailer(cls, reason, text_in_finish):
    engine = _engine(cls)
    chunks = list(_stream(reason=reason))
    if text_in_finish:
        chunks[1] = _chunk('final', reason=reason)
    snapshots = [deepcopy(m) for m in engine._stream_continue_generate(
        [Message('user', 'hi')], iter(chunks), max_runs=0)]
    assert snapshots[0].finish_reason == ''
    assert snapshots[-1].finish_reason == reason
    assert snapshots[-1].content == ('##final' if text_in_finish else '##')
    assert snapshots[-1].completion_tokens == 2048
    # Also cover callers merging usage/empty deltas after a finish chunk.
    for empty in (_chunk(), _chunk(choices=False)):
        merged = engine._merge_stream_message(
            snapshots[-1], engine._stream_format_output_message(empty))
        assert merged.finish_reason == reason


@pytest.mark.parametrize('cls', CHAT_ENGINES)
def test_chat_stream_can_finish_without_text(cls):
    engine = _engine(cls)
    result = collect_response(engine._stream_continue_generate(
        [Message('user', 'hi')], _stream(text='', reason='length'), max_runs=0))
    assert result.content == ''
    assert result.finish_reason == 'length'


@pytest.mark.parametrize('cls,mode', CONTINUATION_MODES)
@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('last_reason', ['stop', 'length', None])
def test_continuation_reports_last_call_not_previous_truncation(
        cls, mode, stream, last_reason):
    engine = _engine(cls, mode)
    messages = [Message('user', 'hi')]
    factory = _stream if stream else _completion
    calls = [factory('A', 'length', 'r1'), factory('B', 'length', 'r2'),
             factory('C', last_reason, 'r3')]
    with patch.object(engine, '_call_llm', side_effect=calls[1:]) as call:
        if stream:
            snapshots = []
            for message in engine._stream_continue_generate(
                    messages, calls[0], max_runs=2):
                snapshots.append(deepcopy(message))
                # The agent replaces history with every streamed snapshot.
                if messages[-1].role == 'user':
                    messages.append(message)
                else:
                    messages[-1] = message
            result = snapshots[-1]
            assert all(m.finish_reason == '' for m in snapshots[:-1])
        else:
            result = engine._continue_generate(messages, calls[0], max_runs=2)
    assert call.call_count == 2
    assert result.content == 'ABC'
    assert result.finish_reason == (last_reason or '')
    assert result.completion_tokens == 3 * 2048
    assert result.api_calls == 3


class _StreamManager:

    def __init__(self, events):
        self.events = events
        self.closed = False

    def __enter__(self):
        return iter(self.events)

    def __exit__(self, *args):
        self.closed = True


@pytest.mark.parametrize('cls', ANTHROPIC_ENGINES)
@pytest.mark.parametrize('reason,expected', [
    ('max_tokens', 'length'), ('end_turn', 'stop'), ('stop_sequence', 'stop'),
    ('tool_use', 'tool_use'), ('refusal', 'refusal'), (None, '')])
def test_anthropic_nonstream_finish_reason(cls, reason, expected):
    completion = NS(id='a', content=[NS(type='text', text='##')],
                    usage=None, stop_reason=reason)
    result = cls._format_output_message(completion)
    assert result.finish_reason == expected
    assert result.content == '##'
    del completion.stop_reason
    assert cls._format_output_message(completion).finish_reason == ''


@pytest.mark.parametrize('cls', ANTHROPIC_ENGINES)
@pytest.mark.parametrize('reason,expected', [
    ('max_tokens', 'length'), ('end_turn', 'stop'), ('tool_use', 'tool_use')])
@pytest.mark.parametrize('reason_source', ['delta', 'final', 'both'])
def test_anthropic_stream_finish_survives_empty_deltas_and_final_message(
        cls, reason, expected, reason_source):
    engine = _engine(cls)
    stop = NS(type='message_stop')
    if reason_source in ('final', 'both'):
        stop.message = NS(
            content=[NS(type='text', text='##')],
            stop_reason=reason if reason_source == 'final' else None)
    events = [
        NS(type='message_start', message=NS(id='a')),
        NS(type='content_block_delta', delta=NS(type='text_delta', text='##')),
        NS(type='message_delta', delta=NS(
            stop_reason=reason if reason_source != 'final' else None)),
        NS(type='message_delta', delta=NS(stop_reason=None),
           usage=NS(output_tokens=2048)),
        stop,
    ]
    manager = _StreamManager(events)
    snapshots = [deepcopy(m) for m in engine._stream_format_output_message(manager)]
    assert snapshots[0].finish_reason == ''
    assert snapshots[-1].finish_reason == expected
    assert snapshots[-1].content == '##'
    assert snapshots[-1].partial is False
    assert snapshots[-1].completion_tokens == 2048
    assert manager.closed


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('status,details,expected', [
    ('completed', None, 'stop'),
    ('incomplete', NS(reason='max_output_tokens'), 'length'),
    ('incomplete', {'reason': 'max_output_tokens'}, 'length'),
    ('incomplete', NS(reason='content_filter'), 'content_filter'),
    ('incomplete', None, 'incomplete'),
    ('incomplete', {}, 'incomplete'),
    (None, None, ''),
])
def test_responses_api_status_and_incomplete_details(stream, status, details,
                                                    expected):
    engine = _engine(OpenAI)
    response = NS(id='resp', output_text='##', output=[],
                  usage=NS(input_tokens=100, output_tokens=2048),
                  incomplete_details=details)
    if status is not None:
        response.status = status
    event_type = ('response.incomplete' if status == 'incomplete'
                  else 'response.completed')
    completion = iter([
        NS(type='response.output_text.delta', delta='##'),
        NS(type=event_type, response=response),
        NS(type='response.output_text.delta', delta=''),
    ]) if stream else response
    create = Mock(return_value=completion)
    engine._responses_client = NS(responses=NS(create=create))
    # Exercise the real request wrapper with a fake create method, no HTTP client.
    if stream:
        result = collect_response(engine._responses_stream_generate(
            [Message('user', 'hi')], max_output_tokens=2048))
    else:
        result = engine._responses_generate(
            [Message('user', 'hi')], max_output_tokens=2048)
    assert result.finish_reason == expected
    assert result.content == '##'
    assert result.id == 'resp'
    assert result.completion_tokens == 2048
    create.assert_called_once()
    assert create.call_args.kwargs['max_output_tokens'] == 2048


def test_responses_failed_stream_still_raises():
    engine = _engine(OpenAI)
    create = Mock(return_value=iter([NS(
        type='response.failed',
        response=NS(status='failed', error=NS(message='failure')))]))
    engine._responses_client = NS(responses=NS(create=create))
    with pytest.raises(RuntimeError, match='Responses API call failed: failure'):
        collect_response(engine._responses_stream_generate([Message('user', 'hi')]))
    create.assert_called_once()
