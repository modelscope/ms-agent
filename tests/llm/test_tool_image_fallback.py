# Copyright (c) ModelScope Contributors. All rights reserved.
import base64
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from ms_agent.llm import multimodal
from ms_agent.llm.transport.anthropic_messages import AnthropicMessagesTransport
from ms_agent.llm.utils import Message


class ImageRejected(Exception):
    status_code = 400


def image_attachment(tmp_path, name, size):
    Image.new('RGB', size, 'navy').save(tmp_path / name)
    return {'type': 'image', 'path': name, 'media_type': 'image/png'}


def tool_messages(attachment):
    return [
        Message(
            role='assistant',
            tool_calls=[{
                'id': 'call-1',
                'tool_name': 'render',
                'arguments': '{}'
            }]),
        Message(
            role='tool',
            tool_call_id='call-1',
            content='rendered',
            attachments=[attachment] if attachment else []),
    ]


def transport(tmp_path, create):
    client = SimpleNamespace(
        base_url='https://example.test',
        messages=SimpleNamespace(create=create))
    result = AnthropicMessagesTransport.__new__(AnthropicMessagesTransport)
    result.client = client
    result.model = 'test-model'
    result._vision = multimodal.VisionOptions(
        workspace_root=str(tmp_path), max_edge=2560)
    result._vision_supported = True
    result._last_deliveries = []
    return result


def tool_result(messages):
    return next(block for message in messages for block in message['content']
                if block.get('type') == 'tool_result')


def test_tool_image_size_rejection_retries_with_smaller_image(tmp_path):
    calls = []

    def create(**kwargs):
        result = tool_result(kwargs['messages'])
        image = next(b for b in result['content'] if b['type'] == 'image')
        with Image.open(io.BytesIO(base64.b64decode(
                image['source']['data']))) as im:
            calls.append((result, max(im.size)))
        if calls[-1][1] > 2048:
            raise ImageRejected('input size exceed limit 2048x2048')
        return 'ok'

    attachment = image_attachment(tmp_path, 'result.png', (2560, 1200))
    result = transport(tmp_path, create)._call_llm(tool_messages(attachment))
    assert result == 'ok'
    assert [edge for _, edge in calls] == [2560, 2048]
    assert calls[-1][0]['tool_use_id'] == 'call-1'
    assert calls[-1][0]['content'][-1] == {'type': 'text', 'text': 'rendered'}


def test_tool_image_refusal_keeps_tool_result_and_text(tmp_path):
    calls = []

    def create(**kwargs):
        result = tool_result(kwargs['messages'])
        calls.append(result)
        if any(block['type'] == 'image' for block in result['content']):
            raise ImageRejected('Unexpected item type in content')
        return 'ok'

    attachment = image_attachment(tmp_path, 'result.png', (64, 64))
    result = transport(tmp_path, create)._call_llm(tool_messages(attachment))
    assert result == 'ok'
    assert len(calls) == 2
    assert calls[-1]['tool_use_id'] == 'call-1'
    assert calls[-1]['content'][-1] == {'type': 'text', 'text': 'rendered'}
    assert any('Do not guess' in block.get('text', '')
               for block in calls[-1]['content'])


def test_image_count_recovery_keeps_latest_across_user_and_tool_results(
        tmp_path):
    calls = []

    def create(**kwargs):
        messages = kwargs['messages']
        calls.append(messages)
        user_images = sum(b['type'] == 'image' for b in messages[0]['content'])
        results = messages[-1]['content']
        tool_images = sum(b['type'] == 'image' for result in results
                          for b in result['content'])
        if user_images + tool_images > 1:
            raise ImageRejected('at most 1 image is supported')
        return 'ok'

    attachments = [
        image_attachment(tmp_path, f'{i}.png', (64, 64)) for i in range(3)
    ]
    messages = [
        Message(role='user', content='compare', attachments=[attachments[0]]),
        Message(
            role='assistant',
            tool_calls=[
                {
                    'id': 'call-1',
                    'tool_name': 'render',
                    'arguments': '{}'
                },
                {
                    'id': 'call-2',
                    'tool_name': 'render',
                    'arguments': '{}'
                },
            ]),
        Message(
            role='tool',
            tool_call_id='call-1',
            content='first',
            attachments=[attachments[1]]),
        Message(
            role='tool',
            tool_call_id='call-2',
            content='second',
            attachments=[attachments[2]]),
    ]
    assert transport(tmp_path, create)._call_llm(messages) == 'ok'
    assert len(calls) == 2
    user, _, result_message = calls[-1]
    assert not any(b['type'] == 'image' for b in user['content'])
    results = result_message['content']
    assert [r['tool_use_id'] for r in results] == ['call-1', 'call-2']
    assert not any(b['type'] == 'image' for b in results[0]['content'])
    assert sum(b['type'] == 'image' for b in results[1]['content']) == 1
    assert results[0]['content'][-1] == {'type': 'text', 'text': 'first'}
    assert results[1]['content'][-1] == {'type': 'text', 'text': 'second'}


def test_text_only_tool_error_is_not_retried(tmp_path):
    calls = []
    error = ImageRejected('Unexpected item type in content')

    def create(**kwargs):
        calls.append(kwargs)
        raise error

    with pytest.raises(ImageRejected) as caught:
        transport(tmp_path, create)._call_llm(tool_messages(None))
    assert caught.value is error
    assert len(calls) == 1
