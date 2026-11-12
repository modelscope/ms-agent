# Copyright (c) ModelScope Contributors. All rights reserved.
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class OutcrawlSearchRequest:
    """Outcrawl POST /v1/search body. See https://outcrawl.ai/docs/search/overview"""

    query: str
    limit: int = 5
    # When true, Outcrawl also scrapes each hit and returns its markdown.
    scrape: bool = False

    def to_api_body(self) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            'query': self.query,
            'limit': max(1, min(20, int(self.limit))),
        }
        if self.scrape:
            body['scrape'] = True
            body['formats'] = ['markdown']
        return body


@dataclass
class OutcrawlSearchResult:
    """Parsed Outcrawl /v1/search JSON."""

    query: str
    arguments: Dict[str, Any]
    response: Dict[str, Any]

    def to_list(self) -> List[Dict[str, Any]]:
        """Normalize to WebSearchTool pipeline dicts (prefill content when markdown is present)."""
        if not self.response:
            return []
        rows: List[Dict[str, Any]] = []
        for hit in self.response.get('hits') or []:
            url = hit.get('url') or ''
            snippet = (hit.get('snippet') or '').strip()
            markdown = (hit.get('markdown') or '').strip()
            rows.append({
                'url': url,
                'id': url,
                'title': hit.get('title') or '',
                'highlights': None,
                'highlight_scores': None,
                'summary': snippet,
                'markdown': markdown or None,
                # Pipeline uses these keys:
                'content': markdown or snippet,
                'fetch_success': bool(markdown),
                'rank': hit.get('rank'),
            })
        return rows
