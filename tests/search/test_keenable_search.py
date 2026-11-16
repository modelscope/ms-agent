# Copyright (c) ModelScope Contributors. All rights reserved.
"""Keenable engine: keyless by default, keyed with a key, errors the tool can act on.

All HTTP is mocked by patching ``urlopen`` in the engine module.
"""
import json
import pytest
from io import BytesIO
from urllib.error import HTTPError

from ms_agent.config import search_settings
from ms_agent.tools.search.keenable import search as keenable_mod
from ms_agent.tools.search.keenable.schema import (KeenableSearchRequest,
                                                   KeenableSearchResult)
from ms_agent.tools.search.keenable.search import (KeenableHTTPError,
                                                   KeenableSearch)
from ms_agent.tools.search.search_base import ENGINE_TOOL_NAMES
from ms_agent.tools.search.websearch_tool import (WebSearchTool,
                                                  get_search_engine,
                                                  get_search_engine_class)

BODY = {
    'query':
    'q',
    'mode':
    'pro',
    'results': [
        {
            'title': 'T1',
            'url': 'https://a.example/1',
            'description': '',
            'snippet': 'S1',
            'published_at': '2026-11-01T00:00:00Z',
        },
        {
            'title': 'T2',
            'url': 'https://a.example/2',
            'description': 'D2'
        },
        {
            'title': 'no url',
            'snippet': 'dropped'
        },
    ],
}


class _Resp:

    def __init__(self, body):
        self._raw = json.dumps(body).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Hdrs(dict):

    def get(self, key, default=None):
        return dict.get(self, key.lower(), default)


@pytest.fixture()
def no_env_key(monkeypatch):
    monkeypatch.delenv('KEENABLE_API_KEY', raising=False)


@pytest.fixture()
def capture(monkeypatch):
    seen = []

    def install(response=BODY, error=None):

        def fake_urlopen(req, timeout=None, context=None):
            seen.append(req)
            if error is not None:
                raise error
            return _Resp(response)

        monkeypatch.setattr(keenable_mod, 'urlopen', fake_urlopen)
        return seen

    return install


def test_keyless_posts_to_public_path_and_maps_rows(no_env_key, capture):
    seen = capture()
    result = KeenableSearch().search(KeenableSearchRequest('q', 3))

    req = seen[0]
    headers = {k.lower(): v for k, v in req.header_items()}
    assert req.full_url == 'https://api.keenable.ai/v1/search/public'
    assert req.get_method() == 'POST'
    assert headers['x-keenable-title'] == 'ms-agent'
    assert 'x-api-key' not in headers
    assert json.loads(req.data) == {'query': 'q', 'max_results': 3}
    assert result.arguments['access_mode'] == 'keyless'

    rows = result.to_list()
    assert [r['url']
            for r in rows] == ['https://a.example/1', 'https://a.example/2']
    assert rows[0]['summary'] == 'S1'
    assert rows[0]['published_date'] == '2026-11-01T00:00:00Z'
    assert rows[1]['summary'] == 'D2'


def test_key_switches_to_keyed_path(no_env_key, capture):
    seen = capture({'results': []})
    result = KeenableSearch(api_key='k-123').search(
        KeenableSearchRequest('q', 99))

    req = seen[0]
    headers = {k.lower(): v for k, v in req.header_items()}
    assert req.full_url == 'https://api.keenable.ai/v1/search'
    assert headers['x-api-key'] == 'k-123'
    assert json.loads(req.data)['max_results'] == 50
    assert 'k-123' not in json.dumps(result.arguments)
    assert result.to_list() == []


def test_env_key_is_used(monkeypatch, capture):
    monkeypatch.setenv('KEENABLE_API_KEY', 'env-key')
    seen = capture({'results': []})
    KeenableSearch().search(KeenableSearchRequest('q'))
    headers = {k.lower(): v for k, v in seen[0].header_items()}
    assert headers['x-api-key'] == 'env-key'


def test_rate_limit_is_reported_as_quota(no_env_key, capture):
    err = HTTPError(
        'https://api.keenable.ai/v1/search/public', 429, 'Too Many Requests',
        _Hdrs({'retry-after': '42'}),
        BytesIO(
            json.dumps({
                'code': 'public_rate_limit_hourly',
                'message': 'Rate limit exceeded'
            }).encode()))
    capture(error=err)

    with pytest.raises(KeenableHTTPError) as excinfo:
        KeenableSearch().search(KeenableSearchRequest('q'))

    exc = excinfo.value
    assert exc.status == 429 and exc.is_quota and not exc.is_auth
    assert exc.code == 'public_rate_limit_hourly'
    assert exc.retry_after == 42
    payload = WebSearchTool._search_error_payload('keenable', exc)
    assert payload['kind'] == 'quota_exceeded'
    assert payload['retry_after_seconds'] == 42


def test_auth_failure_is_reported_as_auth(no_env_key, capture):
    err = HTTPError('https://api.keenable.ai/v1/search', 401, 'Unauthorized',
                    _Hdrs(), BytesIO(b'{"code": "invalid_api_key"}'))
    capture(error=err)

    with pytest.raises(KeenableHTTPError) as excinfo:
        KeenableSearch(api_key='bad').search(KeenableSearchRequest('q'))

    assert excinfo.value.is_auth
    assert 'bad' not in str(excinfo.value)


def test_registration_and_settings(no_env_key):
    assert 'keenable' in WebSearchTool.SUPPORTED_ENGINES
    assert ENGINE_TOOL_NAMES['keenable'] == 'keenable_search'
    assert get_search_engine_class('keenable') is KeenableSearch
    assert isinstance(get_search_engine('keenable'), KeenableSearch)
    assert KeenableSearch.get_tool_name() == 'keenable_search'
    assert KeenableSearch.build_request_from_args(
        query='q', num_results='7').num_results == 7
    assert search_settings.supports_keyless('keenable')
    assert search_settings.key_field_for('keenable') == 'keenable_api_key'
    # Tavily stays the default engine.
    assert search_settings.default_engine() == 'tavily'


def test_empty_response_has_no_rows():
    assert KeenableSearchResult(query='q').to_list() == []
