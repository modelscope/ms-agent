# Copyright (c) ModelScope Contributors. All rights reserved.
"""Unit tests for /models discovery and chat-oriented filtering (no network)."""
from unittest.mock import MagicMock, patch

from ms_agent.llm.model_discovery import (
    fetch_model_ids,
    filter_chat_model_ids,
    format_id_list,
    is_non_chat_model,
    parse_model_ids,
    wire_protocol,
)


def test_parse_model_ids_openai_shape():
    ids = parse_model_ids({
        'data': [
            {'id': 'qwen-plus'},
            {'id': 'qwen-plus'},
            {'object': 'model'},
            'skip',
        ]
    })
    assert ids == ['qwen-plus']


def test_parse_model_ids_garbage():
    assert parse_model_ids(None) == []
    assert parse_model_ids({'data': 'nope'}) == []


def test_filter_keeps_chat_and_vision_drops_media():
    raw = [
        'qwen-plus',
        'qwen3.8-flash',
        'qwen-vl-max',
        'glm-4v',
        'gpt-4o',
        'wanx-v1',
        'wan2.1-t2v-plus',
        'qwen-image-plus',
        'text-embedding-v3',
        'tts-1',
        'dall-e-3',
        'video-01',
    ]
    kept, dropped = filter_chat_model_ids(raw)
    assert kept == [
        'qwen-plus',
        'qwen3.8-flash',
        'qwen-vl-max',
        'glm-4v',
        'gpt-4o',
    ]
    assert dropped == 7
    assert not is_non_chat_model('qwen-vl-plus')
    assert is_non_chat_model('cogview-3')
    assert is_non_chat_model('MiniMax/speech-02-hd')


def test_format_live_model_lines_groups_by_family_and_owner():
    from ms_agent.llm.model_discovery import format_live_model_lines
    lines = format_live_model_lines(
        [
            'MiniMax-M2.1',
            'MiniMax-M2.5',
            'MiniMax/MiniMax-M2.1',
            'ZHIPU/GLM-5',
            'deepseek-r1',
            'deepseek-v3',
            'gui-plus',
            'qwen-plus',
            'qwen3.8-flash',
            'qwen-vl-max',
        ],
        indent='  ',
    )
    text = '\n'.join(lines)
    assert '  MiniMax  (2)' in lines or '  MiniMax  (2)' in text
    assert '    MiniMax-M2.1' in lines
    assert '  MiniMax/  (1)' in lines
    assert '    MiniMax/MiniMax-M2.1' in lines
    assert '  ZHIPU/  (1)' in lines
    assert '    ZHIPU/GLM-5' in lines
    assert '  qwen  (3)' in lines
    assert '    qwen-plus' in lines
    assert '    qwen3.8-flash' in lines
    assert '  gui-plus' in lines
    assert '  deepseek  (2)' in lines
    # One id per line — no comma-joined blob.
    assert not any(',' in line and 'qwen-plus' in line for line in lines)


def test_format_id_list_caps():
    ids = [f'm{i}' for i in range(5)]
    assert format_id_list(ids, limit=3) == 'm0, m1, m2  … +2 more'
    assert format_id_list([], limit=3) == '(none)'


def test_wire_protocol():
    assert wire_protocol('anthropic_messages') == 'anthropic'
    assert wire_protocol('openai_compat') == 'openai'


def test_fetch_model_ids_ok():
    payload = {'data': [{'id': 'a'}, {'id': 'b'}]}
    resp = MagicMock(status_code=200)
    resp.json.return_value = payload
    client = MagicMock()
    client.get.return_value = resp
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    with patch('ms_agent.llm.model_discovery.httpx.Client', return_value=client):
        ids = fetch_model_ids('https://example.invalid/v1', 'openai', 'sk')
    assert ids == ['a', 'b']
    client.get.assert_called_once()
    args, kwargs = client.get.call_args
    assert args[0] == 'https://example.invalid/v1/models'
    assert kwargs['headers']['Authorization'] == 'Bearer sk'


def test_fetch_model_ids_non_2xx():
    resp = MagicMock(status_code=401)
    client = MagicMock()
    client.get.return_value = resp
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    with patch('ms_agent.llm.model_discovery.httpx.Client', return_value=client):
        assert fetch_model_ids('https://example.invalid/v1', 'openai', 'sk') == []
