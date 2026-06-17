import asyncio
import html as html_module
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from ms_agent.tools.fetch_playwright_fallback import (
    looks_like_spa_shell_html, try_playwright_inner_text)
from ms_agent.utils.logger import get_logger

logger = get_logger()

DEFAULT_HEADERS: Dict[str, str] = {
    'User-Agent':
    'Mozilla/5.0 (compatible; ms-agent/1.0; +https://example.com)',
    'Accept': 'text/plain; charset=utf-8',
    'Accept-Language': 'en-US,en;q=0.9',
}

# Cap body size for direct HTTP fallback (same order of magnitude as MAX_FETCH_CHARS).
_MAX_DIRECT_RESPONSE_BYTES = 10 * 1024 * 1024

_DIRECT_FETCH_HEADERS: Dict[str, str] = {
    'User-Agent': DEFAULT_HEADERS['User-Agent'],
    'Accept':
    'text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7',
    'Accept-Language': DEFAULT_HEADERS['Accept-Language'],
}


@dataclass
class JinaReaderConfig:
    base_endpoint: str = 'https://r.jina.ai/'
    timeout: float = 45.0
    retries: int = 3
    backoff_base: float = 0.8
    backoff_max: float = 8.0
    headers: Dict[str,
                  str] = field(default_factory=lambda: DEFAULT_HEADERS.copy())
    # When Jina Reader returns empty after retries, try HTTP GET on the target URL.
    direct_fetch_fallback: bool = True
    # Tier 2 (urllib): shorter than Jina timeout — fail fast on slow origins.
    direct_fetch_timeout: float = 15.0
    # Tier 3: headless Chromium when direct body is empty/short or looks like a JS shell.
    playwright_fetch_fallback: bool = True
    playwright_retry_min_chars: int = 400
    playwright_timeout_ms: int = 30_000
    # After domcontentloaded, brief wait for client hydration (lower = faster).
    playwright_settle_ms: int = 350


def _build_reader_url(target_url: str, base_endpoint: str) -> str:
    encoded_target = quote(target_url, safe=":/?&=%#@!$'*+,;[]()")
    base = base_endpoint if base_endpoint.endswith(
        '/') else f'{base_endpoint}/'
    return f'{base}{encoded_target}'


def _postprocess_text(raw_text: str) -> str:
    """
    Lightweight cleanup suitable for LLM consumption.
    - Normalize line breaks
    - Collapse excessive blank lines
    - Trim leading/trailing whitespace
    """
    if not raw_text:
        return ''
    text = raw_text.replace('\r\n', '\n').replace('\r', '\n')
    # Collapse 3+ consecutive blank lines down to 2
    while '\n\n\n' in text:
        text = text.replace('\n\n\n', '\n\n')
    return text.strip()


def _is_direct_http_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        if not parsed.netloc:
            return False
        return True
    except Exception:
        return False


def _html_to_plaintext(html: str) -> str:
    """Best-effort HTML → text without extra dependencies."""
    text = re.sub(r'(?is)<script[^>]*>.*?</script>', ' ', html)
    text = re.sub(r'(?is)<style[^>]*>.*?</style>', ' ', text)
    text = re.sub(r'(?is)<noscript[^>]*>.*?</noscript>', ' ', text)
    text = re.sub(
        r'(?i)</(p|div|tr|th|td|li|h[1-6]|section|article|header|footer|br)\s*>',
        '\n',
        text,
    )
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html_module.unescape(text)
    text = re.sub(r'[ \t\f\v]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# Snippet size for SPA heuristics (avoid holding multi‑MB strings in memory).
_DIRECT_HTML_HEURISTIC_CAP = 120_000


def _fetch_direct_http_pair(url: str, timeout: float) -> Tuple[str, str]:
    """
    Fetch the target URL over HTTP(S) without Jina.

    Returns:
        (plaintext, raw_html_snippet) — ``raw_html_snippet`` is non-empty only when
        the response was treated as HTML (used for shell / length heuristics).
    """
    if not _is_direct_http_allowed(url):
        return '', ''
    try:
        req = Request(url, headers=_DIRECT_FETCH_HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read(_MAX_DIRECT_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_DIRECT_RESPONSE_BYTES:
                raw = raw[:_MAX_DIRECT_RESPONSE_BYTES]
            charset = resp.headers.get_content_charset() or 'utf-8'
            content_type = (resp.headers.get('Content-Type') or '').lower()
        content_type_main = content_type.split(';')[0].strip()
        text = raw.decode(charset, errors='replace')
        if 'html' in content_type_main or text.lstrip().lower().startswith(
                '<!doctype') or '<html' in text[:4000].lower():
            snippet = text[:_DIRECT_HTML_HEURISTIC_CAP]
            return _html_to_plaintext(text), snippet
        return text, ''
    except Exception as e:
        logger.debug(f'Direct HTTP fallback failed for {url!r}: {e}')
        return '', ''


def _should_try_playwright_after_direct(plain: str, raw_html: str,
                                        min_chars: int) -> bool:
    """Whether tier-3 headless fetch is worth attempting."""
    p = plain.strip()
    if raw_html:
        if looks_like_spa_shell_html(raw_html):
            return True
        if len(p) < min_chars:
            return True
        return False
    return not bool(p)


def _fetch_via_jina(url: str, config: JinaReaderConfig) -> str:
    """Jina Reader only; returns empty string on failure."""
    request_url = _build_reader_url(url, config.base_endpoint)
    attempt = 0
    while True:
        attempt += 1
        try:
            req = Request(request_url, headers=config.headers)
            with urlopen(req, timeout=config.timeout) as resp:
                data = resp.read()
                return data.decode('utf-8', errors='replace')
        except HTTPError as e:
            status = getattr(e, 'code', None)
            if status in (429, 500, 502, 503,
                          504) and attempt <= config.retries:
                sleep_s = min(config.backoff_max,
                              config.backoff_base * (2**(attempt - 1)))
                sleep_s *= random.uniform(0.7, 1.4)
                time.sleep(sleep_s)
                continue
            return ''
        except URLError:
            if attempt <= config.retries:
                sleep_s = min(config.backoff_max,
                              config.backoff_base * (2**(attempt - 1)))
                sleep_s *= random.uniform(0.7, 1.4)
                time.sleep(sleep_s)
                continue
            return ''
        except Exception:
            if attempt <= config.retries:
                sleep_s = min(config.backoff_max,
                              config.backoff_base * (2**(attempt - 1)))
                sleep_s *= random.uniform(0.7, 1.4)
                time.sleep(sleep_s)
                continue
            return ''


def fetch_single_text_with_meta(
        url: str, config: JinaReaderConfig) -> Tuple[str, Dict[str, Any]]:
    """
    Tiered fetch: Jina Reader → direct HTTP → optional Playwright (empty / short / SPA shell).

    Returns:
        (text, meta) where ``meta['content_source']`` is one of:
        ``jina_reader`` | ``direct_http_fallback`` | ``playwright_fallback`` | ``none``.
    """
    jina_raw = _fetch_via_jina(url, config)
    jina_text = _postprocess_text(jina_raw)
    if jina_text:
        return jina_text, {'content_source': 'jina_reader'}
    if not config.direct_fetch_fallback:
        return '', {'content_source': 'none'}
    d_timeout = (
        float(config.timeout) if float(config.direct_fetch_timeout or 0) <= 0
        else float(config.direct_fetch_timeout))
    direct_plain, raw_html = _fetch_direct_http_pair(url, d_timeout)
    direct_text = _postprocess_text(direct_plain)

    try_playwright = (
        bool(config.playwright_fetch_fallback) and _is_direct_http_allowed(url)
        and _should_try_playwright_after_direct(
            direct_text, raw_html, config.playwright_retry_min_chars))

    if try_playwright:
        pw_text = _postprocess_text(
            try_playwright_inner_text(
                url,
                int(config.playwright_timeout_ms),
                settle_ms=int(config.playwright_settle_ms),
            ))
        if pw_text.strip():
            logger.info(
                'Using headless Chromium fallback after Jina/direct HTTP '
                f'(url prefix): {url[:80]}')
            return pw_text, {'content_source': 'playwright_fallback'}

    if direct_text:
        logger.info(
            'Jina Reader returned no body for URL; using direct HTTP fallback '
            f'(url prefix): {url[:80]}')
        return direct_text, {'content_source': 'direct_http_fallback'}
    return '', {'content_source': 'none'}


def fetch_single_text(url: str, config: JinaReaderConfig) -> str:
    """
    Synchronous fetch of a single URL via Jina Reader with retry/backoff,
    then optional direct HTTP fallback when Jina yields empty.
    """
    text, _meta = fetch_single_text_with_meta(url, config)
    return text


async def fetch_texts_via_jina(
        urls: List[str],
        config: Optional[JinaReaderConfig] = None,
        semaphore: Optional[asyncio.Semaphore] = None,
        executor: Optional[ThreadPoolExecutor] = None) -> List[str]:
    """
    Asynchronously fetch a list of URLs via Jina Reader.
    Allows caller-provided concurrency controls (semaphore/executor) to integrate with pipeline resource management.
    """
    if not urls:
        return []
    cfg = config or JinaReaderConfig()
    loop = asyncio.get_event_loop()

    local_sem = semaphore or asyncio.Semaphore(8)

    async def _bound(u: str) -> str:
        async with local_sem:
            return await loop.run_in_executor(executor, fetch_single_text, u,
                                              cfg)

    tasks = [_bound(u) for u in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    texts: List[str] = []
    for r in results:
        if isinstance(r, Exception):
            continue
        if isinstance(r, str) and r.strip():
            texts.append(r)
    return texts


if __name__ == '__main__':
    urls = [
        'https://arxiv.org/pdf/2408.09869',
        'https://github.com/modelscope/evalscope',
        'https://www.news.cn/talking/20250530/691e47a5d1a24c82bfa2371d1af40630/c.html',
    ]
    texts = asyncio.run(fetch_texts_via_jina(urls))
    for text in texts:
        print(text)
        print('-' * 100)
