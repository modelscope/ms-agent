# Copyright (c) ModelScope Contributors. All rights reserved.
"""Tavily's keyless tier, and telling the agent WHY a search failed.

Keyless access (``X-Tavily-Access-Mode: keyless``) exists so the framework can
search on first run with nothing configured. Two facts measured against
api.tavily.com on 2026-08-20 shape these tests:

* a non-empty ``api_key`` in the body OVERRIDES the keyless header — a bogus one
  answers 401 — so the field must be absent, not empty, when going keyless;
* the quota is a small sliding hourly bucket (refill ~1 request/60-90s), so
  running out is an ORDINARY event whose only fix (add an API key) belongs to
  the user. It must therefore reach them, and the old code turned every failure
  into "No search results found."
"""
import json
from io import BytesIO
from urllib.error import HTTPError

import pytest
from ms_agent.tools.search.tavily import http as tavily_http
from ms_agent.tools.search.tavily.schema import TavilySearchRequest
from ms_agent.tools.search.tavily.search import KEYLESS_HEADER, TavilySearch
from ms_agent.tools.search.websearch_tool import WebSearchTool

# The exact 429 envelope api.tavily.com returns once the keyless bucket is dry.
REAL_QUOTA_BODY = {
    'error': {
        'code': 'hourly_cap_reached',
        'message': ('You reached the hourly keyless Tavily limit. To continue '
                    'immediately, pay via x402 agentic payment or sign up at '
                    'https://tavily.com for a Tavily API key.'),
        'next_actions': [],
        'window': 'hour',
        'retry_after_seconds': 62,
    }
}
# Auth failures nest one level deeper than quota ones.
REAL_AUTH_BODY = {'detail': {'error': 'Unauthorized: missing or invalid API key.'}}


class _Hdrs(dict):

    def get(self, key, default=None):
        return dict.get(self, key.lower(), default)


def _raise_http(status, body, headers=None):
    def boom(*args, **kwargs):
        raise HTTPError('https://api.tavily.com/search', status, 'err',
                        _Hdrs(headers or {}),
                        BytesIO(json.dumps(body).encode()))

    return boom


@pytest.fixture()
def no_env_key(monkeypatch):
    monkeypatch.delenv('TAVILY_API_KEY', raising=False)


# --------------------------------------------------------------- body shape

def test_api_key_is_omitted_when_absent():
    """Present-but-empty would be tolerated; absent is the only unambiguous
    shape, since ANY non-empty value makes Tavily validate it instead of
    honouring the keyless header."""
    body = TavilySearchRequest(query='q', max_results=1).to_api_body('')
    assert 'api_key' not in body
    assert body['query'] == 'q'


def test_api_key_is_sent_when_present():
    body = TavilySearchRequest(query='q', max_results=1).to_api_body('tvly-K')
    assert body['api_key'] == 'tvly-K'


# ------------------------------------------------------------ mode selection

def test_missing_key_selects_keyless_instead_of_raising(no_env_key):
    """Regression: this used to raise ValueError, which WebSearchTool.connect()
    caught and logged — leaving an unconfigured install with no web search and
    no explanation."""
    engine = TavilySearch()
    assert engine.keyless is True
    assert engine._headers() == KEYLESS_HEADER


def test_explicit_key_disables_keyless(no_env_key):
    engine = TavilySearch(api_key='tvly-K')
    assert engine.keyless is False
    assert engine._headers() == {}


def test_env_key_disables_keyless(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY', 'tvly-FROM-ENV')
    assert TavilySearch().keyless is False


def test_keyless_header_is_sent_and_key_field_absent(no_env_key, monkeypatch):
    seen = {}

    def fake_post(url, body, *, timeout=120.0, headers=None):
        seen['body'] = body
        seen['headers'] = headers
        return {'results': []}

    monkeypatch.setattr('ms_agent.tools.search.tavily.search.post_json',
                        fake_post)
    TavilySearch().search(TavilySearchRequest(query='q', max_results=1))
    assert seen['headers'] == KEYLESS_HEADER
    assert 'api_key' not in seen['body']


# ------------------------------------------------------- error classification

def test_quota_error_is_parsed_with_code_and_retry_after(monkeypatch):
    monkeypatch.setattr(
        tavily_http, 'urlopen',
        _raise_http(429, REAL_QUOTA_BODY, {'retry-after': '62'}))
    with pytest.raises(tavily_http.TavilyHTTPError) as ctx:
        tavily_http.post_json('https://api.tavily.com/search', {'query': 'q'})
    err = ctx.value
    assert err.status == 429
    assert err.code == 'hourly_cap_reached'
    assert err.retry_after == 62
    assert err.is_quota and not err.is_auth


def test_auth_error_is_recognised_through_the_detail_envelope(monkeypatch):
    monkeypatch.setattr(tavily_http, 'urlopen',
                        _raise_http(401, REAL_AUTH_BODY))
    with pytest.raises(tavily_http.TavilyHTTPError) as ctx:
        tavily_http.post_json('https://api.tavily.com/search', {'query': 'q'})
    assert ctx.value.is_auth and not ctx.value.is_quota


def test_retry_after_falls_back_to_the_header(monkeypatch):
    """Some responses carry the header but no retry_after_seconds field."""
    monkeypatch.setattr(
        tavily_http, 'urlopen',
        _raise_http(429, {'error': {'code': 'hourly_cap_reached'}},
                    {'retry-after': '90'}))
    with pytest.raises(tavily_http.TavilyHTTPError) as ctx:
        tavily_http.post_json('https://api.tavily.com/search', {'query': 'q'})
    assert ctx.value.retry_after == 90


# ------------------------------------------------ what the MODEL is told

def _payload(status, code='', retry_after=None):
    err = tavily_http.TavilyHTTPError(
        'boom', status=status, code=code, retry_after=retry_after)
    return WebSearchTool._search_error_payload('tavily', err)


def test_quota_payload_names_the_remedy_and_forbids_no_results():
    p = _payload(429, 'hourly_cap_reached', 62)
    assert p['kind'] == 'quota_exceeded'
    assert p['retry_after_seconds'] == 62
    assert 'API key' in p['remedy']
    # The whole point: the model must not narrate this as an empty result set.
    assert 'no results found' in p['remedy'].lower()


def test_auth_payload_points_at_the_key():
    p = _payload(401)
    assert p['kind'] == 'auth_failed'
    assert 'key' in p['remedy'].lower()


def test_transport_failure_is_neither_quota_nor_auth():
    err = tavily_http.TavilyHTTPError('Tavily network error: timed out')
    p = WebSearchTool._search_error_payload('tavily', err)
    assert p['kind'] == 'search_failed'
    assert 'empty result' in p['remedy']
