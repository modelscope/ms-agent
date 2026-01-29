# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Type

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.tools.jina_reader import JinaReaderConfig, fetch_single_text
from ms_agent.tools.search.search_base import ENGINE_TOOL_NAMES, SearchEngine
from ms_agent.utils.logger import get_logger

logger = get_logger()

MAX_FETCH_CHARS = int(os.getenv('MAX_FETCH_CHARS', 100000))


def _json_dumps(data: Any) -> str:
    import json
    return json.dumps(data, ensure_ascii=False, indent=2)


def _extract_date_from_text(text: str) -> Optional[str]:
    """
    Try to extract a publication date from text content.
    Returns YYYY-MM-DD format if found.
    """
    # Common date patterns
    patterns = [
        r'(\d{4}[-/]\d{2}[-/]\d{2})',  # 2024-01-15 or 2024/01/15
        r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})',  # 15 Jan 2024
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})',  # Jan 15, 2024
    ]
    for pattern in patterns:
        match = re.search(pattern, text[:2000], re.IGNORECASE)
        if match:
            return match.group(1)
    return None


@dataclass
class TextChunk:
    chunk_id: str
    content: str
    start_pos: int
    end_pos: int


def chunk_text_simple(text: str,
                      chunk_size: int = 1500,
                      overlap: int = 200,
                      prefix: str = '') -> List[TextChunk]:
    """
    Simple text chunking by character count with overlap.
    Tries to break at paragraph or sentence boundaries when possible.

    Args:
        text: The text to chunk
        chunk_size: Target chunk size in characters
        overlap: Overlap between chunks
        prefix: Prefix for chunk IDs

    Returns:
        List of TextChunk objects
    """
    if not text or chunk_size <= 0:
        return []

    text = text.strip()
    if len(text) <= chunk_size:
        return [
            TextChunk(
                chunk_id=f'{prefix}0' if prefix else '0',
                content=text,
                start_pos=0,
                end_pos=len(text))
        ]

    chunks: List[TextChunk] = []
    start = 0
    chunk_idx = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))

        # Try to find a good break point
        if end < len(text):
            # Look for paragraph break first
            para_break = text.rfind('\n\n', start + overlap, end)
            if para_break > start + overlap:
                end = para_break + 2
            else:
                # Look for sentence break
                for sep in ['. ', '。', '!\n', '?\n', '.\n']:
                    sent_break = text.rfind(sep, start + overlap, end)
                    if sent_break > start + overlap:
                        end = sent_break + len(sep)
                        break

        chunk_content = text[start:end].strip()
        if chunk_content:
            chunks.append(
                TextChunk(
                    chunk_id=f'{prefix}{chunk_idx}'
                    if prefix else str(chunk_idx),
                    content=chunk_content,
                    start_pos=start,
                    end_pos=end))
            chunk_idx += 1

        # Move start with overlap
        start = end - overlap if end < len(text) else len(text)
        if start >= len(text):
            break

    return chunks


class ContentFetcher:
    """Base interface for content fetching."""

    def fetch(self, url: str) -> Tuple[str, Dict[str, Any]]:
        """
        Fetch content from URL.

        Returns:
            Tuple of (content_text, metadata_dict)
        """
        raise NotImplementedError


class JinaContentFetcher(ContentFetcher):
    """Fetch content using Jina Reader."""

    def __init__(self, config: Optional[JinaReaderConfig] = None):
        self.config = config or JinaReaderConfig()

    def fetch(
        self,
        url: str,
        max_chars: Optional[int] = MAX_FETCH_CHARS
    ) -> Tuple[str, Dict[str, Any]]:
        content = fetch_single_text(url, self.config)
        metadata: Dict[str, Any] = {
            'fetcher': 'jina_reader',
            'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }

        if max_chars:
            content = content[:max_chars]

        return content, metadata


# Future: DoclingContentFetcher can be added here
# class DoclingContentFetcher(ContentFetcher):
#     """Fetch content using Docling parser."""
#     pass


def get_content_fetcher(fetcher_type: str = 'jina_reader',
                        **kwargs) -> ContentFetcher:
    """Factory function to get content fetcher by type."""
    if fetcher_type == 'jina_reader':
        config = JinaReaderConfig(
            timeout=kwargs.get('timeout', 30.0),
            retries=kwargs.get('retries', 3),
        )
        return JinaContentFetcher(config)
    # Future: add more fetchers
    # elif fetcher_type == 'docling':
    #     return DoclingContentFetcher(**kwargs)
    else:
        logger.warning(
            f"Unknown fetcher type '{fetcher_type}', falling back to jina_reader"
        )
        return JinaContentFetcher()


def get_search_engine_class(engine_type: str) -> Type[SearchEngine]:
    """
    Get search engine class by type.

    Args:
        engine_type: One of 'exa', 'serpapi', 'arxiv'

    Returns:
        SearchEngine class (not instance)
    """
    engine_type = engine_type.lower().strip()

    if engine_type == 'exa':
        from ms_agent.tools.search.exa import ExaSearch
        return ExaSearch
    elif engine_type in ('serpapi', 'serp', 'google', 'bing', 'baidu'):
        from ms_agent.tools.search.serpapi import SerpApiSearch
        return SerpApiSearch
    elif engine_type == 'arxiv':
        from ms_agent.tools.search.arxiv import ArxivSearch
        return ArxivSearch
    else:
        logger.warning(
            f"Unknown search engine '{engine_type}', falling back to arxiv")
        from ms_agent.tools.search.arxiv import ArxivSearch
        return ArxivSearch


def get_search_engine(engine_type: str,
                      api_key: Optional[str] = None,
                      **kwargs) -> SearchEngine:
    """
    Get search engine instance by type.

    Args:
        engine_type: One of 'exa', 'serpapi', 'arxiv'
        api_key: API key for the search engine (if required)
        **kwargs: Additional arguments passed to engine constructor
    """
    engine_type = engine_type.lower().strip()

    if engine_type == 'exa':
        from ms_agent.tools.search.exa import ExaSearch
        return ExaSearch(api_key=api_key or os.getenv('EXA_API_KEY'))
    elif engine_type in ('serpapi', 'serp', 'google', 'bing', 'baidu'):
        from ms_agent.tools.search.serpapi import SerpApiSearch
        # Allow shorthand engine_type aliases to imply provider
        default_provider = ('google' if engine_type in ('serpapi', 'serp') else
                            engine_type)
        return SerpApiSearch(
            api_key=api_key or os.getenv('SERPAPI_API_KEY'),
            provider=kwargs.get('provider', default_provider),
        )
    elif engine_type == 'arxiv':
        from ms_agent.tools.search.arxiv import ArxivSearch
        return ArxivSearch()
    else:
        logger.warning(
            f"Unknown search engine '{engine_type}', falling back to arxiv")
        from ms_agent.tools.search.arxiv import ArxivSearch
        return ArxivSearch()


# Kept for backward compatibility
def build_search_request(engine_type: str,
                         query: str,
                         num_results: int = 5,
                         **kwargs):
    """Build a search request for the specified engine.

    DEPRECATED: Use SearchEngine.build_request_from_args() instead.
    """
    engine_cls = get_search_engine_class(engine_type)
    return engine_cls.build_request_from_args(
        query=query, num_results=num_results, **kwargs)


class WebSearchTool(ToolBase):
    """
    Unified web search tool for agents. It can search the web and fetch page content.
    - Search via multiple engines (Exa, SerpAPI, Arxiv)
    - Dynamic tool definitions based on configured engines
    - Auto-fetch and parse page content
    - Configurable content fetcher (jina_reader, docling, etc.)
    - Optional text chunking
    - Structured output format

    Configuration (in agent YAML):
        # Single engine mode:
        tools:
          web_search:
            engine: exa  # or 'serpapi', 'arxiv'
            api_key: xxxxxxxx
            fetcher: jina_reader
            fetch_content: true
            max_results: 10
            enable_chunking: false
        # Multi-engine mode:
        tools:
          web_search:
            engines:
              - exa      # Provides exa_search tool
              - arxiv    # Provides arxiv_search tool
            exa_api_key: $EXA_API_KEY
            serpapi_api_key: $SERPAPI_API_KEY
            fetch_content: true
    """

    SERVER_NAME = 'web_search'

    # Registry of supported search engines
    SUPPORTED_ENGINES = ('exa', 'serpapi', 'arxiv')

    def __init__(self, config, **kwargs):
        super().__init__(config)
        tool_cfg = getattr(getattr(config, 'tools'), 'web_search')
        self.exclude_func(tool_cfg)

        # Parse engine configuration - support both single and multi-engine modes
        engines_config = getattr(tool_cfg, 'engines',
                                 None) if tool_cfg else None
        if engines_config:
            # Multi-engine mode: engines: [exa, arxiv]
            # Note: OmegaConf ListConfig is iterable but not isinstance of list/tuple
            if hasattr(engines_config,
                       '__iter__') and not isinstance(engines_config, str):
                self._engine_types = [
                    str(e).lower().strip() for e in engines_config
                ]
            else:
                self._engine_types = [str(engines_config).lower().strip()]
        else:
            # Single engine mode (backward compatible): engine: exa
            single_engine = getattr(tool_cfg, 'engine',
                                    'arxiv') if tool_cfg else 'arxiv'
            self._engine_types = [single_engine.lower().strip()]

        # Validate engine types
        self._engine_types = [
            e for e in self._engine_types if e in self.SUPPORTED_ENGINES
        ]
        if not self._engine_types:
            logger.warning(
                'No valid engines configured, falling back to arxiv')
            self._engine_types = ['arxiv']

        # API keys for each engine
        self._api_keys = {
            'exa': (
                getattr(tool_cfg, 'exa_api_key', None)
                or getattr(tool_cfg, 'api_key', None)  # backward compat
                or os.getenv('EXA_API_KEY'))
            if tool_cfg else os.getenv('EXA_API_KEY'),
            'serpapi': (getattr(tool_cfg, 'serpapi_api_key', None)
                        or os.getenv('SERPAPI_API_KEY'))
            if tool_cfg else os.getenv('SERPAPI_API_KEY'),
        }

        # SerpApi provider (google, bing, baidu)
        self._serpapi_provider = getattr(tool_cfg, 'serpapi_provider',
                                         'google') if tool_cfg else 'google'

        # Default result count
        self._max_results = int(getattr(tool_cfg, 'max_results', 5)
                                or 5) if tool_cfg else 5

        # Content fetcher config
        self._fetcher_type = getattr(
            tool_cfg, 'fetcher', 'jina_reader') if tool_cfg else 'jina_reader'
        self._fetch_timeout = float(
            getattr(tool_cfg, 'fetch_timeout', 30) or 30) if tool_cfg else 30.0
        self._fetch_retries = int(getattr(tool_cfg, 'fetch_retries', 3)
                                  or 3) if tool_cfg else 3
        self._fetch_content_default = bool(
            getattr(tool_cfg, 'fetch_content', True)) if tool_cfg else True

        # Chunking config
        self._enable_chunking = bool(
            getattr(tool_cfg, 'enable_chunking', False)) if tool_cfg else False
        self._chunk_size = int(getattr(tool_cfg, 'chunk_size', 2000)
                               or 2000) if tool_cfg else 2000
        self._chunk_overlap = int(
            getattr(tool_cfg, 'chunk_overlap', 200)
            or 200) if tool_cfg else 200

        # Concurrency
        self._max_concurrent_fetch = int(
            getattr(tool_cfg, 'max_concurrent_fetch', 3)
            or 3) if tool_cfg else 3

        # Runtime instances (lazy init)
        self._engines: Dict[str, SearchEngine] = {
        }  # engine_type -> engine instance
        self._engine_classes: Dict[str, Type[SearchEngine]] = {
        }  # engine_type -> engine class
        self._content_fetcher: Optional[ContentFetcher] = None
        self._executor: Optional[ThreadPoolExecutor] = None

    async def connect(self) -> None:
        """Initialize search engines and content fetcher."""
        for engine_type in self._engine_types:
            try:
                engine_cls = get_search_engine_class(engine_type)
                self._engine_classes[engine_type] = engine_cls

                # Create engine instance
                if engine_type == 'exa':
                    self._engines[engine_type] = engine_cls(
                        api_key=self._api_keys.get('exa'))
                elif engine_type == 'serpapi':
                    self._engines[engine_type] = engine_cls(
                        api_key=self._api_keys.get('serpapi'),
                        provider=self._serpapi_provider,
                    )
                else:  # arxiv
                    self._engines[engine_type] = engine_cls()

                logger.info(f'Initialized search engine: {engine_type}')
            except Exception as e:
                logger.warning(
                    f'Failed to initialize {engine_type} engine: {e}')

        if not self._engines:
            raise RuntimeError('No search engines could be initialized')

        self._content_fetcher = get_content_fetcher(
            self._fetcher_type,
            timeout=self._fetch_timeout,
            retries=self._fetch_retries,
        )
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_concurrent_fetch)

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None
        self._engines.clear()
        self._engine_classes.clear()

    def _get_tool_name_to_engine_map(self) -> Dict[str, str]:
        """Build mapping from tool_name to engine_type."""
        mapping = {}
        for engine_type in self._engine_types:
            tool_name = ENGINE_TOOL_NAMES.get(engine_type)
            if tool_name:
                mapping[tool_name] = engine_type
        # Add 'web_search' as fallback to first engine
        if self._engine_types:
            mapping['web_search'] = self._engine_types[0]
        return mapping

    async def _get_tools_inner(self) -> Dict[str, Any]:
        """Generate tool definitions dynamically based on configured engines."""
        tools: List[Tool] = []

        for engine_type in self._engine_types:
            engine_cls = self._engine_classes.get(engine_type)
            if not engine_cls:
                continue

            # Get engine's tool definition
            tool_def = engine_cls.get_tool_definition(
                server_name=self.SERVER_NAME)

            # Add fetch_content parameter if content fetcher is available
            if self._content_fetcher:
                tool_params = dict(tool_def.get('parameters', {}))
                tool_props = dict(tool_params.get('properties', {}))
                tool_props['fetch_content'] = {
                    'type':
                    'boolean',
                    'description':
                    ('Whether to fetch and parse full page content. '
                     'Set to false for faster results with only titles/snippets. '
                     f'Default is {self._fetch_content_default}. Suggested to set to True.'
                     ),
                }
                tool_params['properties'] = tool_props
                tool_def['parameters'] = tool_params

            tools.append(tool_def)

        # Add fetch_page tool (always available)
        tools.append(
            Tool(
                tool_name='fetch_page',
                server_name=self.SERVER_NAME,
                description=('Fetch and parse a single web page by URL. '
                             'Use this when you have a specific URL to read.'),
                parameters={
                    'type': 'object',
                    'properties': {
                        'url': {
                            'type': 'string',
                            'description': 'The URL to fetch.',
                        },
                    },
                    'required': ['url'],
                },
            ))

        return {self.SERVER_NAME: tools}

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        """Route tool calls to appropriate handler."""
        if tool_name == 'fetch_page':
            return await self.fetch_page(**(tool_args or {}))

        # Map tool_name to engine_type
        tool_to_engine = self._get_tool_name_to_engine_map()
        engine_type = tool_to_engine.get(tool_name)

        if not engine_type or engine_type not in self._engines:
            return _json_dumps({
                'status':
                'error',
                'message':
                f'Unknown tool: {tool_name}. Available: {list(tool_to_engine.keys())}'
            })

        return await self._execute_search(engine_type, tool_args or {})

    def _fetch_content_sync(self, url: str) -> Dict[str, Any]:
        """Synchronous content fetch wrapper."""
        try:
            content, metadata = self._content_fetcher.fetch(url)

            # # Try to extract date from content if not provided
            # published_at = _extract_date_from_text(content) if content else None

            result = {
                'url': url,
                'content': content,
                # 'published_at': published_at,
                'fetch_success': bool(content),
                **metadata,
            }

            # Optional chunking
            if self._enable_chunking and content:
                chunks = chunk_text_simple(
                    content,
                    chunk_size=self._chunk_size,
                    overlap=self._chunk_overlap,
                    prefix=f'{hash(url) & 0xFFFFFF:06x}_')
                result['chunks'] = [{
                    'chunk_id': c.chunk_id,
                    'content': c.content
                } for c in chunks]

            return result
        except Exception as e:
            logger.warning(f'Failed to fetch {url}: {e}')
            return {
                'url': url,
                'content': '',
                'fetch_success': False,
                'error': str(e),
            }

    async def _fetch_content_async(self, url: str) -> Dict[str, Any]:
        """Async wrapper for content fetching."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor,
                                          self._fetch_content_sync, url)

    async def _fetch_multiple_async(self,
                                    urls: List[str]) -> List[Dict[str, Any]]:
        """Fetch multiple URLs concurrently with semaphore."""
        semaphore = asyncio.Semaphore(self._max_concurrent_fetch)

        async def _bounded_fetch(url: str) -> Dict[str, Any]:
            async with semaphore:
                return await self._fetch_content_async(url)

        tasks = [_bounded_fetch(url) for url in urls]
        return await asyncio.gather(*tasks)

    def _do_search(self, engine_type: str, engine: SearchEngine,
                   engine_cls: Type[SearchEngine],
                   tool_args: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Perform search using the specified engine and return raw results."""
        try:
            # Build request using engine's method
            request = engine_cls.build_request_from_args(**tool_args)
            result = engine.search(request)
            return result.to_list()
        except Exception as e:
            logger.error(f'Search failed ({engine_type}): {e}')
            return []

    async def _execute_search(self, engine_type: str,
                              tool_args: Dict[str, Any]) -> str:
        """
        Execute search using the specified engine.

        Args:
            engine_type: The engine type to use
            tool_args: Arguments from the tool call
        """
        query = tool_args.get('query', '').strip()
        if not query:
            return _json_dumps({
                'status': 'error',
                'message': 'Query is required.'
            })

        # Get fetch_content preference, default to configured value
        fetch_content = tool_args.pop('fetch_content',
                                      self._fetch_content_default)

        if 'num_results' not in tool_args or tool_args['num_results'] is None:
            tool_args[
                'num_results'] = 10 if engine_type == 'arxiv' else self._max_results

        engine = self._engines.get(engine_type)
        engine_cls = self._engine_classes.get(engine_type)

        if not engine or not engine_cls:
            return _json_dumps({
                'status':
                'error',
                'message':
                f'Engine {engine_type} not initialized.'
            })

        # Perform search
        loop = asyncio.get_event_loop()
        search_results = await loop.run_in_executor(self._executor,
                                                    self._do_search,
                                                    engine_type, engine,
                                                    engine_cls, tool_args)

        if not search_results:
            return _json_dumps({
                'status': 'ok',
                'query': query,
                'engine': engine_type,
                'count': 0,
                'results': [],
                'message': 'No search results found.',
            })

        # Optionally fetch content
        if fetch_content and self._content_fetcher:
            urls = [r.get('url') for r in search_results if r.get('url')]
            if urls:
                fetch_results = await self._fetch_multiple_async(urls)

                # Merge search metadata with fetched content
                url_to_fetch = {r['url']: r for r in fetch_results}
                for sr in search_results:
                    url = sr.get('url')
                    if url and url in url_to_fetch:
                        fetched = url_to_fetch[url]
                        sr['content'] = fetched.get('content', '')
                        sr['fetch_success'] = fetched.get(
                            'fetch_success', False)
                        if fetched.get('published_at'
                                       ) and not sr.get('published_date'):
                            sr['published_at'] = fetched['published_at']
                        if self._enable_chunking and fetched.get('chunks'):
                            sr['chunks'] = fetched['chunks']

        # Format output
        output_results = []
        for sr in search_results:
            item = {
                'url':
                sr.get('url', ''),
                'title':
                sr.get('title', ''),
                'published_at':
                sr.get('published_date') or sr.get('published_at', ''),
            }

            # Preserve arXiv-specific metadata (aligned with arxiv-mcp-server)
            if engine_type == 'arxiv':
                item.update({
                    'id':
                    sr.get('arxiv_id', '') or '',  # arXiv short id
                    'abs_url':
                    sr.get('id', '') or '',  # entry_id (abstract page)
                    'abstract':
                    sr.get('summary', '') or '',
                    'authors':
                    sr.get('authors', []) or [],
                    'categories':
                    sr.get('categories', []) or [],
                    'resource_uri':
                    sr.get('resource_uri', '') or '',
                    'published':
                    sr.get('published_date') or sr.get('published_at', ''),
                })

            if fetch_content:
                item['content'] = sr.get('content', '')
                item['fetch_success'] = sr.get('fetch_success', False)
                if self._enable_chunking and sr.get('chunks'):
                    item['chunks'] = sr['chunks']

            if not engine_type == 'arxiv':
                # Include snippet if available
                item['summary'] = sr.get('summary', '')
                output_results.append(item)

        return _json_dumps({
            'status': 'ok',
            'query': query,
            'engine': engine_type,
            'count': len(output_results),
            'results': output_results,
        })

    async def fetch_page(self, url: str) -> str:
        """Fetch and parse a single web page."""
        if not url or not url.strip():
            return _json_dumps({
                'status': 'error',
                'message': 'URL is required.'
            })

        result = await self._fetch_content_async(url.strip())

        return _json_dumps({
            'status':
            'ok' if result.get('fetch_success') else 'error',
            'url':
            url,
            'content':
            result.get('content', ''),
            'published_at':
            result.get('published_at', ''),
            'fetch_success':
            result.get('fetch_success', False),
            'chunks':
            result.get('chunks') if self._enable_chunking else None,
        })

    # Backward compatibility aliases
    async def web_search(self,
                         query: str,
                         num_results: Optional[int] = None,
                         fetch_content: bool = True,
                         **kwargs) -> str:
        """
        Search the web and optionally fetch page content.

        This method is kept for backward compatibility.
        It uses the first configured engine.
        """
        # Use first engine as default
        engine_type = self._engine_types[0] if self._engine_types else 'arxiv'

        tool_args = {
            'query': query,
            'num_results': num_results,
            'fetch_content': fetch_content,
            **kwargs
        }

        return await self._execute_search(engine_type, tool_args)

    # Engine-specific search methods (Explicit methods provide better IDE support)
    async def exa_search(self, **kwargs) -> str:
        """Search using Exa engine."""
        return await self._execute_search('exa', kwargs)

    async def arxiv_search(self, **kwargs) -> str:
        """Search using arXiv engine."""
        return await self._execute_search('arxiv', kwargs)

    async def serpapi_search(self, **kwargs) -> str:
        """Search using SerpApi engine."""
        return await self._execute_search('serpapi', kwargs)
