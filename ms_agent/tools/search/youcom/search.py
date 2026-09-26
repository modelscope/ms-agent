# Copyright (c) ModelScope Contributors. All rights reserved.
import os
from typing import TYPE_CHECKING, Any, Optional

from ms_agent.tools.search.search_base import SearchEngine, SearchEngineType
from ms_agent.tools.search.youcom.http import YouHTTPError, get_json
from ms_agent.tools.search.youcom.schema import (YouSearchRequest,
                                                 YouSearchResult)
from ms_agent.utils.logger import get_logger

if TYPE_CHECKING:
    from ms_agent.llm.utils import Tool

logger = get_logger()

#: Authenticated search endpoint (use with YDC_API_KEY).
YOU_SEARCH_URL = 'https://api.you.com/v1/search'
#: Keyless search endpoint — no API key required, rate limited (~100 req/day).
YOU_KEYLESS_URL = 'https://api.you.com/v1/agents/search'


class YouSearch(SearchEngine):
    """You.com Search — keyed or keyless web search for AI agents.

    Works with an API key (``YDC_API_KEY``) for higher rate limits, or falls
    back to the free keyless tier when no key is set — no signup required.
    """

    engine_type = SearchEngineType.YOCOM

    def __init__(
        self,
        api_key: Optional[str] = None,
        request_timeout: float = 60.0,
    ):
        self._api_key = api_key or os.getenv('YDC_API_KEY') or ''
        self._request_timeout = float(request_timeout)

    @property
    def keyless(self) -> bool:
        return not self._api_key

    def _search_url(self) -> str:
        return YOU_KEYLESS_URL if self.keyless else YOU_SEARCH_URL

    def _headers(self) -> dict:
        if self.keyless:
            return {}
        return {'Authorization': f'Bearer {self._api_key}'}

    def search(self, search_request: YouSearchRequest) -> YouSearchResult:
        params = search_request.to_api_body()
        data = get_json(
            self._search_url(),
            params=params,
            headers=self._headers(),
            timeout=self._request_timeout,
        )
        return YouSearchResult(
            query=search_request.query,
            arguments={'query': search_request.query,
                       'num_results': search_request.num_results},
            response=data,
        )

    @classmethod
    def get_tool_definition(cls, server_name: str = 'web_search') -> 'Tool':
        from ms_agent.llm.utils import Tool
        return Tool(
            tool_name=cls.get_tool_name(),
            server_name=server_name,
            description=(
                'Search the web using You.com. Returns ranked web search '
                'results with titles, URLs, and snippets. '
                'Works without an API key on the free keyless tier.'
            ),
            parameters={
                'type': 'object',
                'properties': {
                    'query': {
                        'type': 'string',
                        'description': 'The search query.',
                    },
                    'num_results': {
                        'type': 'integer',
                        'minimum': 1,
                        'maximum': 10,
                        'description': (
                            'Number of search results to return. Default 5.'),
                    },
                },
                'required': ['query'],
            },
        )

    @classmethod
    def build_request_from_args(cls, **kwargs: Any) -> YouSearchRequest:
        num = kwargs.get('num_results', 5)
        try:
            num = int(num)
        except (TypeError, ValueError):
            num = 5
        return YouSearchRequest(
            query=kwargs['query'],
            num_results=num,
            search_type=kwargs.get('search_type', 'search'),
        )