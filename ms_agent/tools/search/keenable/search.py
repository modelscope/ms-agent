# Copyright (c) ModelScope Contributors. All rights reserved.
"""Keenable search engine (stdlib HTTP only).

The API key is optional. With a key, requests go to ``POST /v1/search`` with an
``X-API-Key`` header. Without one they go to ``POST /v1/search/public``, which
Keenable rate limits per IP address (1,000 requests per hour, 10 per second)
and logs together with the query and IP address
(https://docs.keenable.ai/rate-limits). Both need an ``X-Keenable-Title``
header naming the application.
"""
import json
import os
from typing import TYPE_CHECKING, Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ms_agent.tools.search.keenable.schema import (KeenableSearchRequest,
                                                   KeenableSearchResult)
from ms_agent.tools.search.search_base import SearchEngine, SearchEngineType
from ms_agent.tools.search.tavily.http import _ssl_context
from ms_agent.utils.logger import get_logger

if TYPE_CHECKING:
    from ms_agent.llm.utils import Tool

logger = get_logger()

KEENABLE_SEARCH_URL = 'https://api.keenable.ai/v1/search'
KEENABLE_PUBLIC_SEARCH_URL = 'https://api.keenable.ai/v1/search/public'
KEENABLE_APP_TITLE = 'ms-agent'


class KeenableHTTPError(RuntimeError):
    """A failed Keenable call with the fields WebSearchTool reports.

    ``status`` is the HTTP code (None for transport failures), ``code`` is
    Keenable's machine-readable ``code`` (e.g. ``public_rate_limit_hourly``)
    and ``retry_after`` the seconds from ``Retry-After`` when present.
    """

    def __init__(self,
                 message: str,
                 *,
                 status: Optional[int] = None,
                 code: str = '',
                 retry_after: Optional[int] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.retry_after = retry_after

    @property
    def is_quota(self) -> bool:
        return self.status == 429

    @property
    def is_auth(self) -> bool:
        return self.status in (401, 403)


def _error_from(e: HTTPError) -> KeenableHTTPError:
    detail: Dict[str, Any] = {}
    try:
        raw = e.read().decode('utf-8', errors='replace')
        parsed = json.loads(raw) if raw else {}
        if isinstance(parsed, dict):
            detail = parsed
    except Exception:
        pass
    retry_after = None
    ra = detail.get('retry_after_seconds')
    if ra is None:
        try:
            ra = e.headers.get('retry-after')
        except Exception:
            ra = None
    try:
        retry_after = int(float(ra)) if ra is not None else None
    except (TypeError, ValueError):
        retry_after = None
    message = str(detail.get('message') or detail.get('error') or e.reason)
    return KeenableHTTPError(
        f'Keenable HTTP {e.code}: {message}',
        status=e.code,
        code=str(detail.get('code') or ''),
        retry_after=retry_after)


class KeenableSearch(SearchEngine):
    """Keenable Search API, keyless by default, keyed when a key is set."""

    engine_type = SearchEngineType.KEENABLE

    def __init__(self,
                 api_key: Optional[str] = None,
                 request_timeout: float = 30.0):
        # No key is a supported mode: the keyless endpoint serves the same
        # result shape, so a fresh install can search with nothing configured.
        self._api_key = api_key or os.getenv('KEENABLE_API_KEY') or ''
        self._request_timeout = float(request_timeout)

    @property
    def keyless(self) -> bool:
        return not self._api_key

    def _url_and_headers(self) -> tuple:
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-Keenable-Title': KEENABLE_APP_TITLE,
        }
        if self.keyless:
            return KEENABLE_PUBLIC_SEARCH_URL, headers
        headers['X-API-Key'] = self._api_key
        return KEENABLE_SEARCH_URL, headers

    def search(self,
               search_request: KeenableSearchRequest) -> KeenableSearchResult:
        body = search_request.to_api_body()
        url, headers = self._url_and_headers()
        req = Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
            method='POST',
            headers=headers)
        try:
            with urlopen(
                    req, timeout=self._request_timeout,
                    context=_ssl_context()) as resp:
                raw = resp.read().decode('utf-8', errors='replace')
        except HTTPError as e:
            raise _error_from(e) from None
        except URLError as e:
            raise KeenableHTTPError(
                f'Keenable network error: {e.reason}') from None
        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            raise KeenableHTTPError(
                'Keenable returned an invalid response body') from None
        arguments = dict(body)
        arguments['access_mode'] = 'keyless' if self.keyless else 'api_key'
        return KeenableSearchResult(
            query=search_request.query,
            arguments=arguments,
            response=data if isinstance(data, dict) else {},
        )

    @classmethod
    def get_tool_definition(cls, server_name: str = 'web_search') -> 'Tool':
        from ms_agent.llm.utils import Tool
        return Tool(
            tool_name=cls.get_tool_name(),
            server_name=server_name,
            description=(
                'Search the web using Keenable, a search engine built for AI '
                'agents. Returns ranked results with titles, URLs, publish '
                'dates and the page text that matches the query. Describe the '
                'ideal page in natural language rather than listing keywords.'
            ),
            parameters={
                'type': 'object',
                'properties': {
                    'query': {
                        'type': 'string',
                        'description': 'Search query.',
                    },
                    'num_results': {
                        'type': 'integer',
                        'minimum': 1,
                        'maximum': 50,
                        'description': 'Max results. Default 10.',
                    },
                },
                'required': ['query'],
            },
        )

    @classmethod
    def build_request_from_args(cls, **kwargs: Any) -> KeenableSearchRequest:
        num = kwargs.get('num_results', kwargs.get('max_results', 10))
        try:
            num = int(num)
        except (TypeError, ValueError):
            num = 10
        return KeenableSearchRequest(query=kwargs['query'], num_results=num)
