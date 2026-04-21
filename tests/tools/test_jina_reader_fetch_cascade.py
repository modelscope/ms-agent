# Copyright (c) ModelScope Contributors. All rights reserved.
"""Unit tests for Jina → direct HTTP → Playwright cascade in jina_reader."""

import os
import unittest
from unittest.mock import patch

from ms_agent.tools.jina_reader import (
    JinaReaderConfig,
    _parse_scutil_proxy_stdout,
    _scutil_kv_to_urllib_proxies,
    fetch_single_text_with_meta,
)
from ms_agent.tools.search.websearch_tool import JinaContentFetcher, get_content_fetcher

URL = 'https://example.com/article'


class TestScutilProxyParsing(unittest.TestCase):
    """Unit tests for macOS ``scutil --proxy`` → urllib proxy dict."""

    def test_parse_and_build_http_https_proxy(self):
        sample = """
<dictionary> {
  HTTPEnable : 1
  HTTPPort : 7890
  HTTPProxy : 127.0.0.1
  HTTPSEnable : 1
  HTTPSPort : 7890
  HTTPSProxy : 127.0.0.1
}
"""
        kv = _parse_scutil_proxy_stdout(sample)
        self.assertEqual(kv.get('HTTPProxy'), '127.0.0.1')
        proxies = _scutil_kv_to_urllib_proxies(kv)
        self.assertEqual(proxies['http'], 'http://127.0.0.1:7890')
        self.assertEqual(proxies['https'], 'http://127.0.0.1:7890')

    def test_http_only_mirrors_to_https(self):
        kv = {
            'HTTPEnable': '1',
            'HTTPPort': '8888',
            'HTTPProxy': '127.0.0.1',
        }
        proxies = _scutil_kv_to_urllib_proxies(kv)
        self.assertEqual(proxies['https'], 'http://127.0.0.1:8888')

    def test_pac_only_returns_empty(self):
        kv = {
            'ProxyAutoConfigEnable': '1',
            'ProxyAutoConfigURLString': 'http://example.com/proxy.pac',
        }
        self.assertEqual(_scutil_kv_to_urllib_proxies(kv), {})


class TestJinaReaderFetchCascadeMocked(unittest.TestCase):
    """Assert tier triggers and returned text/meta using mocks (no network)."""

    @patch('ms_agent.tools.jina_reader.try_playwright_inner_text')
    @patch('ms_agent.tools.jina_reader._fetch_direct_http_pair')
    @patch('ms_agent.tools.jina_reader._fetch_via_jina')
    def test_jina_hit_skips_direct_and_playwright(self, m_jina, m_direct,
                                                  m_pw):
        m_jina.return_value = 'Jina body content.'
        text, meta = fetch_single_text_with_meta(URL, JinaReaderConfig())
        self.assertEqual(meta['content_source'], 'jina_reader')
        self.assertEqual(text, 'Jina body content.')
        m_direct.assert_not_called()
        m_pw.assert_not_called()

    @patch('ms_agent.tools.jina_reader.try_playwright_inner_text')
    @patch('ms_agent.tools.jina_reader._fetch_direct_http_pair')
    @patch('ms_agent.tools.jina_reader._fetch_via_jina')
    def test_direct_fallback_called_long_plain_skips_playwright(
            self, m_jina, m_direct, m_pw):
        m_jina.return_value = ''
        long_plain = 'word\n' * 120
        m_direct.return_value = (long_plain,
                                 '<html><body><p>x</p></body></html>')
        text, meta = fetch_single_text_with_meta(
            URL,
            JinaReaderConfig(playwright_retry_min_chars=400),
        )
        self.assertEqual(meta['content_source'], 'direct_http_fallback')
        self.assertEqual(text, long_plain.strip())
        m_direct.assert_called_once()
        m_pw.assert_not_called()

    @patch('ms_agent.tools.jina_reader.try_playwright_inner_text')
    @patch('ms_agent.tools.jina_reader._fetch_direct_http_pair')
    @patch('ms_agent.tools.jina_reader._fetch_via_jina')
    def test_short_direct_triggers_playwright_and_prefers_pw_text(
            self, m_jina, m_direct, m_pw):
        m_jina.return_value = ''
        m_direct.return_value = ('short', '<html><body>hi</body></html>')
        pw_body = 'playwright rendered paragraph.\n' * 30
        m_pw.return_value = pw_body
        text, meta = fetch_single_text_with_meta(
            URL,
            JinaReaderConfig(playwright_retry_min_chars=400),
        )
        self.assertEqual(meta['content_source'], 'playwright_fallback')
        self.assertEqual(text, pw_body.strip())
        m_direct.assert_called_once()
        m_pw.assert_called_once()
        args, kwargs = m_pw.call_args
        self.assertEqual(args[0], URL)
        self.assertEqual(args[1], 30_000)
        self.assertEqual(kwargs.get('settle_ms'), 350)

    @patch('ms_agent.tools.jina_reader.try_playwright_inner_text')
    @patch('ms_agent.tools.jina_reader._fetch_direct_http_pair')
    @patch('ms_agent.tools.jina_reader._fetch_via_jina')
    def test_spa_shell_html_triggers_playwright(self, m_jina, m_direct,
                                                m_pw):
        m_jina.return_value = ''
        shell = '<html><body><div id="root"></div></body></html>'
        m_direct.return_value = ('', shell)
        m_pw.return_value = 'hydrated app text ' * 40
        text, meta = fetch_single_text_with_meta(URL, JinaReaderConfig())
        self.assertEqual(meta['content_source'], 'playwright_fallback')
        self.assertIn('hydrated', text)
        m_pw.assert_called_once()

    @patch('ms_agent.tools.jina_reader.try_playwright_inner_text')
    @patch('ms_agent.tools.jina_reader._fetch_direct_http_pair')
    @patch('ms_agent.tools.jina_reader._fetch_via_jina')
    def test_playwright_empty_falls_back_to_direct(self, m_jina, m_direct,
                                                     m_pw):
        m_jina.return_value = ''
        direct_plain = 'tiny'
        m_direct.return_value = (direct_plain, '<html><body>x</body></html>')
        m_pw.return_value = ''
        text, meta = fetch_single_text_with_meta(
            URL,
            JinaReaderConfig(playwright_retry_min_chars=400),
        )
        self.assertEqual(meta['content_source'], 'direct_http_fallback')
        self.assertEqual(text, 'tiny')
        m_pw.assert_called_once()

    @patch('ms_agent.tools.jina_reader.try_playwright_inner_text')
    @patch('ms_agent.tools.jina_reader._fetch_direct_http_pair')
    @patch('ms_agent.tools.jina_reader._fetch_via_jina')
    def test_playwright_disabled_short_still_returns_direct(self, m_jina,
                                                            m_direct, m_pw):
        m_jina.return_value = ''
        m_direct.return_value = ('ab', '<html><body></body></html>')
        text, meta = fetch_single_text_with_meta(
            URL,
            JinaReaderConfig(
                playwright_fetch_fallback=False,
                playwright_retry_min_chars=400,
            ),
        )
        self.assertEqual(meta['content_source'], 'direct_http_fallback')
        self.assertEqual(text, 'ab')
        m_pw.assert_not_called()

    @patch('ms_agent.tools.jina_reader._fetch_via_jina')
    def test_direct_disabled_no_fetch_pair(self, m_jina):
        m_jina.return_value = ''
        with patch(
                'ms_agent.tools.jina_reader._fetch_direct_http_pair'
        ) as m_direct, patch(
                'ms_agent.tools.jina_reader.try_playwright_inner_text'
        ) as m_pw:
            text, meta = fetch_single_text_with_meta(
                URL,
                JinaReaderConfig(direct_fetch_fallback=False),
            )
            self.assertEqual(meta['content_source'], 'none')
            self.assertEqual(text, '')
            m_direct.assert_not_called()
            m_pw.assert_not_called()

    def test_get_content_fetcher_passes_playwright_options(self):
        f = get_content_fetcher(
            'jina_reader',
            timeout=12.0,
            retries=1,
            direct_fetch_fallback=True,
            playwright_fetch_fallback=False,
            playwright_retry_min_chars=99,
            playwright_timeout_ms=5000,
            use_system_proxy=False,
        )
        self.assertIsInstance(f, JinaContentFetcher)
        self.assertFalse(f.config.playwright_fetch_fallback)
        self.assertEqual(f.config.playwright_retry_min_chars, 99)
        self.assertEqual(f.config.playwright_timeout_ms, 5000)
        self.assertFalse(f.config.use_system_proxy)


@unittest.skipUnless(
    os.environ.get('MS_AGENT_FETCH_INTEGRATION') == '1',
    'set MS_AGENT_FETCH_INTEGRATION=1 to run real HTTP / Playwright checks',
)
class TestJinaReaderFetchIntegration(unittest.TestCase):
    """Optional real network / browser checks (off in CI by default)."""

    def test_direct_http_pair_example_com(self):
        from ms_agent.tools.jina_reader import _fetch_direct_http_pair

        plain, raw = _fetch_direct_http_pair('https://example.com/', 20.0)
        self.assertIn('Example', plain)
        self.assertTrue(raw.strip().startswith('<!'))

    def test_playwright_inner_text_example_com(self):
        from ms_agent.tools.fetch_playwright_fallback import (
            try_playwright_inner_text,
        )

        try:
            import playwright  # noqa: F401
        except ImportError:
            self.skipTest('playwright not installed')

        text = try_playwright_inner_text('https://example.com/', 45_000)
        self.assertIn('Example', text)


if __name__ == '__main__':
    unittest.main()
