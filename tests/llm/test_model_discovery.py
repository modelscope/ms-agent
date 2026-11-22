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


def test_probe_405_and_404_are_no_catalog():
    from ms_agent.llm.model_discovery import probe_model_catalog
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    with patch('ms_agent.llm.model_discovery.httpx.Client', return_value=client):
        for code in (404, 405):
            client.get.return_value = MagicMock(status_code=code)
            probe = probe_model_catalog(
                'https://example.invalid/v1', 'openai', 'sk')
            assert probe.outcome == 'no_catalog'
            assert probe.status == code
            assert probe.ids == []


def test_probe_keeps_auth_status():
    from ms_agent.llm.model_discovery import probe_model_catalog
    resp = MagicMock(status_code=401)
    client = MagicMock()
    client.get.return_value = resp
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    with patch('ms_agent.llm.model_discovery.httpx.Client', return_value=client):
        probe = probe_model_catalog('https://example.invalid/v1', 'openai', 'sk')
    assert probe.outcome == 'auth'
    assert probe.status == 401
    assert probe.ids == []


def test_probe_empty_body_is_not_a_missing_id():
    from ms_agent.llm.model_discovery import probe_model_catalog
    resp = MagicMock(status_code=200)
    resp.json.return_value = {'unexpected': True}
    client = MagicMock()
    client.get.return_value = resp
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    with patch('ms_agent.llm.model_discovery.httpx.Client', return_value=client):
        probe = probe_model_catalog('https://example.invalid/v1', 'openai', 'sk')
    assert probe.outcome == 'no_catalog'
    assert probe.status == 200


def test_probe_timeout_is_unreachable():
    import httpx
    from ms_agent.llm.model_discovery import probe_model_catalog
    client = MagicMock()
    client.get.side_effect = httpx.ConnectError('nope')
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    with patch('ms_agent.llm.model_discovery.httpx.Client', return_value=client):
        probe = probe_model_catalog('https://example.invalid/v1', 'openai', 'sk')
    assert probe.outcome == 'unreachable'
    assert probe.status is None


def test_chat_unsupported_stays_on_modality_phrases():
    from ms_agent.llm.model_discovery import chat_failed_because_unsupported
    missed = (
        'gemini-2.5-flash-image-preview',
        'lumina-image-2.0',
        'ideogram-v3',
        'midjourney-v7',
        'recraft-v3',
        'playground-v2.5-1024px-aesthetic',
        'hidream-i1-full',
        'seedream-4.0',
        'nano-banana',
        'veo3',
        'luma-dream-machine',
        'runway-gen4',
        'pika-2.2',
        'minimax-hailuo-02',
        'z-image-turbo',
        'unisound-u2',
        'chattts',
        'bge-m3',
        'm3e-base',
    )
    for name in missed:
        assert not chat_failed_because_unsupported(name, '')
    invalid = "Error code: 400 - {'error':{'message':'Invalid model id'}}"
    assert not chat_failed_because_unsupported('z-image-turbo', invalid)
    assert not chat_failed_because_unsupported('qwen-vl-max', invalid)
    assert not chat_failed_because_unsupported('qwen-plus', '401 Unauthorized')
    assert chat_failed_because_unsupported(
        'qwen-plus', 'This endpoint only supports embeddings')
    assert chat_failed_because_unsupported('wanx-v1', '')


def test_rejected_model_id_is_separate_from_cannot_chat():
    from ms_agent.llm.model_discovery import model_id_rejected
    assert model_id_rejected(
        "Error code: 400 - {'error':{'message':'Invalid model id'}}")
    assert model_id_rejected('Error code: 400 - Model does not exist')
    assert model_id_rejected('Error code: 404 - The model `x` does not exist')
    assert model_id_rejected('model_not_supported')
    assert model_id_rejected(
        "Error code: 400 - {'error': {'message': "
        "'Model id : Qwen/old , has no provider supported'}}")
    assert not model_id_rejected('401 Unauthorized')
    assert not model_id_rejected('403 Forbidden')
    assert not model_id_rejected('does not exist')
    assert not model_id_rejected('This endpoint only supports embeddings')
    assert not model_id_rejected('')


def test_fetch_model_ids_non_2xx():
    resp = MagicMock(status_code=401)
    client = MagicMock()
    client.get.return_value = resp
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    with patch('ms_agent.llm.model_discovery.httpx.Client', return_value=client):
        assert fetch_model_ids('https://example.invalid/v1', 'openai', 'sk') == []
