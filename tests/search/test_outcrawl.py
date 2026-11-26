# Copyright (c) ModelScope Contributors. All rights reserved.
"""Outcrawl search engine and scrape fetcher.

Offline tests patch the HTTP layer. The two ``*_real`` tests call
api.outcrawl.ai and are skipped unless OUTCRAWL_API_KEY is set.
"""
import json
import os
from io import BytesIO
from urllib.error import HTTPError

import pytest
from ms_agent.tools.search.outcrawl import http as outcrawl_http
from ms_agent.tools.search.outcrawl.fetcher import OutcrawlScrapeFetcher
from ms_agent.tools.search.outcrawl.schema import (OutcrawlSearchRequest,
                                                   OutcrawlSearchResult)
from ms_agent.tools.search.outcrawl.search import OutcrawlSearch
from ms_agent.tools.search.search_base import (ENGINE_TOOL_NAMES,
                                               SearchEngineType)
from ms_agent.tools.search.websearch_tool import (WebSearchTool,
                                                  get_content_fetcher,
                                                  get_search_engine,
                                                  get_search_engine_class)

SEARCH_RESPONSE = {
    'hits': [
        {
            'url': 'https://example.com/a',
            'title': 'A',
            'snippet': 'first',
            'rank': 1
        },
        {
            'url': 'https://example.com/b',
            'title': 'B',
            'snippet': 'second',
            'rank': 2,
            'markdown': '# B page'
        },
    ],
    'usage': {
        'credits': '1'
    },
}

SCRAPE_RESPONSE = {
    'url': 'https://example.com/',
    'statusCode': 200,
    'markdown': '# Example Domain',
    'metadata': {
        'title': 'Example Domain',
        'language': 'en'
    },
    'usage': {
        'credits': '1'
    },
}

AUTH_BODY = {
    'code': 'unauthorized',
    'message': 'authentication failed: no api key presented',
    'details': {
        'reason': 'missing_token'
    },
}


class _Hdrs(dict):

    def get(self, key, default=None):
        return dict.get(self, key.lower(), default)


def _raise_http(status, body, headers=None):

    def boom(*args, **kwargs):
        raise HTTPError('https://api.outcrawl.ai/v1/search', status, 'err',
                        _Hdrs(headers or {}),
                        BytesIO(json.dumps(body).encode()))

    return boom


@pytest.fixture()
def no_env_key(monkeypatch):
    monkeypatch.delenv('OUTCRAWL_API_KEY', raising=False)


# ------------------------------------------------------------ registration


def test_engine_is_registered():
    assert SearchEngineType.OUTCRAWL.value == 'outcrawl'
    assert ENGINE_TOOL_NAMES['outcrawl'] == 'outcrawl_search'
    assert 'outcrawl' in WebSearchTool.SUPPORTED_ENGINES
    assert get_search_engine_class('outcrawl') is OutcrawlSearch
    assert OutcrawlSearch.get_tool_name() == 'outcrawl_search'


def test_factories_pass_the_key(no_env_key):
    engine = get_search_engine('outcrawl', api_key='oc-K')
    assert isinstance(engine, OutcrawlSearch)
    fetcher = get_content_fetcher('outcrawl_scrape', outcrawl_api_key='oc-K')
    assert isinstance(fetcher, OutcrawlScrapeFetcher)


def test_missing_key_raises(no_env_key):
    with pytest.raises(ValueError, match='OUTCRAWL_API_KEY'):
        OutcrawlSearch()


def test_env_key_is_used(monkeypatch):
    monkeypatch.setenv('OUTCRAWL_API_KEY', 'oc-FROM-ENV')
    assert OutcrawlSearch()._api_key == 'oc-FROM-ENV'


# --------------------------------------------------------------- request


def test_request_body_shape():
    assert OutcrawlSearchRequest(query='q', limit=3).to_api_body() == {
        'query': 'q',
        'limit': 3
    }
    body = OutcrawlSearchRequest(query='q', limit=50, scrape=True).to_api_body()
    assert body == {
        'query': 'q',
        'limit': 20,
        'scrape': True,
        'formats': ['markdown']
    }


def test_build_request_from_tool_args():
    req = OutcrawlSearch.build_request_from_args(
        query='q', num_results='4', scrape='true')
    assert (req.query, req.limit, req.scrape) == ('q', 4, True)
    assert OutcrawlSearch.build_request_from_args(query='q').limit == 5


def test_tool_definition():
    tool = OutcrawlSearch.get_tool_definition()
    assert tool['tool_name'] == 'outcrawl_search'
    assert tool['parameters']['required'] == ['query']
    assert 'scrape' in tool['parameters']['properties']


# ---------------------------------------------------------------- search


def test_search_posts_with_bearer_and_parses_hits(no_env_key, monkeypatch):
    seen = {}

    def fake_post(path, body, *, api_key, timeout=60.0):
        seen.update(path=path, body=body, api_key=api_key)
        return SEARCH_RESPONSE

    monkeypatch.setattr('ms_agent.tools.search.outcrawl.search.post_json',
                        fake_post)
    result = OutcrawlSearch(api_key='oc-K').search(
        OutcrawlSearchRequest(query='q', limit=2))
    assert seen == {
        'path': '/search',
        'body': {
            'query': 'q',
            'limit': 2
        },
        'api_key': 'oc-K'
    }
    rows = result.to_list()
    assert [r['url'] for r in rows] == [
        'https://example.com/a', 'https://example.com/b'
    ]
    assert rows[0]['summary'] == 'first'
    assert rows[0]['fetch_success'] is False
    # Scraped hits prefill content so WebSearchTool skips the fetch step.
    assert rows[1]['content'] == '# B page'
    assert rows[1]['fetch_success'] is True


def test_empty_response_gives_no_rows():
    assert OutcrawlSearchResult(query='q', arguments={},
                                response={}).to_list() == []


def test_http_sends_authorization_header(monkeypatch):
    seen = {}

    class _Resp:

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(SEARCH_RESPONSE).encode()

    def fake_urlopen(req, timeout=None, context=None):
        seen['url'] = req.full_url
        seen['auth'] = req.get_header('Authorization')
        seen['user_agent'] = req.get_header('User-agent')
        seen['body'] = json.loads(req.data)
        return _Resp()

    monkeypatch.setattr(outcrawl_http, 'urlopen', fake_urlopen)
    data = outcrawl_http.post_json('/search', {'query': 'q'}, api_key='oc-K')
    assert data == SEARCH_RESPONSE
    assert seen == {
        'url': 'https://api.outcrawl.ai/v1/search',
        'auth': 'Bearer oc-K',
        'user_agent': 'ms-agent',
        'body': {
            'query': 'q'
        }
    }


# ------------------------------------------------------- error handling


def test_auth_error_is_parsed(monkeypatch):
    monkeypatch.setattr(outcrawl_http, 'urlopen', _raise_http(401, AUTH_BODY))
    with pytest.raises(outcrawl_http.OutcrawlHTTPError) as ctx:
        outcrawl_http.post_json('/search', {'query': 'q'}, api_key='bad')
    err = ctx.value
    assert err.status == 401
    assert err.code == 'unauthorized'
    assert err.is_auth and not err.is_quota
    p = WebSearchTool._search_error_payload('outcrawl', err)
    assert p['kind'] == 'auth_failed'


def test_rate_limit_is_quota_with_retry_after(monkeypatch):
    monkeypatch.setattr(
        outcrawl_http, 'urlopen',
        _raise_http(429, {'code': 'rate_limited'}, {'retry-after': '30'}))
    with pytest.raises(outcrawl_http.OutcrawlHTTPError) as ctx:
        outcrawl_http.post_json('/search', {'query': 'q'}, api_key='oc-K')
    assert ctx.value.is_quota
    assert ctx.value.retry_after == 30
    p = WebSearchTool._search_error_payload('outcrawl', ctx.value)
    assert p['kind'] == 'quota_exceeded'


# --------------------------------------------------------------- fetcher


def test_fetcher_returns_markdown_and_metadata(monkeypatch):
    seen = {}

    def fake_post(path, body, *, api_key, timeout=60.0):
        seen.update(path=path, body=body)
        return SCRAPE_RESPONSE

    monkeypatch.setattr('ms_agent.tools.search.outcrawl.fetcher.post_json',
                        fake_post)
    text, meta = OutcrawlScrapeFetcher(api_key='oc-K').fetch(
        'https://example.com/')
    assert seen == {
        'path': '/scrape',
        'body': {
            'url': 'https://example.com/',
            'formats': ['markdown'],
            'onlyMainContent': True
        }
    }
    assert text == '# Example Domain'
    assert meta['fetcher'] == 'outcrawl_scrape'
    assert meta['status_code'] == 200
    assert meta['title'] == 'Example Domain'
    assert 'error' not in meta


def test_fetcher_reports_errors_instead_of_raising(monkeypatch):
    monkeypatch.setattr(outcrawl_http, 'urlopen', _raise_http(401, AUTH_BODY))
    text, meta = OutcrawlScrapeFetcher(api_key='bad').fetch(
        'https://example.com/')
    assert text == ''
    assert 'Outcrawl HTTP 401' in meta['error']


def test_fetcher_without_key_reports_error(no_env_key):
    text, meta = OutcrawlScrapeFetcher().fetch('https://example.com/')
    assert text == ''
    assert 'OUTCRAWL_API_KEY' in meta['error']


# ------------------------------------------------------- real network


@pytest.mark.skipif(
    not os.getenv('OUTCRAWL_API_KEY'),
    reason='OUTCRAWL_API_KEY is required for Outcrawl real-network test.')
def test_outcrawl_search_real():
    engine = get_search_engine('outcrawl')
    request = OutcrawlSearch.build_request_from_args(
        query='ModelScope MS-Agent', num_results=3)
    rows = engine.search(request).to_list()
    assert rows
    assert all(r['url'].startswith('http') for r in rows)


@pytest.mark.skipif(
    not os.getenv('OUTCRAWL_API_KEY'),
    reason='OUTCRAWL_API_KEY is required for Outcrawl real-network test.')
def test_outcrawl_scrape_real():
    fetcher = get_content_fetcher('outcrawl_scrape')
    text, meta = fetcher.fetch('https://example.com/')
    assert 'documentation examples' in text
    assert meta['status_code'] == 200
    assert meta['title'] == 'Example Domain'
