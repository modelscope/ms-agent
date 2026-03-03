# flake8: noqa
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional

import arxiv
import json
from arxiv import SortCriterion, SortOrder
from ms_agent.tools.search.search_base import (BaseResult, SearchRequest,
                                               SearchResponse, SearchResult)
from ms_agent.utils.logger import get_logger

logger = get_logger()


class ArxivSearchRequest(SearchRequest):
    """
    A class representing a search request to ArXiv.
    """

    def __init__(self,
                 query: str = None,
                 num_results: Optional[int] = 10,
                 sort_strategy: SortCriterion = SortCriterion.Relevance,
                 sort_order: SortOrder = SortOrder.Descending,
                 categories: Optional[List[str]] = None,
                 date_from: Optional[str] = None,
                 date_to: Optional[str] = None,
                 **kwargs: Any):
        """
        Initialize ArxivSearchRequest with search parameters.

        Args:
            query: The search query string
            num_results: Number of results to return, default is 10
            sort_strategy: The strategy to sort results, default is relevance
            sort_order: The order of sorting, default is descending
            categories: Optional arXiv category filter list (e.g., ["cs.AI", "cs.LG"])
            date_from: Optional start date (YYYY-MM-DD), applied client-side
            date_to: Optional end date (YYYY-MM-DD), applied client-side
        """
        super().__init__(query=query, num_results=num_results, **kwargs)
        self.sort_strategy = sort_strategy
        self.sort_order = sort_order
        self.categories = categories
        self.date_from = date_from
        self.date_to = date_to
        self.sort_strategy_map = {
            'relevance': SortCriterion.Relevance,
            'lastUpdatedDate': SortCriterion.LastUpdatedDate,
            'submittedDate': SortCriterion.SubmittedDate
        }
        self.sort_order_map = {
            'descending': SortOrder.Descending,
            'ascending': SortOrder.Ascending
        }

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the request parameters to a dictionary.

        Returns:
            Dict[str, Any]: The parameters as a dictionary
        """
        if isinstance(self.sort_strategy, str) and self.sort_strategy_map.get(
                self.sort_strategy):
            self.sort_strategy = self.sort_strategy_map[self.sort_strategy]
        if isinstance(self.sort_order, str) and self.sort_order_map.get(
                self.sort_order):
            self.sort_order = self.sort_order_map[self.sort_order]

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
        self.raw_response = response
        self.arguments = self._process_arguments()
        self.response = self._process_results()

    def _process_results(self) -> SearchResponse:
        """
        Process the raw results into a standardized format.

        Returns:
            SearchResponse: Processed search results
        """
        if isinstance(self.raw_response, Generator):
            self.raw_response = list(self.raw_response)
        if self.raw_response is None:
            self.raw_response = []

        if not self.raw_response:
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
        for res in self.raw_response:
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
        sort_strategy = self.arguments.get('sort_strategy', None)
        if sort_strategy is None:
            sort_strategy = self.arguments.get('sort_by',
                                               SortCriterion.Relevance)
        sort_order = self.arguments.get('sort_order', SortOrder.Descending)

        if isinstance(sort_strategy, SortCriterion):
            sort_strategy_val = sort_strategy.value
        elif isinstance(sort_strategy, str):
            sort_strategy_val = sort_strategy
        else:
            sort_strategy_val = SortCriterion.Relevance.value

        if isinstance(sort_order, SortOrder):
            sort_order_val = sort_order.value
        elif isinstance(sort_order, str):
            sort_order_val = sort_order
        else:
            sort_order_val = SortOrder.Descending.value

        out = {
            'query': self.query,
            'max_results': self.arguments.get('max_results', None),
            'sort_strategy': sort_strategy_val,
            'sort_order': sort_order_val,
        }

        # Only include optional filters if they were explicitly provided
        if 'date_from' in self.arguments:
            out['date_from'] = self.arguments.get('date_from', None)
        if 'date_to' in self.arguments:
            out['date_to'] = self.arguments.get('date_to', None)
        if 'categories' in self.arguments:
            out['categories'] = self.arguments.get('categories', None)

        return out

    def to_list(self) -> List[Dict[str, Any]]:
        """
        Convert the search results to a list of dictionaries.

        This overrides the base implementation to include arXiv-specific metadata
        (published_date/authors/categories/resource_uri) similar to arxiv-mcp-server.
        """
        if not self.raw_response:
            logger.info('***Warning: No search results found.')
            return []

        if not self.query:
            print('***Warning: No query provided for search results.')
            return []

        res_list: List[Dict[str, Any]] = []
        for res in self.raw_response:
            short_id = getattr(res, 'get_short_id', None)
            short_id = short_id() if callable(short_id) else None

            published = getattr(res, 'published', None)
            published_date = published.isoformat() if published else ''

            authors = getattr(res, 'authors', None)
            if authors:
                authors = [getattr(a, 'name', str(a)) for a in authors]
            else:
                authors = []

            categories = getattr(res, 'categories', None) or []

            res_list.append({
                'url': (getattr(res, 'pdf_url', None)
                        or getattr(res, 'entry_id', None) or ''),
                'id':
                getattr(res, 'entry_id', None) or '',
                'title':
                getattr(res, 'title', None) or '',
                'published_date':
                published_date,
                'summary':
                getattr(res, 'summary', None) or '',
                'highlights':
                None,
                'highlight_scores':
                None,
                'markdown':
                None,
                'authors':
                authors,
                'categories':
                categories,
                'arxiv_id':
                short_id or '',
                'resource_uri':
                f'arxiv://{short_id}' if short_id else '',
            })

        return res_list
