# flake8: noqa
import os
from typing import TYPE_CHECKING

from ms_agent.tools.search.search_base import SearchEngine, SearchEngineType
from ms_agent.tools.search.serpapi.schema import (SerpApiSearchRequest,
                                                  SerpApiSearchResult)

if TYPE_CHECKING:
    from ms_agent.llm.utils import Tool


class SerpApiSearch(SearchEngine):
    """
    Search engine using SerpApi service.

    Best for: general web search via Google/Bing/Baidu, current events,
    news, and real-time information.
    """

    engine_type = SearchEngineType.SERPAPI

    def __init__(self, api_key: str = None, provider: str = None):

        api_key = api_key or os.getenv('SERPAPI_API_KEY')
        assert api_key, 'SERPAPI_API_KEY must be set either as an argument or as an environment variable'

        self.provider = (provider or 'google').lower()
        self.client = self._get_search_client(
            provider=self.provider, api_key=api_key)

    def search(self,
               search_request: SerpApiSearchRequest) -> SerpApiSearchResult:
        """
        Perform a search using SerpApi and return the results.

        Args:
            search_request: A SearchRequest object containing search parameters

        Returns:
            SearchResult: The search results
        """
        search_args = search_request.to_dict()

        try:
            self.client.params_dict.update(search_args)
            response = self.client.get_dict()
            search_result = SerpApiSearchResult(
                provider=self.provider,
                query=search_request.query,
                arguments=search_args,
                response=response)
        except Exception as e:
            raise RuntimeError(f'Failed to perform search: {e}') from e

        return search_result

    @classmethod
    def get_tool_definition(cls, server_name: str = 'web_search') -> 'Tool':
        """Return the tool definition for SerpApi search engine."""
        from ms_agent.llm.utils import Tool
        return Tool(
            tool_name=cls.get_tool_name(),
            server_name=server_name,
            description=(
                'Search the web using Google/Bing/Baidu via SerpApi. '
                'Default provider is Google. '
                'Best for: general web search, current events, news, '
                'real-time information, and location-specific results. '
                'Supports Google search operators.'),
            parameters={
                'type': 'object',
                'properties': {
                    'query': {
                        'type':
                        'string',
                        'description':
                        ('Google-style search query. Use operators as needed: '
                         'quotes for exact phrases ("..."), OR, -term to exclude. '
                         'Date limits: before:YYYY-MM-DD, after:YYYY-MM-DD.'),
                    },
                    'num_results': {
                        'type':
                        'integer',
                        'minimum':
                        1,
                        'maximum':
                        10,
                        'description':
                        'Number of results to return. Default is 5.',
                    },
                    'location': {
                        'type':
                        'string',
                        'description':
                        ('Geographic location filter. Default is null'),
                    },
                },
                'required': ['query'],
            },
        )

    @classmethod
    def build_request_from_args(cls, **kwargs) -> SerpApiSearchRequest:
        """Build SerpApiSearchRequest from tool call arguments."""
        return SerpApiSearchRequest(
            query=kwargs['query'],
            num_results=kwargs.get('num_results', 5),
            location=kwargs.get('location'),
        )

    @staticmethod
    def _get_search_client(provider: str = None, api_key: str = None):
        """
        Get a search client based on the provider.

        Args:
            api_key: The API key for SerpApi
            provider: The search provider to use ('google', 'baidu', 'bing')

        Returns:
            A SerpApi instance for the specified provider

        Raises:
            ValueError: If an unsupported provider is specified
        """
        from serpapi import BaiduSearch, BingSearch, GoogleSearch

        if provider == 'google':
            return GoogleSearch(params_dict={'api_key': api_key})
        elif provider == 'baidu':
            return BaiduSearch(params_dict={'api_key': api_key})
        elif provider == 'bing':
            return BingSearch(params_dict={'api_key': api_key})
        else:
            raise ValueError(
                f"Unsupported search provider: {provider}. Supported providers are: 'google', 'baidu', 'bing'"
            )
