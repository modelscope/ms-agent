# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Optional headless Chromium fetch for URLs where Jina + direct HTTP yield empty
or obviously client-rendered shells.

Requires: ``pip install playwright`` and ``playwright install chromium``.
If Playwright is not installed, helpers return empty string without raising.

Performance: Playwright ``Browser`` must be used from the creating thread only.
We keep **one browser per thread** (e.g. each ``ThreadPoolExecutor`` worker) and
reuse it across URLs instead of launching Chromium for every fetch.
"""
from __future__ import annotations

import atexit
import os
import re
import threading
from typing import Dict, List, Tuple

from ms_agent.utils.logger import get_logger

logger = get_logger()

_MAX_INNER_TEXT_CHARS = 100_000

_tls = threading.local()
_registry_lock = threading.Lock()
# thread_id -> (sync_playwright handle, Browser) for atexit cleanup
_pw_by_thread: Dict[int, Tuple[object, object]] = {}


def _chromium_launch_args() -> List[str]:
    args: List[str] = [
        '--disable-extensions',
        '--blink-settings=imagesEnabled=false',
    ]
    if os.getenv('MS_AGENT_PLAYWRIGHT_NO_SANDBOX', '').lower() in (
            '1',
            'true',
            'yes',
    ):
        args.extend(('--no-sandbox', '--disable-setuid-sandbox'))
    return args


def _invalidate_thread_playwright_unlocked() -> None:
    """Drop thread-local Playwright; caller must hold no registry lock if mutating _pw_by_thread."""
    tid = threading.get_ident()
    pw = getattr(_tls, 'pw', None)
    br = getattr(_tls, 'browser', None)
    _tls.pw = None
    _tls.browser = None
    with _registry_lock:
        _pw_by_thread.pop(tid, None)
    if br is not None:
        try:
            br.close()
        except Exception:
            pass
    if pw is not None:
        try:
            pw.stop()
        except Exception:
            pass


def _atexit_close_all_playwright() -> None:
    with _registry_lock:
        items = list(_pw_by_thread.values())
        _pw_by_thread.clear()
    for pw, browser in items:
        try:
            browser.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass


atexit.register(_atexit_close_all_playwright)


def _thread_browser() -> object:
    """Return a Chromium ``Browser`` for this thread, creating it lazily."""
    br = getattr(_tls, 'browser', None)
    if br is not None:
        try:
            if br.is_connected():
                return br
        except Exception:
            pass
        _invalidate_thread_playwright_unlocked()
        br = None

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.debug(
            'playwright is not installed; skip headless fetch. '
            'Install with: pip install playwright && playwright install chromium')
        raise RuntimeError('playwright not installed') from None

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=_chromium_launch_args(),
    )
    _tls.pw = pw
    _tls.browser = browser
    with _registry_lock:
        _pw_by_thread[threading.get_ident()] = (pw, browser)
    return browser


def try_playwright_inner_text(
    url: str,
    timeout_ms: int,
    *,
    settle_ms: int = 350,
) -> str:
    """
    Load URL in headless Chromium and return ``document.body.innerText``.

    Reuses one browser per thread. Returns empty string on missing dependency,
    timeout, or navigation error.
    """
    if not url.startswith(('http://', 'https://')):
        return ''
    settle_ms = max(0, int(settle_ms))
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        logger.debug(
            'playwright is not installed; skip headless fetch. '
            'Install with: pip install playwright && playwright install chromium')
        return ''

    text = ''
    try:
        browser = _thread_browser()
        page = browser.new_page()
        try:
            page.set_default_timeout(timeout_ms)
            page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)
            if settle_ms:
                page.wait_for_timeout(settle_ms)
            raw = page.evaluate(
                """() => {
                    const b = document.body;
                    if (!b) return '';
                    return b.innerText || '';
                }"""
            )
            if isinstance(raw, str):
                text = raw[:_MAX_INNER_TEXT_CHARS]
        finally:
            try:
                page.close()
            except Exception:
                pass
    except RuntimeError:
        return ''
    except Exception as e:
        logger.debug(f'Playwright fetch failed for {url[:80]!r}: {e}')
        try:
            _invalidate_thread_playwright_unlocked()
        except Exception:
            pass
        return ''

    return text


def looks_like_spa_shell_html(raw_html: str) -> bool:
    """Heuristic: HTML suggests JS-only app or empty mount root."""
    if not raw_html or len(raw_html) < 80:
        return False
    low = raw_html.lower()
    if any(
            x in low
            for x in ('enable javascript', 'javascript is required',
                      'you need to enable javascript')):
        return True
    if re.search(r'<div[^>]+\bid=["\']root["\'][^>]*>\s*</div>', low):
        return True
    if re.search(r'<div[^>]+\bid=["\']app["\'][^>]*>\s*</div>', low):
        return True
    return False
