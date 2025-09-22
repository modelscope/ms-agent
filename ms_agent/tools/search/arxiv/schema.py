# flake8: noqa
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional

import arxiv
import json
from arxiv import SortCriterion, SortOrder
from ms_agent.tools.search.search_base import (BaseResult, SearchRequest,
                                               SearchResponse, SearchResult)


class ArxivSearchRequest(SearchRequest):
    """
    A class representing a search request to ArXiv.
    """

    def __init__(self,
                 query: str = None,
                 num_results: Optional[int] = 10,
                 sort_strategy: SortCriterion = SortCriterion.Relevance,
                 sort_order: SortOrder = SortOrder.Descending,
                 **kwargs: Any):
        """
        Initialize ArxivSearchRequest with search parameters.

        Args:
            query: The search query string
            num_results: Number of results to return, default is 10
            sort_strategy: The strategy to sort results, default is relevance
            sort_order: The order of sorting, default is descending
        """
        super().__init__(query=query, num_results=num_results, **kwargs)
        self.sort_strategy = sort_strategy
        self.sort_order = sort_order

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the request parameters to a dictionary.

        Returns:
            Dict[str, Any]: The parameters as a dictionary
        """
        return {
            'query': self.query,
            'max_results': self.num_results,
            'sort_by': self.sort_strategy,
            'sort_order': self.sort_order
        }

    def to_json(self) -> Dict[str, Any]:
        """
        Convert the request parameters to a JSON string.

        Returns:
            Dict[str, Any]: The parameters as a JSON string
        """
        return json.dumps(
            {
                'query': self.query,
                'max_results': self.num_results,
                'sort_strategy': self.sort_strategy.value,
                'sort_order': self.sort_order.value
            },
            ensure_ascii=False)


class ArxivSearchResult(SearchResult):
    """ArXiv search result implementation."""

    def __init__(self,
                 query: str,
                 arguments: Dict[str, Any] = None,
                 response: List['arxiv.Result'] = None):
        """
        Initialize ArxivSearchResult.

        Args:
            query: The original search query string
            arguments: The arguments used for the search
            response: The raw results returned by the search
        """
        super().__init__(query, arguments, response)
        self.arguments = self._process_arguments()
        self.response = self._process_results()

    def _process_results(self) -> SearchResponse:
        """
        Process the raw results into a standardized format.

        Returns:
            SearchResponse: Processed search results
        """
        if isinstance(self.response, Generator):
            self.response = list(self.response)

        if not self.response:
            print(
                '***Warning: No search results found. This may happen because '
                'Arxiv\'s search functionality relies on precise metadata matching (e.g., title, '
                'author, abstract keywords) rather than the full-text indexing and complex '
                'ranking algorithms used by search engines like Google, or the semantic search '
                'capabilities of some neural search engines. The search query rewritten by the '
                'model may not align perfectly with Arxiv\'s metadata-driven engine. For a more '
                'robust and stable search experience, consider configuring an advanced search '
                'provider (such as Exa, SerpApi, etc.) in the `conf.yaml` file.'
            )
            return SearchResponse(results=[])

        processed = []
        for res in self.response:
            if not isinstance(res, arxiv.Result):
                print(
                    f'***Warning: Result {res} is not an instance of arxiv.Result.'
                )
                continue

            processed.append(
                BaseResult(
                    url=getattr(res, 'pdf_url', None)
                    or getattr(res, 'entry_id', None),
                    id=getattr(res, 'entry_id', None),
                    title=getattr(res, 'title', None),
                    highlights=None,
                    highlight_scores=None,
                    summary=getattr(res, 'summary', None),
                    markdown=None))

        return SearchResponse(results=processed)

    def _process_arguments(self) -> Dict[str, Any]:
        """Process the search arguments to be JSON serializable."""
        return {
            'query':
            self.query,
            'max_results':
            self.arguments.get('max_results', None),
            'sort_strategy':
            self.arguments.get('sort_strategy', SortCriterion.Relevance).value,
            'sort_order':
            self.arguments.get('sort_order', SortOrder.Descending).value
        }
