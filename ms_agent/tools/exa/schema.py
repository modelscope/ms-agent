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

    # Type of search to perform, can be 'auto', 'neural', or 'keyword'
    type: Optional[str] = 'auto'

    # Number of results to return, default is 25
    num_results: Optional[int] = 25

    # Date filters for search results, formatted as 'YYYY-MM-DD'
    start_published_date: Optional[str] = None
    end_published_date: Optional[str] = None

    # Date filters for crawl data, formatted as 'YYYY-MM-DD'
    start_crawl_date: Optional[str] = None
    end_crawl_date: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the request parameters to a dictionary.
        """
        return {
            'query': self.query,
            'text': self.text,
            'type': self.type,
            'num_results': self.num_results,
            'start_published_date': self.start_published_date,
            'end_published_date': self.end_published_date,
            'start_crawl_date': self.start_crawl_date,
            'end_crawl_date': self.end_crawl_date
        }

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
    # SearchResponse(results=[Result(url='https://arxiv.org/abs/2505.02686', id='https://arxiv.org/abs/2505.02686', title='Sailing A...search_type='neural', auto_date=None, cost_dollars=CostDollars(total=0.03, search={'neural': 0.005}, contents={'text': 0.025}))
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
            res_list.append({
                'url': res.url,
                'id': res.id,
                'title': res.title,
                'highlights': res.highlights,
                'highlight_scores': res.highlight_scores,
                'summary': res.summary,
                'markdown': None,
            })

        return res_list

    @staticmethod
    def load_from_disk(file_path: str) -> List[Dict[str, Any]]:
        """
        Load search results from a local file.

        Example:
        [
            {
              "query": "Survey of Agent RL in last 3 months",
              "arguments": {
                "query": "Survey of Agent RL in last 3 months",
                "text": true,
                "type": "auto",
                "num_results": 25,
                "start_published_date": "2025-05-01",
                "end_published_date": "2025-05-29",
                "start_crawl_date": "2025-01-01",
                "end_crawl_date": "2025-05-29"
              },
              "results": [
                {
                  "url": "https://arxiv.org/abs/2505.17342",
                  "id": "https://arxiv.org/abs/2505.17342",
                  "title": "A Survey of Safe Reinforcement Learning and Constrained MDPs: A Technical Survey on Single-Agent and Multi-Agent Safety",
                  "highlights": null,
                  "highlight_scores": null,
                  "summary": null,
                  "markdown": null,
                },
                ]
            },
        ]
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
