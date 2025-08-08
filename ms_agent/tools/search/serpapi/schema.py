# flake8: noqa
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ms_agent.tools.search.search_base import (BaseResult, SearchRequest,
                                               SearchResponse, SearchResult)


class SerpApiSearchRequest(SearchRequest):
    """
    A class representing a search request to SerpApi.
    """

    def __init__(self,
                 query: str,
                 num_results: Optional[int] = 25,
                 location: Optional[str] = None):
        """
        Initialize SerpApiSearchRequest with search parameters.

        Args:
            query: The search query string
            num_results: Number of results to return, default is 25
            location: Search location, e.g., 'Austin,Texas'
        """
        super().__init__(query=query, num_results=num_results)
        self.location = location

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the request parameters to a dictionary.

        Returns:
            Dict[str, Any]: The parameters as a dictionary
        """
        return {
            'q': self.query,
            'num': self.num_results,
            'location': self.location
        }


class SerpApiSearchResult(SearchResult):
    """SerpApi search result implementation."""

    def __init__(self,
                 provider: str,
                 query: str,
                 arguments: Dict[str, Any] = None,
                 response: Dict[str, Any] = None):
        """
        Initialize SerpApiSearchResult.

        Args:
            provider: The search provider used for the search
            query: The original search query string
            arguments: The arguments used for the search
            response: The raw results returned by the search
        """
        self.provider = provider
        super().__init__(query, arguments, response)
        self.response = self._process_results()

    def _process_results(self) -> SearchResponse:
        """
        Process the raw results into a standardized format.

        Returns:
            SearchResponse: Processed search results
        """
        if not self.response or not self.response.get('organic_results'):
            print('***Warning: No search results found.')
            return SearchResponse(results=[])

        processed = []
        if self.provider.lower() in ['google', 'bing', 'baidu']:
            # Extract organic results
            organic_results: List[Dict[str, Any]] = self.response.get(
                'organic_results', [])
            for res in organic_results:
                processed.append(
                    BaseResult(
                        url=res.get('link'),
                        id=res.get('link'),
                        title=res.get('title'),
                        highlights=res.get('snippet_highlighted_words'),
                        highlight_scores=None,
                        summary=None,
                        markdown=None))
        else:
            raise NotImplementedError(
                f"Provider '{self.provider}' is not supported yet.")

        return SearchResponse(results=processed)
