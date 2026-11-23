"""Context through the existing native search tool, including refusals."""
import asyncio
import json
import traceback
from unittest.mock import patch

import httpx
import pytest
from omegaconf import OmegaConf

from ms_agent.config.search_settings import SearchSettingsManager
from ms_agent.config.secrets import resolve_secret
from ms_agent.tools.search.context import ContextSearch
from ms_agent.tools.search.websearch_tool import WebSearchTool


def config(key='synthetic-context-key'):
    return OmegaConf.create({'tools': {'web_search': {
        'engine': 'context', 'context_api_key': key, 'fetch_content': False,
        'enable_summarization': False, 'enable_rerank': False,
    }}})


def hit(**changes):
    return {'title': 'Source', 'url': 'https://example.com/',
            'description': 'Discovery description',
            'highlights': {'code': 'SUCCESS', 'highlights': ['first', 'second']},
            **changes}


def native_call(monkeypatch, payload=None, *, status=200, error=None, query='query', count=5):
    calls = []
    original = httpx.Client

    def respond(request):
        calls.append(request)
        if error:
            raise error
        return httpx.Response(status, json=payload, headers={'Location': 'https://redirect.example/'})

    def client(*args, **kwargs):
        return original(*args, **kwargs, transport=httpx.MockTransport(respond))

    async def run():
        tool = WebSearchTool(config())
        await tool.connect()
        try:
            names = [item['tool_name'] for item in (await tool.get_tools())['web_search']]
            assert 'context_search' in names
            return json.loads(await tool.call_tool('web_search', tool_name='context_search',
                tool_args={'query': query, 'num_results': count, 'fetch_content': False}))
        finally:
            await tool.cleanup()

    with monkeypatch.context() as scoped:
        scoped.setattr(httpx, 'Client', client)
        result = asyncio.run(run())
    return result, calls


def test_native_context_tool_uses_highlights_and_header(monkeypatch):
    result, calls = native_call(monkeypatch, {'results': [hit()]})
    assert result['status'] == 'ok'
    assert result['results'][0]['summary'] == 'first\nsecond'
    assert result['results'][0]['url'] == 'https://example.com/'
    request = calls[0]
    assert str(request.url) == 'https://api.context.dev/v1/web/search'
    assert request.headers['authorization'] == 'Bearer synthetic-context-key'
    body = json.loads(request.content)
    assert body['numResults'] == 5
    assert body['highlightsOptions'] == {'enabled': True, 'maxCharacters': 4000}
    assert 'api_key' not in body


@pytest.mark.parametrize('highlights', [None, {'code': 'ERROR'}, {'code': 'SUCCESS', 'highlights': []}])
def test_unavailable_highlights_are_not_presented_as_page_passages(monkeypatch, highlights):
    result, _ = native_call(monkeypatch, {'results': [hit(highlights=highlights)]})
    assert result['status'] == 'ok'
    assert result['results'][0]['summary'] == '[Highlights unavailable; search description only] Discovery description'


def test_empty_success_is_preserved(monkeypatch):
    result, _ = native_call(monkeypatch, {'results': [], 'partial': False})
    assert result['status'] == 'ok' and result['count'] == 0


@pytest.mark.parametrize('payload', [None, [], {}, {'results': None}, {'results': [None]},
    {'results': [hit(url=12)]}, {'results': [hit(title={})]},
    {'results': [hit(description=[])]}, {'results': [hit(highlights={'code': 'SUCCESS', 'highlights': [12]})]},
    {'results': [], 'partial': True}, {'results': [], 'partial': 'false'}, {'results': [], 'partial': None}, {'results': [], 'partial': 0},
    {'results': [hit(url='file:///tmp/secret')]}, {'results': [hit(url='http://127.0.0.1/')]},
    {'results': [hit(url='https://name:password@example.com/')]},
    {'results': [hit(highlights={'code': 'SUCCESS', 'highlights': ['valid', None]})]}])
def test_incomplete_or_malformed_results_fail_explicitly(monkeypatch, payload):
    result, _ = native_call(monkeypatch, payload)
    assert result['status'] == 'error'
    assert result['count'] == 0
    assert result['kind'] == 'search_failed'


@pytest.mark.parametrize('status', [302, 401, 402, 403, 429, 500])
def test_provider_refusals_never_echo_provider_payload_or_follow_redirect(monkeypatch, caplog, status):
    canary = 'synthetic-credential-canary\\x21'
    result, calls = native_call(monkeypatch, {'message': canary}, status=status)
    assert result['status'] == 'error'
    assert len(calls) == 1
    assert canary not in json.dumps(result) + caplog.text


@pytest.mark.parametrize('error', [httpx.ConnectError('synthetic-secret-raw\\x21'),
                                  httpx.ReadTimeout('synthetic-secret-raw\\x21')])
def test_transport_errors_keep_raw_and_escaped_credentials_out_of_full_trace(monkeypatch, caplog, error):
    result, _ = native_call(monkeypatch, error=error)
    assert result['status'] == 'error'
    assert 'synthetic-secret' not in json.dumps(result) + caplog.text
    engine = ContextSearch(api_key='synthetic-key')
    with patch('httpx.Client', side_effect=error):
        with pytest.raises(RuntimeError) as failed:
            engine.search(engine.build_request_from_args(query='q'))
    assert 'synthetic-secret' not in ''.join(traceback.format_exception(failed.value))
    assert failed.value.__cause__ is None
    assert failed.value.__context__ is None


@pytest.mark.parametrize('query,count', [('q' * 501, 5), ('q', 0), ('q', 101), ('q', True)])
def test_invalid_context_arguments_fail_before_network(monkeypatch, query, count):
    result, calls = native_call(monkeypatch, {'results': []}, query=query, count=count)
    assert result['status'] == 'error' and not calls


def test_context_requires_key_and_preserves_existing_defaults(monkeypatch):
    monkeypatch.delenv('CONTEXT_DEV_API_KEY', raising=False)
    with pytest.raises(ValueError, match='CONTEXT_DEV_API_KEY'):
        ContextSearch()
    assert WebSearchTool(OmegaConf.create({'tools': {'web_search': {}}}))._engine_types == ['arxiv']


def test_context_managed_key_is_encrypted_and_other_provider_keys_survive(tmp_path):
    manager = SearchSettingsManager(tmp_path)
    assert manager.get().engine == 'tavily'
    manager.set_engine('context')
    manager.set_api_key('synthetic-context-credential')
    data = json.loads((tmp_path / 'settings.json').read_text())
    encrypted = data['tools']['web_search']['context_api_key']
    assert encrypted.startswith('enc:v1:')
    assert resolve_secret(encrypted, home=tmp_path) == 'synthetic-context-credential'
    assert 'synthetic-context-credential' not in json.dumps(data)
    manager.set_engine('tavily')
    manager.set_engine('context')
    assert manager.get().has_key
    manager.set_api_key(None)
    assert not manager.get().has_key
