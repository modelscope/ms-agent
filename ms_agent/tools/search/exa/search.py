# flake8: noqa
import os
from typing import TYPE_CHECKING

from exa_py import Exa
from ms_agent.tools.search.exa.schema import ExaSearchRequest, ExaSearchResult
from ms_agent.tools.search.search_base import SearchEngine, SearchEngineType

if TYPE_CHECKING:
    from ms_agent.llm.utils import Tool


class ExaSearch(SearchEngine):
    """
    Search engine using Exa API.

    Best for: semantic understanding, finding similar content,
    recent web pages with date filtering.
    """

    engine_type = SearchEngineType.EXA

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

    @classmethod
    def get_tool_definition(cls, server_name: str = 'web_search') -> 'Tool':
        """Return the tool definition for Exa search engine."""
        from ms_agent.llm.utils import Tool
        return Tool(
            tool_name=cls.get_tool_name(),
            server_name=server_name,
            description=(
                'Search the web using Exa neural search engine. '
                'Best for: semantic understanding, finding relevant content, '
                'recent web pages with date filtering. '
                'Supports neural search (meaning-based) and keyword search.'),
            parameters={
                'type': 'object',
                'properties': {
                    'query': {
                        'type':
                        'string',
                        'description':
                        ('The search query. For neural search, use natural language '
                         'descriptions. For keyword search, use Google-style queries.'
                         ),
                    },
                    'num_results': {
                        'type':
                        'integer',
                        'minimum':
                        1,
                        'maximum':
                        10,
                        'description':
                        'Number of results to return. Default is 3.',
                    },
                    'type': {
                        'type':
                        'string',
                        'enum': ['auto', 'neural', 'keyword'],
                        'description':
                        ('Search type. "neural" for semantic similarity, '
                         '"keyword" for exact matching, "auto" to let Exa decide. '
                         'Default is "auto".'),
                    },
                    'start_published_date': {
                        'type':
                        'string',
                        'description':
                        ('Filter results published on/after this date. '
                         'Format: YYYY-MM-DD (e.g., "2024-01-01").'),
                    },
                    'end_published_date': {
                        'type':
                        'string',
                        'description':
                        ('Filter results published on/before this date. '
                         'Format: YYYY-MM-DD (e.g., "2024-12-31").'),
                    },
                },
                'required': ['query'],
            },
        )

    @classmethod
    def build_request_from_args(cls, **kwargs) -> ExaSearchRequest:
        """Build ExaSearchRequest from tool call arguments."""
        return ExaSearchRequest(
            query=kwargs['query'],
            num_results=kwargs.get('num_results', 5),
            type=kwargs.get('type', 'auto'),
            text=False,
            start_published_date=kwargs.get('start_published_date'),
            end_published_date=kwargs.get('end_published_date'),
        )
