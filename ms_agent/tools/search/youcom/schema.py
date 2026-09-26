# Copyright (c) ModelScope Contributors. All rights reserved.
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class YouSearchRequest:
    """You.com POST /search body."""

    query: str
    num_results: int = 10
    search_type: str = 'search'  # search | news | knowledge

    def to_api_body(self) -> Dict[str, Any]:
        return {
            'query': self.query,
            'num_results': max(1, min(20, int(self.num_results))),
        }


@dataclass
class YouSearchResult:
    """Parsed You.com /search JSON."""

    query: str
    arguments: Dict[str, Any]
    response: Dict[str, Any]

    def to_list(self) -> List[Dict[str, Any]]:
        if not self.response:
            return []
        # You.com v1/search returns {'results': [...]} or
        # {'response': {'results': [...]}} or {'hits': [...]}
        results = (
            self.response.get('results')
            or (self.response.get('response') or {}).get('results')
            or self.response.get('hits')
            or []
        )
        if isinstance(results, dict):
            results = results.get('results') or []
        rows: List[Dict[str, Any]] = []
        for r in results:
            url = r.get('url') or ''
            snippet = (r.get('snippet') or r.get('description') or '').strip()
            title = r.get('title') or ''
            rows.append({
                'url': url,
                'id': url,
                'title': title,
                'highlights': None,
                'highlight_scores': None,
                'summary': snippet,
                'markdown': (r.get('markdown') or r.get('contents') or
                             None),
            })
        return rows

    def extra_response_fields(self) -> Dict[str, Any]:
        return {}