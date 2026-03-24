# flake8: noqa
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import json


@dataclass
class TavilySearchRequest:

    # The search query string
    query: str

    # Number of results to return, default is 5
    num_results: Optional[int] = 5

    # Search depth: 'basic' or 'advanced'
    search_depth: Optional[str] = 'advanced'

    # Topic category: 'general', 'news', or 'finance'
    topic: Optional[str] = 'general'

    # Domains to include in search
    include_domains: Optional[List[str]] = None

    # Domains to exclude from search
    exclude_domains: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert the request parameters to a dictionary."""
        d = {
            'query': self.query,
            'max_results': self.num_results,
            'search_depth': self.search_depth,
            'topic': self.topic,
        }
        if self.include_domains:
            d['include_domains'] = self.include_domains
        if self.exclude_domains:
            d['exclude_domains'] = self.exclude_domains
        return d

    def to_json(self) -> str:
        """Convert the request parameters to a JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class TavilySearchResult:

    # The original search query string
    query: str

    # Optional arguments for the search request
    arguments: Dict[str, Any] = field(default_factory=dict)

    # The raw response from the Tavily search API
    response: Any = None

    def to_list(self) -> List[Dict[str, Any]]:
        """Convert the search results to a list of dictionaries."""
        if not self.response or not self.response.get('results'):
            print('***Warning: No search results found.')
            return []

        if not self.query:
            print('***Warning: No query provided for search results.')
            return []

        res_list: List[Dict[str, Any]] = []
        for res in self.response['results']:
            res_list.append({
                'url': res.get('url', ''),
                'id': res.get('url', ''),
                'title': res.get('title', ''),
                'summary': res.get('content', ''),
            })

        return res_list

    @staticmethod
    def load_from_disk(file_path: str) -> List[Dict[str, Any]]:
        """Load search results from a local file."""
        import os
        if not os.path.exists(file_path):
            return []

        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(f'Search results loaded from {file_path}')

        return data
