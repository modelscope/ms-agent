# Copyright (c) ModelScope Contributors. All rights reserved.
"""Tavily Extract API as ContentFetcher (replaces Jina for fetch_page / URL fetch)."""
import os
import time
from typing import Any, Dict, Optional, Tuple

from ms_agent.tools.search.tavily.http import post_json
from ms_agent.utils.logger import get_logger

logger = get_logger()

TAVILY_EXTRACT_URL = 'https://api.tavily.com/extract'


class TavilyExtractFetcher:
    """
    Fetch page text via Tavily POST /extract.

    Uses ``extract_depth=advanced`` and ``format=markdown`` by default for
    richest structured text (tables, etc., when available).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        extract_depth: str = 'advanced',
        format: str = 'markdown',
        timeout: float = 45.0,
        chunks_per_source: int = 3,
        include_images: bool = False,
        include_favicon: bool = False,
        include_usage: bool = False,
    ):
        key = api_key or os.getenv('TAVILY_API_KEY')
        if not key:
            raise ValueError(
                'TAVILY_API_KEY required for tavily_extract fetcher')
        self._api_key = key
        self._extract_depth = extract_depth
        self._format = format
        self._timeout = max(1.0, min(60.0, float(timeout)))
        self._chunks_per_source = max(1, min(5, int(chunks_per_source)))
        self._include_images = include_images
        self._include_favicon = include_favicon
        self._include_usage = include_usage

    def fetch(self,
              url: str,
              query: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        """
        Extract one URL. Optional ``query`` enables chunk reranking (more relevant raw_content).
        """
        body: Dict[str, Any] = {
            'api_key': self._api_key,
            'urls': [url],
            'extract_depth': self._extract_depth,
            'format': self._format,
            'timeout': self._timeout,
            'include_images': self._include_images,
            'include_favicon': self._include_favicon,
            'include_usage': self._include_usage,
        }
        if query:
            body['query'] = query
            body['chunks_per_source'] = self._chunks_per_source

        try:
            data = post_json(
                TAVILY_EXTRACT_URL, body, timeout=self._timeout + 30.0)
        except Exception as e:
            logger.warning(f'Tavily extract failed for {url[:80]}: {e}')
            return '', {
                'fetcher': 'tavily_extract',
                'error': str(e),
                'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            }

        results = data.get('results') or []
        text = ''
        if results:
            text = (results[0].get('raw_content') or '').strip()
        meta: Dict[str, Any] = {
            'fetcher': 'tavily_extract',
            'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'tavily_response_time': data.get('response_time'),
            'tavily_usage': data.get('usage'),
            'tavily_request_id': data.get('request_id'),
        }
        failed = data.get('failed_results') or []
        if failed and not text:
            err = failed[0].get('error', 'unknown')
            meta['error'] = err
        return text, meta
