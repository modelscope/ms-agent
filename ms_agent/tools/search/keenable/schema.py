# Copyright (c) ModelScope Contributors. All rights reserved.
from dataclasses import dataclass, field
from typing import Any, Dict, List

#: The API accepts 1 to 50 for ``max_results``.
MAX_RESULTS = 50


@dataclass
class KeenableSearchRequest:

    # The search query string
    query: str

    # Number of results to return (1 to 50)
    num_results: int = 10

    def to_api_body(self) -> Dict[str, Any]:
        """JSON body for ``POST /v1/search`` and ``/v1/search/public``."""
        return {
            'query': self.query,
            'max_results': max(1, min(int(self.num_results), MAX_RESULTS)),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {'query': self.query, 'num_results': self.num_results}


@dataclass
class KeenableSearchResult:
    """Parsed Keenable search JSON."""

    query: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    response: Dict[str, Any] = field(default_factory=dict)

    def to_list(self) -> List[Dict[str, Any]]:
        """Normalize to WebSearchTool pipeline dicts.

        ``snippet`` is the page text that matches the query; it falls back to
        the meta ``description``. Rows without a URL are dropped. Page content
        is left to the content fetcher, as for Exa.
        """
        if not self.response:
            return []
        rows: List[Dict[str, Any]] = []
        for r in self.response.get('results') or []:
            if not isinstance(r, dict):
                continue
            url = r.get('url') or ''
            if not url:
                continue
            rows.append({
                'url':
                url,
                'id':
                url,
                'title':
                r.get('title') or '',
                'highlights':
                None,
                'highlight_scores':
                None,
                'summary': (r.get('snippet') or r.get('description')
                            or '').strip(),
                'markdown':
                None,
                'published_date':
                r.get('published_at') or '',
            })
        return rows
