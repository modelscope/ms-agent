# flake8: noqa
import os

from exa_py import Exa
from ms_agent.tools.exa.schema import ExaSearchRequest, ExaSearchResult


class ExaSearch:

    def __init__(self, api_key: str = None):

        api_key = api_key or os.getenv('EXA_API_KEY')
        assert api_key, 'EXA_API_KEY must be set either as an argument or as an environment variable'

        self.client = Exa(api_key=api_key)

    def search(self, search_request: ExaSearchRequest) -> ExaSearchResult:
        """
        Perform a search using the Exa API with the provided search request parameters.

        :param search_request: An instance of ExaSearchRequest containing search parameters.
        :return: An instance of ExaSearchResult containing the search results.
        """
        search_args: dict = search_request.to_dict()
        search_result: ExaSearchResult = ExaSearchResult(
            query=search_request.query,
            arguments=search_args,
        )
        try:
            search_result.response = self.client.search_and_contents(
                **search_args)
        except Exception as e:
            raise RuntimeError(f'Failed to perform search: {e}') from e

        return search_result
