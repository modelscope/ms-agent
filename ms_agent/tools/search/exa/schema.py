# flake8: noqa
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import json
from exa_py.api import SearchResponse


@dataclass
class ExaSearchRequest:

    # The search query string
    query: str

    # Include text content in the search results or not
    text: Optional[bool] = True

    # Include highlights in the search results
    highlights: Optional[bool] = False

    # Include summary in the search results
    summary: Optional[bool] = False

    # Type of search to perform: 'auto', 'neural', 'fast', 'deep-lite',
    # 'deep', 'deep-reasoning', or 'instant'
    type: Optional[str] = 'auto'

    # Number of results to return, default is 5
    num_results: Optional[int] = 5

    # Date filters for search results, formatted as 'YYYY-MM-DD'
    start_published_date: Optional[str] = None
    end_published_date: Optional[str] = None

    # Date filters for crawl data, formatted as 'YYYY-MM-DD'
    start_crawl_date: Optional[str] = None
    end_crawl_date: Optional[str] = None

    # Domain filtering
    include_domains: Optional[List[str]] = None
    exclude_domains: Optional[List[str]] = None

    # Category filter: 'company', 'research paper', 'news',
    # 'personal site', 'financial report', 'people'
    category: Optional[str] = None

    # User location (two-letter ISO country code)
    user_location: Optional[str] = None

    # temporary field for research goal
    research_goal: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the request parameters to a dictionary suitable for
        exa-py's search_and_contents() call.
        """
        d: Dict[str, Any] = {
            'query': self.query,
            'text': self.text,
            'highlights': self.highlights,
            'summary': self.summary,
            'type': self.type,
            'num_results': self.num_results,
            'start_published_date': self.start_published_date,
            'end_published_date': self.end_published_date,
            'start_crawl_date': self.start_crawl_date,
            'end_crawl_date': self.end_crawl_date,
        }
        if self.include_domains:
            d['include_domains'] = self.include_domains
        if self.exclude_domains:
            d['exclude_domains'] = self.exclude_domains
        if self.category:
            d['category'] = self.category
        if self.user_location:
            d['user_location'] = self.user_location
        return d

    def to_json(self) -> str:
        """
        Convert the request parameters to a JSON string.
        """
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class ExaSearchResult:

    # The original search query string
    query: str

    # Optional arguments for the search request
    arguments: Dict[str, Any] = field(default_factory=dict)

    # The response from the Exa search API
    response: SearchResponse = None

    def to_list(self):
        """
        Convert the search results to a list of dictionaries.
        """
        if not self.response or not self.response.results:
            print('***Warning: No search results found.')
            return []

        if not self.query:
            print('***Warning: No query provided for search results.')
            return []

        res_list: List[Any] = []
        for res in self.response.results:
            entry: Dict[str, Any] = {
                'url': getattr(res, 'url', ''),
                'id': getattr(res, 'id', ''),
                'title': getattr(res, 'title', ''),
                'published_date': getattr(res, 'published_date', ''),
            }
            # Include content fields when available, cascading through
            # summary > highlights > text for snippet extraction.
            summary = getattr(res, 'summary', None)
            highlights = getattr(res, 'highlights', None)
            text = getattr(res, 'text', None)

            if summary:
                entry['summary'] = summary
            if highlights:
                entry['highlights'] = highlights
                entry['highlight_scores'] = getattr(
                    res, 'highlight_scores', None)
            if text:
                entry['text'] = text

            res_list.append(entry)

        return res_list

    @staticmethod
    def load_from_disk(file_path: str) -> List[Dict[str, Any]]:
        """
        Load search results from a local file.
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(f'Search results loaded from {file_path}')

        return data


def dump_batch_search_results(results: List[ExaSearchResult],
                              file_path: str) -> None:
    """
    Dump a batch of search results to a local file.
    """
    out_list: List[Dict[str, Any]] = []
    for res in results:
        out_list.append({
            'query': res.query,
            'arguments': res.arguments,
            'results': res.to_list(),
        })

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(out_list, f, ensure_ascii=False, indent=2)

    print(f'Batched search results dumped to {file_path}')
