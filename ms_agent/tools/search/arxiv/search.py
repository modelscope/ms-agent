# flake8: noqa
import os

import arxiv
from ms_agent.tools.search.arxiv.schema import (ArxivSearchRequest,
                                                ArxivSearchResult)
from ms_agent.tools.search.search_base import SearchEngine, SearchEngineType


class ArxivSearch(SearchEngine):
    """
    A class to perform web searches using the arxiv service.
    """

    def __init__(self):

        self.client = arxiv.Client()
        self.engine_type = SearchEngineType.ARXIV

    def search(self, search_request: ArxivSearchRequest) -> ArxivSearchResult:
        """Perform a search using arxiv and return the results."""
        search_args: dict = search_request.to_dict()

        try:
            response = list(
                self.client.results(search=arxiv.Search(**search_args)))
            search_result = ArxivSearchResult(
                query=search_request.query,
                arguments=search_request.to_dict(),
                response=response)
        except Exception as e:
            raise RuntimeError(f'Failed to perform search: {e}') from e

        return search_result
