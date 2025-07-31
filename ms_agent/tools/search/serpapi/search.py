# flake8: noqa
import os

from ms_agent.tools.search.search_base import SearchEngine, SearchEngineType
from ms_agent.tools.search.serpapi.schema import (SerpApiSearchRequest,
                                                  SerpApiSearchResult)
from serpapi import BaiduSearch, BingSearch, GoogleSearch


class SerpApiSearch(SearchEngine):
    """
    A class to perform web searches using the SerpApi service.
    """

    def __init__(self, api_key: str = None, provider: str = None):

        api_key = api_key or os.getenv('SERPAPI_API_KEY')
        assert api_key, 'SERPAPI_API_KEY must be set either as an argument or as an environment variable'

        self.provider = provider.lower()
        self.client = self._get_search_client(
            provider=self.provider, api_key=api_key)
        self.engine_type = SearchEngineType.SERPAPI

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
