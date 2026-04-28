# Copyright (c) ModelScope Contributors. All rights reserved.
import os
from typing import TYPE_CHECKING, Any, Dict, Optional

from ms_agent.tools.search.search_base import SearchEngine, SearchEngineType
from ms_agent.tools.search.tavily.http import post_json
from ms_agent.tools.search.tavily.schema import (TavilySearchRequest,
                                                 TavilySearchResult)
from ms_agent.utils.logger import get_logger

if TYPE_CHECKING:
    from ms_agent.llm.utils import Tool

logger = get_logger()

TAVILY_SEARCH_URL = 'https://api.tavily.com/search'


class TavilySearch(SearchEngine):
    """
    Tavily Search API — optimized for LLM agents.

    Defaults favor maximum usable text: ``search_depth=advanced``,
    ``include_raw_content=markdown``, ``include_answer=advanced``,
    ``chunks_per_source=3`` (capped by Tavily).
    """

    engine_type = SearchEngineType.TAVILY

    def __init__(
        self,
        api_key: Optional[str] = None,
        request_timeout: float = 120.0,
    ):
        key = api_key or os.getenv('TAVILY_API_KEY')
        if not key:
            raise ValueError(
                'TAVILY_API_KEY must be set in environment or web_search.tavily_api_key'
            )
        self._api_key = key
        self._request_timeout = float(request_timeout)

    def search(self,
               search_request: TavilySearchRequest) -> TavilySearchResult:
        body = search_request.to_api_body(self._api_key)
        try:
            data = post_json(
                TAVILY_SEARCH_URL, body, timeout=self._request_timeout)
        except Exception as e:
            raise RuntimeError(f'Tavily search failed: {e}') from e
        safe_args = {k: v for k, v in body.items() if k != 'api_key'}
        safe_args['api_key'] = '<redacted>'
        return TavilySearchResult(
            query=search_request.query,
            arguments=safe_args,
            response=data or {},
        )

    @classmethod
    def get_tool_definition(cls, server_name: str = 'web_search') -> 'Tool':
        from ms_agent.llm.utils import Tool
        return Tool(
            tool_name=cls.get_tool_name(),
            server_name=server_name,
            description=(
                'Search the web using Tavily (built for AI agents). '
                'Returns ranked results with optional full-page markdown via '
                '`include_raw_content`. Use `search_depth` advanced for best '
                'relevance and richer `content` chunks (higher API credit use).'
            ),
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
                        'Max results (maps to Tavily max_results). Default 10.',
                    },
                    'search_depth': {
                        'type':
                        'string',
                        'enum': ['advanced', 'basic', 'fast', 'ultra-fast'],
                        'description':
                        ('advanced: best quality, 2 credits; '
                         'basic/fast/ultra-fast: 1 credit (see Tavily docs).'),
                    },
                    'topic': {
                        'type':
                        'string',
                        'enum': ['general', 'news', 'finance'],
                        'description':
                        'Search category (`news` / `finance` for focused verticals).',
                    },
                    'time_range': {
                        'type':
                        'string',
                        'description':
                        ('Filter by recency: day, week, month, year or d,w,m,y.'
                         ),
                    },
                    'start_date': {
                        'type': 'string',
                        'description': 'Results after YYYY-MM-DD.',
                    },
                    'end_date': {
                        'type': 'string',
                        'description': 'Results before YYYY-MM-DD.',
                    },
                    'include_answer': {
                        'type':
                        'string',
                        'enum': ['false', 'true', 'basic', 'advanced'],
                        'description':
                        ('LLM answer: true/basic for short, advanced for detailed. '
                         'Use false to skip.'),
                    },
                    'include_raw_content': {
                        'type':
                        'string',
                        'enum': ['false', 'true', 'markdown', 'text'],
                        'description':
                        ('full page text: markdown (recommended) or text; '
                         'false to skip raw content.'),
                    },
                    'chunks_per_source': {
                        'type':
                        'integer',
                        'minimum':
                        1,
                        'maximum':
                        3,
                        'description':
                        ('Relevant chunks per URL when search_depth=advanced. '
                         'Each chunk up to ~500 chars in `content` field.'),
                    },
                    'include_domains': {
                        'type': 'array',
                        'items': {
                            'type': 'string'
                        },
                        'description': 'Only include these domains (max 300).',
                    },
                    'exclude_domains': {
                        'type': 'array',
                        'items': {
                            'type': 'string'
                        },
                        'description': 'Exclude domains (max 150).',
                    },
                    'country': {
                        'type':
                        'string',
                        'description':
                        ('Boost results from country (e.g. united states). '
                         'See Tavily docs for enum.'),
                    },
                    'exact_match': {
                        'type':
                        'boolean',
                        'description':
                        'Only results with exact quoted phrases in query.',
                    },
                },
                'required': ['query'],
            },
        )

    @classmethod
    def build_request_from_args(cls, **kwargs: Any) -> TavilySearchRequest:
        """Build from merged tool args + YAML defaults (see WebSearchTool)."""

        def _boolish(name: str, default: Any) -> Any:
            if name not in kwargs:
                return default
            v = kwargs[name]
            if isinstance(v, str) and v.lower() in ('false', 'true'):
                return v.lower() == 'true'
            return v

        num = kwargs.get('num_results', kwargs.get('max_results', 10))
        try:
            num = int(num)
        except (TypeError, ValueError):
            num = 10

        try:
            cps = int(kwargs.get('chunks_per_source', 3))
        except (TypeError, ValueError):
            cps = 3

        inc_ans = kwargs.get('include_answer', 'advanced')
        if isinstance(inc_ans, str) and inc_ans.lower() == 'false':
            inc_ans = False
        elif isinstance(inc_ans, str) and inc_ans.lower() == 'true':
            inc_ans = True

        inc_raw = kwargs.get('include_raw_content', 'markdown')
        if isinstance(inc_raw, str) and inc_raw.lower() == 'false':
            inc_raw = False
        elif isinstance(inc_raw, str) and inc_raw.lower() == 'true':
            inc_raw = 'markdown'

        return TavilySearchRequest(
            query=kwargs['query'],
            max_results=num,
            search_depth=str(kwargs.get('search_depth', 'advanced')),
            chunks_per_source=cps,
            topic=str(kwargs.get('topic', 'general')),
            time_range=kwargs.get('time_range'),
            start_date=kwargs.get('start_date'),
            end_date=kwargs.get('end_date'),
            include_answer=inc_ans,
            include_raw_content=inc_raw,
            include_images=bool(_boolish('include_images', False)),
            include_image_descriptions=bool(
                _boolish('include_image_descriptions', False)),
            include_favicon=bool(_boolish('include_favicon', False)),
            include_domains=list(kwargs.get('include_domains') or []),
            exclude_domains=list(kwargs.get('exclude_domains') or []),
            country=kwargs.get('country'),
            auto_parameters=bool(_boolish('auto_parameters', False)),
            exact_match=bool(_boolish('exact_match', False)),
            include_usage=bool(_boolish('include_usage', False)),
            safe_search=bool(_boolish('safe_search', False)),
        )
