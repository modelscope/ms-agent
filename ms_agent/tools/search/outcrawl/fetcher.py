# Copyright (c) ModelScope Contributors. All rights reserved.
"""Outcrawl Scrape API as ContentFetcher (for fetch_page / URL fetch)."""
import os
import time
from typing import Any, Dict, Optional, Tuple

from ms_agent.tools.search.outcrawl.http import post_json
from ms_agent.utils.logger import get_logger

logger = get_logger()


class OutcrawlScrapeFetcher:
    """Fetch page text as markdown via Outcrawl POST /v1/scrape."""

    def __init__(self,
                 api_key: Optional[str] = None,
                 *,
                 only_main_content: bool = True,
                 timeout: float = 45.0):
        self._api_key = api_key or os.getenv('OUTCRAWL_API_KEY') or ''
        self._only_main_content = bool(only_main_content)
        self._timeout = max(1.0, float(timeout))

    def fetch(self, url: str) -> Tuple[str, Dict[str, Any]]:
        meta: Dict[str, Any] = {
            'fetcher': 'outcrawl_scrape',
            'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
        if not self._api_key:
            meta['error'] = 'OUTCRAWL_API_KEY is not set'
            return '', meta
        body = {
            'url': url,
            'formats': ['markdown'],
            'onlyMainContent': self._only_main_content,
        }
        try:
            data = post_json(
                '/scrape', body, api_key=self._api_key, timeout=self._timeout)
        except Exception as e:
            logger.warning(f'Outcrawl scrape failed for {url[:80]}: {e}')
            meta['error'] = str(e)
            return '', meta

        text = (data.get('markdown') or '').strip()
        metadata = data.get('metadata') or {}
        meta.update({
            'status_code': data.get('statusCode'),
            'title': metadata.get('title'),
            'outcrawl_usage': data.get('usage'),
        })
        if not text:
            meta['error'] = 'Outcrawl returned no markdown'
        return text, meta
