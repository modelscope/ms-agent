# Copyright (c) ModelScope Contributors. All rights reserved.
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TavilySearchRequest:
    """Tavily POST /search body. See https://docs.tavily.com/documentation/api-reference/endpoint/search"""

    query: str
    max_results: int = 10
    search_depth: str = 'advanced'
    chunks_per_source: int = 3
    topic: str = 'general'
    time_range: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    # include_answer: false | true | basic | advanced
    include_answer: Any = 'advanced'
    # include_raw_content: false | true | markdown | text — use markdown for richest text
    include_raw_content: Any = 'markdown'
    include_images: bool = False
    include_image_descriptions: bool = False
    include_favicon: bool = False
    include_domains: List[str] = field(default_factory=list)
    exclude_domains: List[str] = field(default_factory=list)
    country: Optional[str] = None
    auto_parameters: bool = False
    exact_match: bool = False
    include_usage: bool = False
    safe_search: bool = False

    def to_api_body(self, api_key: str) -> Dict[str, Any]:
        n = max(0, min(20, int(self.max_results)))
        body: Dict[str, Any] = {
            'api_key': api_key,
            'query': self.query,
            'max_results': n,
            'search_depth': self.search_depth,
            'topic': self.topic,
            'include_answer': self.include_answer,
            'include_raw_content': self.include_raw_content,
            'include_images': self.include_images,
            'include_image_descriptions': self.include_image_descriptions,
            'include_favicon': self.include_favicon,
            'auto_parameters': self.auto_parameters,
            'exact_match': self.exact_match,
            'include_usage': self.include_usage,
            'safe_search': self.safe_search,
        }
        # chunks_per_source only meaningful for advanced (per Tavily docs)
        if self.search_depth == 'advanced':
            body['chunks_per_source'] = max(1, min(3, int(self.chunks_per_source)))
        if self.time_range:
            body['time_range'] = self.time_range
        if self.start_date:
            body['start_date'] = self.start_date
        if self.end_date:
            body['end_date'] = self.end_date
        if self.include_domains:
            body['include_domains'] = list(self.include_domains)[:300]
        if self.exclude_domains:
            body['exclude_domains'] = list(self.exclude_domains)[:150]
        if self.country:
            body['country'] = self.country
        return body


@dataclass
class TavilySearchResult:
    """Parsed Tavily /search JSON."""

    query: str
    arguments: Dict[str, Any]
    response: Dict[str, Any]

    def to_list(self) -> List[Dict[str, Any]]:
        """Normalize to WebSearchTool pipeline dicts (prefill content when raw_content present)."""
        if not self.response:
            return []
        rows: List[Dict[str, Any]] = []
        for r in self.response.get('results') or []:
            url = r.get('url') or ''
            title = r.get('title') or ''
            snippet = (r.get('content') or '').strip()
            raw = (r.get('raw_content') or '').strip()
            # Prefer full page text for downstream summarization; fallback to snippets
            body = raw if raw else snippet
            rows.append({
                'url': url,
                'id': url,
                'title': title,
                'highlights': None,
                'highlight_scores': None,
                'summary': snippet,
                'markdown': raw if raw else None,
                # Pipeline uses these keys:
                'content': body,
                'fetch_success': bool(raw),
                'score': r.get('score'),
                'tavily_images': r.get('images') or [],
                'favicon': r.get('favicon'),
            })
        return rows

    def extra_response_fields(self) -> Dict[str, Any]:
        """Top-level fields to merge into web_search JSON output."""
        if not self.response:
            return {}
        out: Dict[str, Any] = {}
        if self.response.get('answer'):
            out['tavily_answer'] = self.response['answer']
        if self.response.get('images'):
            out['tavily_images'] = self.response['images']
        if self.response.get('response_time') is not None:
            out['tavily_response_time'] = self.response['response_time']
        if self.response.get('usage'):
            out['tavily_usage'] = self.response['usage']
        if self.response.get('request_id'):
            out['tavily_request_id'] = self.response['request_id']
        return out
