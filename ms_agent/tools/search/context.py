# Copyright (c) ModelScope Contributors. All rights reserved.
"""Context search through the native search-engine contract."""
import httpx
import ipaddress
import os
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from ms_agent.tools.search.search_base import (BaseResult, SearchEngine,
                                               SearchEngineType, SearchRequest,
                                               SearchResponse, SearchResult)


class ContextSearchRequest(SearchRequest):

    def to_dict(self) -> Dict[str, Any]:
        if not isinstance(self.query,
                          str) or not 1 <= len(self.query.strip()) <= 500:
            raise ValueError('Context query must contain 1 to 500 characters.')
        if type(self.num_results
                ) is not int or not 1 <= self.num_results <= 100:
            raise ValueError(
                'Context num_results must be an integer from 1 to 100.')
        return {
            'query': self.query.strip(),
            'numResults': self.num_results,
            'highlightsOptions': {
                'enabled': True,
                'maxCharacters': 4000
            },
            'timeoutOpts': {
                'milliseconds': 29000,
                'behavior': 'fail'
            },
        }


class ContextSearchResult(SearchResult):

    def __init__(self, query: str, arguments: Dict[str, Any], response: Any):
        super().__init__(query, arguments, response)
        self.response = self._process_results()

    def _process_results(self) -> SearchResponse:
        payload = self.response
        if not isinstance(payload, dict) or type(
                payload.get('partial', False)) is not bool:
            raise ValueError('Context returned an invalid response.')
        if payload.get('partial'):
            raise ValueError(
                'Context returned incomplete search results. Try again later.')
        rows = payload.get('results')
        if not isinstance(rows, list):
            raise ValueError('Context returned invalid search results.')
        results = []
        for row in rows[:self.arguments['numResults']]:
            if not isinstance(row, dict) or not isinstance(
                    row.get('url'), str):
                raise ValueError('Context returned an invalid source.')
            url = row['url']
            parsed = urlsplit(url)
            if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                    or parsed.username is not None
                    or parsed.password is not None
                    or parsed.hostname.rstrip('.').lower() == 'localhost'):
                raise ValueError('Context returned an invalid source URL.')
            try:
                address = ipaddress.ip_address(parsed.hostname)
            except ValueError:
                address = None
            if address is not None and not address.is_global:
                raise ValueError('Context returned a nonpublic source URL.')
            title = row.get('title')
            description = row.get('description')
            if any(
                    value is not None and not isinstance(value, str)
                    for value in (title, description)):
                raise ValueError('Context returned invalid source text.')
            passages = []
            highlights = row.get('highlights')
            if highlights is not None:
                if not isinstance(highlights, dict) or not isinstance(
                        highlights.get('code'), str):
                    raise ValueError('Context returned invalid Highlights.')
                values = highlights.get('highlights')
                if values is not None:
                    if not isinstance(values, list) or any(
                            not isinstance(value, str) for value in values):
                        raise ValueError(
                            'Context returned invalid Highlights.')
                    if highlights['code'] == 'SUCCESS':
                        passages = [
                            value.strip() for value in values if value.strip()
                        ]
            summary = ('\n'.join(passages)[:4000] if passages else
                       '[Highlights unavailable; search description only] ' +
                       (description or ''))
            results.append(
                BaseResult(
                    url=url,
                    id=url,
                    title=title or 'Untitled',
                    highlights=passages or None,
                    summary=summary))
        return SearchResponse(results=results)


class ContextSearchError(RuntimeError):
    """Safe failure metadata consumed by the native tool's error formatter."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status
        self.is_auth = status in (401, 403)


class ContextSearch(SearchEngine):
    """Search with query-relevant Highlights; page fetching stays a separate tool option."""

    engine_type = SearchEngineType.CONTEXT

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.getenv('CONTEXT_DEV_API_KEY')
        if not isinstance(key, str) or not key.strip():
            raise ValueError(
                'Context requires CONTEXT_DEV_API_KEY or context_api_key.')
        self._api_key = key.strip()

    @classmethod
    def build_request_from_args(cls, **kwargs: Any) -> ContextSearchRequest:
        return ContextSearchRequest(
            query=kwargs.get('query'),
            num_results=kwargs.get('num_results', 10))

    def search(self,
               search_request: ContextSearchRequest) -> ContextSearchResult:
        body = search_request.to_dict()
        failure = None
        try:
            with httpx.Client(timeout=30.0, follow_redirects=False) as client:
                response = client.post(
                    'https://api.context.dev/v1/web/search',
                    json=body,
                    headers={'Authorization': 'Bearer ' + self._api_key})
                if not 200 <= response.status_code < 300:
                    failure = ContextSearchError(
                        'Context search request failed (HTTP %s).'
                        % response.status_code,
                        status=response.status_code)
                else:
                    result = ContextSearchResult(search_request.query, body,
                                                 response.json())
        except httpx.HTTPError:
            failure = ContextSearchError(
                'Context search could not complete. Check connectivity and try again.'
            )
        except (ValueError, TypeError):
            failure = ContextSearchError(
                'Context returned an invalid or incomplete search response.')
        # Raise outside the handler: vendor diagnostics must not survive in an exception context.
        if failure is not None:
            raise failure
        return result
