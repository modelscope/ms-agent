# Copyright (c) ModelScope Contributors. All rights reserved.
import os
from typing import TYPE_CHECKING, Any, Optional

from ms_agent.tools.search.outcrawl.http import post_json
from ms_agent.tools.search.outcrawl.schema import (OutcrawlSearchRequest,
                                                   OutcrawlSearchResult)
from ms_agent.tools.search.search_base import SearchEngine, SearchEngineType
from ms_agent.utils.logger import get_logger

if TYPE_CHECKING:
    from ms_agent.llm.utils import Tool

logger = get_logger()


class OutcrawlSearch(SearchEngine):
    """
    Outcrawl (https://outcrawl.ai) is a scrape and search API for AI agents.

    Uses POST /v1/search. With ``scrape=true`` each hit also carries the page
    markdown, so WebSearchTool can skip the separate fetch step.
    """

    engine_type = SearchEngineType.OUTCRAWL

    def __init__(
        self,
        api_key: Optional[str] = None,
        request_timeout: float = 60.0,
    ):
        self._api_key = api_key or os.getenv('OUTCRAWL_API_KEY') or ''
        if not self._api_key:
            raise ValueError(
                'OUTCRAWL_API_KEY must be set either as an argument '
                'or as an environment variable')
        self._request_timeout = float(request_timeout)

    def search(self,
               search_request: OutcrawlSearchRequest) -> OutcrawlSearchResult:
        body = search_request.to_api_body()
        # Unguarded on purpose: OutcrawlHTTPError carries the status/code the
        # tool layer uses to tell the agent why a search failed.
        data = post_json(
            '/search',
            body,
            api_key=self._api_key,
            timeout=self._request_timeout)
        return OutcrawlSearchResult(
            query=search_request.query,
            arguments=body,
            response=data or {},
        )

    @classmethod
    def get_tool_definition(cls, server_name: str = 'web_search') -> 'Tool':
        from ms_agent.llm.utils import Tool
        return Tool(
            tool_name=cls.get_tool_name(),
            server_name=server_name,
            description=(
                'Search the web using Outcrawl, a scrape and search API for '
                'AI agents. Returns ranked results with title, URL and '
                'snippet. Set `scrape` to true to also get each page as '
                'markdown in the same call.'),
            parameters={
                'type': 'object',
                'properties': {
                    'query': {
                        'type': 'string',
                        'description': 'Search query.',
                    },
                    'num_results': {
                        'type':
                        'integer',
                        'minimum':
                        1,
                        'maximum':
                        20,
                        'description':
                        'Max results (maps to Outcrawl limit). Default 5.',
                    },
                    'scrape': {
                        'type':
                        'boolean',
                        'description':
                        ('Also scrape each result and return its markdown. '
                         'Uses more credits. Default false.'),
                    },
                },
                'required': ['query'],
            },
        )

    @classmethod
    def build_request_from_args(cls, **kwargs: Any) -> OutcrawlSearchRequest:
        num = kwargs.get('num_results', kwargs.get('limit', 5))
        try:
            num = int(num)
        except (TypeError, ValueError):
            num = 5
        scrape = kwargs.get('scrape', False)
        if isinstance(scrape, str):
            scrape = scrape.lower() == 'true'
        return OutcrawlSearchRequest(
            query=kwargs['query'],
            limit=num,
            scrape=bool(scrape),
        )
