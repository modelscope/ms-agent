# Copyright (c) ModelScope Contributors. All rights reserved.
import socket
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from ms_agent.tools import jina_reader
from ms_agent.tools.search.websearch_tool import JinaContentFetcher
from ms_agent.tools.url_safety import (_SafeRedirectHandler,
                                       is_safe_public_url, safe_urlopen)


def _addrinfo(*addresses):
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '',
             (address, 0)) for address in addresses]


@pytest.mark.parametrize(
    'url',
    [
        'http://127.0.0.1/',
        'http://10.0.0.1/',
        'http://192.168.1.1/',
        'http://169.254.169.254/latest/meta-data/',
        'http://100.100.100.200/',
        'http://0.0.0.0/',
        'http://[::1]/',
        'http://[fe80::1]/',
        'http://[::ffff:127.0.0.1]/',
        'http://224.0.0.1/',
        'http://localhost/',
        'http://service.internal/',
        'ftp://example.com/file',
        'file:///etc/passwd',
        'http:///missing-host',
        'http://example.com:not-a-port/',
    ],
)
def test_rejects_non_public_literal_urls(url):
    assert not is_safe_public_url(url)


@pytest.mark.parametrize(
    'address',
    [
        '10.0.0.1',
        '192.168.1.1',
        '169.254.169.254',
        '100.100.100.200',
        '127.0.0.1',
        '::1',
        'fe80::1',
        '::ffff:127.0.0.1',
        '224.0.0.1',
        '0.0.0.0',
    ],
)
def test_rejects_hostnames_resolving_to_non_public(address):
    with patch(
            'ms_agent.tools.url_safety.socket.getaddrinfo',
            return_value=_addrinfo(address)):
        assert not is_safe_public_url('https://example.com/page')


def test_rejects_mixed_public_and_private_dns_answers():
    with patch(
            'ms_agent.tools.url_safety.socket.getaddrinfo',
            return_value=_addrinfo('93.184.216.34', '10.0.0.1')):
        assert not is_safe_public_url('https://example.com/')


def test_allows_public_hostname():
    with patch(
            'ms_agent.tools.url_safety.socket.getaddrinfo',
            return_value=_addrinfo('93.184.216.34')):
        assert is_safe_public_url('https://example.com/path?q=1')


def test_rejects_dns_failure():
    with patch(
            'ms_agent.tools.url_safety.socket.getaddrinfo',
            side_effect=socket.gaierror):
        assert not is_safe_public_url('https://example.com/')


def test_safe_urlopen_blocks_non_public_initial_url():
    with pytest.raises(ValueError, match='non-public URL'):
        safe_urlopen(Request('http://127.0.0.1/'), timeout=1)


def test_redirect_handler_blocks_non_public_target():
    handler = _SafeRedirectHandler()
    with patch(
            'ms_agent.tools.url_safety.is_safe_public_url',
            return_value=False):
        with pytest.raises(HTTPError):
            handler.redirect_request(
                Request('https://example.com/'),
                None,
                302,
                'Found',
                Message(),
                'http://169.254.169.254/',
            )


def test_redirect_handler_allows_public_target():
    handler = _SafeRedirectHandler()
    with patch(
            'ms_agent.tools.url_safety.is_safe_public_url',
            return_value=True):
        redirected = handler.redirect_request(
            Request('https://example.com/'),
            None,
            302,
            'Found',
            Message(),
            'https://example.org/',
        )
    assert redirected.full_url == 'https://example.org/'


def test_fetch_single_text_blocks_before_jina(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError('Jina must not be called for a non-public URL')

    monkeypatch.setattr(jina_reader, '_fetch_via_jina', fail)
    text, meta = jina_reader.fetch_single_text_with_meta(
        'http://127.0.0.1/',
        jina_reader.JinaReaderConfig(),
    )
    assert text == ''
    assert meta['content_source'] == 'blocked'
    assert meta['fetch_error'] == 'blocked_non_public_url'


def test_jina_content_fetcher_blocks_non_public():
    content, meta = JinaContentFetcher().fetch('http://127.0.0.1/')
    assert content == ''
    assert meta['content_source'] == 'blocked'
    assert meta['fetch_error'] == 'blocked_non_public_url'


def test_playwright_blocks_non_public_before_import():
    from ms_agent.tools.fetch_playwright_fallback import try_playwright_inner_text

    assert try_playwright_inner_text('http://127.0.0.1/', 1000) == ''
