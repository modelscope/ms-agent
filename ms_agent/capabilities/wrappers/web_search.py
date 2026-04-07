# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import logging
from typing import Any

from ms_agent.capabilities.descriptor import CapabilityDescriptor
from ms_agent.capabilities.registry import CapabilityRegistry

logger = logging.getLogger(__name__)

_engines: dict[str, Any] = {}
_fetcher: Any = None


def _get_engine(engine_type: str) -> Any:
    """Return a cached :class:`SearchEngine` instance for *engine_type*."""
    if engine_type not in _engines:
        from ms_agent.tools.search.websearch_tool import get_search_engine
        _engines[engine_type] = get_search_engine(engine_type)
    return _engines[engine_type]


def _get_fetcher() -> Any:
    """Return a cached :class:`ContentFetcher` (Jina Reader)."""
    global _fetcher
    if _fetcher is None:
        from ms_agent.tools.search.websearch_tool import get_content_fetcher
        _fetcher = get_content_fetcher('jina_reader')
    return _fetcher


WEB_SEARCH_DESCRIPTOR = CapabilityDescriptor(
    name='web_search',
    version='0.1.0',
    granularity='tool',
    summary=('Search the web using multiple engines (exa, serpapi, arxiv) '
             'and optionally fetch full page content.'),
    description=(
        'Performs a web search and returns structured results including '
        'title, URL, and summary for each hit.  Supports exa, serpapi, '
        'and arxiv backends.  Set fetch_content=true to additionally '
        'retrieve and return page text (truncated to 10 000 chars).'),
    input_schema={
        'type': 'object',
        'properties': {
            'query': {
                'type': 'string',
                'description': 'The search query',
            },
            'num_results': {
                'type': 'integer',
                'description': 'Number of results to return (default: 5)',
                'default': 5,
            },
            'engine_type': {
                'type':
                'string',
                'description':
                ("Search engine to use: 'exa', 'serpapi', or 'arxiv' "
                 "(default: 'arxiv')"),
                'default':
                'arxiv',
            },
            'fetch_content': {
                'type':
                'boolean',
                'description':
                ('Whether to fetch full page content for each result '
                 '(default: false)'),
                'default':
                False,
            },
        },
        'required': ['query'],
    },
    output_schema={
        'type': 'object',
        'properties': {
            'status': {
                'type': 'string'
            },
            'query': {
                'type': 'string'
            },
            'engine': {
                'type': 'string'
            },
            'count': {
                'type': 'integer'
            },
            'results': {
                'type': 'array'
            },
        },
    },
    tags=['search', 'web', 'research'],
    estimated_duration='seconds',
)


async def _handle_web_search(args: dict[str, Any],
                             **kwargs: Any) -> dict[str, Any]:
    """Execute a web search and return structured results."""
    query = (args.get('query') or '').strip()
    if not query:
        return {'error': 'query is required'}

    num_results: int = args.get('num_results', 5)
    engine_type: str = args.get('engine_type', 'arxiv')
    fetch_content: bool = args.get('fetch_content', False)

    # Initialise search engine
    try:
        engine = _get_engine(engine_type)
    except Exception as exc:
        return {
            'error':
            f'Failed to initialise search engine {engine_type!r}: {exc}'
        }

    # Build request via the engine's class method
    engine_cls = type(engine)
    try:
        search_request = engine_cls.build_request_from_args(
            query=query,
            num_results=num_results,
        )
    except Exception as exc:
        return {'error': f'Failed to build search request: {exc}'}

    # SearchEngine.search() is synchronous -- run in executor
    loop = asyncio.get_event_loop()
    try:
        search_result = await loop.run_in_executor(
            None,
            engine.search,
            search_request,
        )
    except Exception as exc:
        return {'error': f'Search failed: {exc}'}

    # Normalise results
    raw_list = search_result.to_list() if search_result else []
    results: list[dict[str, Any]] = []
    for item in raw_list[:num_results]:
        results.append({
            'title': item.get('title', ''),
            'url': item.get('url', ''),
            'summary': item.get('summary', ''),
        })

    # Optional content fetching
    if fetch_content and results:
        fetcher = _get_fetcher()
        for item in results:
            url = item.get('url')
            if not url:
                continue
            try:
                content, _meta = await loop.run_in_executor(
                    None,
                    fetcher.fetch,
                    url,
                )
                item['content'] = content[:10000] if content else ''
            except Exception:
                item['content'] = ''

    return {
        'status': 'ok',
        'query': query,
        'engine': engine_type,
        'count': len(results),
        'results': results,
    }


def register_all(registry: CapabilityRegistry, config: Any = None) -> None:
    """Register web search capabilities into the registry."""
    registry.register(WEB_SEARCH_DESCRIPTOR, _handle_web_search)
