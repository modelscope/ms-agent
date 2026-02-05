# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Type

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.tools.jina_reader import JinaReaderConfig, fetch_single_text
from ms_agent.tools.search.content_optimizer import (ContentOptimizer,
                                                     ContentOptimizerConfig,
                                                     SearchResultReranker)
from ms_agent.tools.search.search_base import ENGINE_TOOL_NAMES, SearchEngine
from ms_agent.utils.logger import get_logger
from ms_agent.utils.thread_util import DaemonThreadPoolExecutor

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

    # Process-wide (class-level) usage tracking for summarization calls.
    # This is intentionally separate from LLMAgent usage totals.
    _GLOBAL_SUMMARY_USAGE_LOCK = threading.Lock()
    _GLOBAL_SUMMARY_USAGE_TOTAL: Dict[str, int] = {
        'api_calls': 0,
        'prompt_tokens': 0,
        'completion_tokens': 0,
        'cached_tokens': 0,
        'cache_creation_input_tokens': 0,
        'pages': 0,
    }
    _GLOBAL_SUMMARY_USAGE_BY_MODEL: Dict[str, Dict[str, int]] = {}

    @classmethod
    def get_global_summarization_usage(cls) -> Dict[str, Any]:
        """Get process-wide summarization usage totals (best-effort)."""
        with cls._GLOBAL_SUMMARY_USAGE_LOCK:
            total = dict(cls._GLOBAL_SUMMARY_USAGE_TOTAL)
            by_model = {
                k: dict(v)
                for k, v in cls._GLOBAL_SUMMARY_USAGE_BY_MODEL.items()
            }
        total['total_tokens'] = total.get('prompt_tokens', 0) + total.get(
            'completion_tokens', 0)
        return {
            'total': total,
            'by_model': by_model,
        }

    @classmethod
    def log_global_summarization_usage(cls) -> None:
        """Log process-wide summarization totals once at end-of-run."""
        usage = cls.get_global_summarization_usage()
        total = usage.get('total', {}) or {}
        if not (total.get('prompt_tokens', 0) or total.get(
                'completion_tokens', 0) or total.get('api_calls', 0)):
            return
        logger.info(
            '[web_search_summarization_usage_process_total] '
            f"pages={total.get('pages', 0)} "
            f"api_calls={total.get('api_calls', 0)} "
            f"prompt_tokens={total.get('prompt_tokens', 0)} "
            f"completion_tokens={total.get('completion_tokens', 0)} "
            f"total_tokens={total.get('total_tokens', 0)} "
            f"cached_tokens={total.get('cached_tokens', 0)} "
            f"cache_creation_input_tokens={total.get('cache_creation_input_tokens', 0)}"
        )
        by_model = usage.get('by_model', {}) or {}
        # Keep per-model logs concise; only print when there are multiple models.
        if len(by_model) > 1:
            for model, m in sorted(by_model.items(), key=lambda kv: kv[0]):
                logger.info(
                    '[web_search_summarization_usage_process_total_by_model] '
                    f'model={model} '
                    f"pages={m.get('pages', 0)} "
                    f"api_calls={m.get('api_calls', 0)} "
                    f"prompt_tokens={m.get('prompt_tokens', 0)} "
                    f"completion_tokens={m.get('completion_tokens', 0)} "
                    f"total_tokens={m.get('prompt_tokens', 0) + m.get('completion_tokens', 0)} "
                    f"cached_tokens={m.get('cached_tokens', 0)} "
                    f"cache_creation_input_tokens={m.get('cache_creation_input_tokens', 0)}"
                )

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
        self._max_concurrent_summarization = int(
            getattr(tool_cfg, 'max_concurrent_summarization', 5)
            or 5) if tool_cfg else 5

        # Content optimization config (summarization & reranking)
        self._enable_summarization = bool(
            getattr(tool_cfg, 'enable_summarization',
                    False)) if tool_cfg else False
        self._summarizer_model = getattr(
            tool_cfg, 'summarizer_model',
            'qwen-flash') if tool_cfg else 'qwen-flash'
        self._summarizer_base_url = getattr(
            tool_cfg, 'summarizer_base_url',
            'https://dashscope.aliyuncs.com/compatible-mode/v1'
        ) if tool_cfg else 'https://dashscope.aliyuncs.com/compatible-mode/v1'
        self._summarizer_api_key = getattr(tool_cfg, 'summarizer_api_key',
                                           None) if tool_cfg else None
        self._max_content_chars = int(
            getattr(tool_cfg, 'max_content_chars', 500000)
            or 500000) if tool_cfg else 500000
        self._summarizer_max_workers = int(
            getattr(tool_cfg, 'summarizer_max_workers', 5)
            or 5) if tool_cfg else 5
        self._summarization_timeout = float(
            getattr(tool_cfg, 'summarization_timeout', 90.0)
            or 90.0) if tool_cfg else 90.0

        # Reranking config
        self._enable_rerank = bool(getattr(tool_cfg, 'enable_rerank',
                                           False)) if tool_cfg else False
        self._rerank_top_k = int(getattr(tool_cfg, 'rerank_top_k', 3)
                                 or 3) if tool_cfg else 3

        # Task context for summarization (can be set dynamically)
        self._task_context = getattr(tool_cfg, 'task_context',
                                     '') if tool_cfg else ''

        # Runtime instances (lazy init)
        self._engines: Dict[str, SearchEngine] = {
        }  # engine_type -> engine instance
        self._engine_classes: Dict[str, Type[SearchEngine]] = {
        }  # engine_type -> engine class
        self._content_fetcher: Optional[ContentFetcher] = None
        self._content_optimizer: Optional[ContentOptimizer] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        # Summarization token usage tracking (separate from LLMAgent usage)
        self._summary_usage_total: Dict[str, int] = {
            'api_calls': 0,
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'cached_tokens': 0,
            'cache_creation_input_tokens': 0,
        }
        self._summary_usage_model: str = ''

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
        # Use daemon threads: tool-call timeouts can cancel the awaiting coroutine,
        # but not the underlying sync network calls running in executor threads.
        self._executor = DaemonThreadPoolExecutor(
            max_workers=self._max_concurrent_fetch,
            thread_name_prefix='web_search_',
        )

        # Initialize content optimizer if summarization or reranking is enabled
        if self._enable_summarization or self._enable_rerank:
            optimizer_config = ContentOptimizerConfig(
                summarizer_model=self._summarizer_model,
                summarizer_base_url=self._summarizer_base_url,
                summarizer_api_key=(self._summarizer_api_key
                                    or os.getenv('DASHSCOPE_API_KEY')
                                    or os.getenv('OPENAI_API_KEY')),
                max_content_chars=self._max_content_chars,
                summarizer_max_workers=self._summarizer_max_workers,
                summarization_timeout=self._summarization_timeout,
                enable_rerank=self._enable_rerank,
                rerank_top_k=self._rerank_top_k,
            )
            self._content_optimizer = ContentOptimizer(optimizer_config)
            if self._enable_summarization:
                await self._content_optimizer.initialize()
                logger.info(
                    f'Content optimizer initialized with model: {self._summarizer_model}'
                )
            else:
                logger.info(
                    'Content reranking enabled (summarization disabled)')

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self._executor:
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                # Python<3.9 compatibility (cancel_futures not supported)
                self._executor.shutdown(wait=False)
            self._executor = None
        if self._content_optimizer:
            await self._content_optimizer.cleanup()
            self._content_optimizer = None
        self._engines.clear()
        self._engine_classes.clear()
        # Optional: instance-level totals can be noisy when multiple sub-agents
        # create their own WebSearchTool instances. Default off; use env var to enable.
        if os.getenv('MS_AGENT_WEB_SEARCH_LOG_INSTANCE_SUMMARY_USAGE',
                     '').lower() in ('1', 'true', 'yes'):
            if (self._summary_usage_total.get('prompt_tokens', 0)
                    or self._summary_usage_total.get('completion_tokens', 0)
                    or self._summary_usage_total.get('api_calls', 0)):
                model = self._summary_usage_model or self._summarizer_model
                logger.info(
                    '[web_search_summarization_usage_total] '
                    f'model={model} '
                    f"api_calls={self._summary_usage_total.get('api_calls', 0)} "
                    f"prompt_tokens={self._summary_usage_total.get('prompt_tokens', 0)} "
                    f"completion_tokens={self._summary_usage_total.get('completion_tokens', 0)} "
                    f"total_tokens={self._summary_usage_total.get('prompt_tokens', 0) + self._summary_usage_total.get('completion_tokens', 0)} "  # noqa: E501
                    f"cached_tokens={self._summary_usage_total.get('cached_tokens', 0)} "
                    f"cache_creation_input_tokens={self._summary_usage_total.get('cache_creation_input_tokens', 0)}"  # noqa: E501
                )

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
        The search pipeline with optimization:
        1. Execute search query
        2. (Optional) Rerank results by relevance before fetching
        3. Fetch page content for top results
        4. (Optional) Summarize content using fast LLM
        5. Format and return results

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

        # Get task context for summarization (can be passed in tool_args)
        task_context = tool_args.pop('task_context', self._task_context)

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

        original_count = len(search_results)

        # Step 2: Rerank results before fetching content (if enabled)
        # This reduces the number of pages to fetch and summarize
        if self._enable_rerank and self._content_optimizer:
            search_results = self._content_optimizer.rerank_results(
                search_results,
                query,
                top_k=self._rerank_top_k,
            )
            logger.info(
                f'Reranked {original_count} results to top {len(search_results)} '
                f'for query: {query[:50]}...')

        # Step 3: Fetch content for (filtered) results
        if fetch_content and self._content_fetcher:
            search_results = SearchResultReranker.deduplicate_by_url(
                search_results)
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

        # Step 4: Summarize content (if enabled)
        summarization_usage: Optional[Dict[str, Any]] = None
        if self._enable_summarization and self._content_optimizer and fetch_content:
            # Collect contents that need summarization
            contents_to_summarize = [
                (sr.get('url', ''), sr.get('content', ''))
                for sr in search_results
                if sr.get('content') and sr.get('fetch_success', False)
            ]

            if contents_to_summarize:
                logger.info(
                    f'Summarizing {len(contents_to_summarize)} pages...')

                # Summarize all contents in parallel + collect usage
                summaries, summarization_usage = await self._content_optimizer.summarize_contents_with_usage(
                    contents_to_summarize,
                    task_context=task_context,
                    max_concurrent=min(self._max_concurrent_summarization,
                                       len(contents_to_summarize)),
                )

                # Update global usage totals for this tool instance (independent from LLMAgent)
                try:
                    if summarization_usage:
                        self._summary_usage_model = str(
                            summarization_usage.get('model')
                            or self._summary_usage_model or '')
                        self._summary_usage_total['api_calls'] += int(
                            summarization_usage.get('api_calls', 0) or 0)
                        self._summary_usage_total['prompt_tokens'] += int(
                            summarization_usage.get('prompt_tokens', 0) or 0)
                        self._summary_usage_total['completion_tokens'] += int(
                            summarization_usage.get('completion_tokens', 0)
                            or 0)
                        self._summary_usage_total['cached_tokens'] += int(
                            summarization_usage.get('cached_tokens', 0) or 0)
                        self._summary_usage_total[
                            'cache_creation_input_tokens'] += int(
                                summarization_usage.get(
                                    'cache_creation_input_tokens', 0) or 0)
                        # Process-wide totals (thread-safe; sub-agents may run in background threads)
                        model = str(
                            summarization_usage.get('model')
                            or self._summarizer_model)
                        with WebSearchTool._GLOBAL_SUMMARY_USAGE_LOCK:
                            WebSearchTool._GLOBAL_SUMMARY_USAGE_TOTAL[
                                'pages'] += int(
                                    summarization_usage.get('pages', 0) or 0)
                            WebSearchTool._GLOBAL_SUMMARY_USAGE_TOTAL[
                                'api_calls'] += int(
                                    summarization_usage.get('api_calls', 0)
                                    or 0)
                            WebSearchTool._GLOBAL_SUMMARY_USAGE_TOTAL[
                                'prompt_tokens'] += int(
                                    summarization_usage.get(
                                        'prompt_tokens', 0) or 0)
                            WebSearchTool._GLOBAL_SUMMARY_USAGE_TOTAL[
                                'completion_tokens'] += int(
                                    summarization_usage.get(
                                        'completion_tokens', 0) or 0)
                            WebSearchTool._GLOBAL_SUMMARY_USAGE_TOTAL[
                                'cached_tokens'] += int(
                                    summarization_usage.get(
                                        'cached_tokens', 0) or 0)
                            WebSearchTool._GLOBAL_SUMMARY_USAGE_TOTAL[
                                'cache_creation_input_tokens'] += int(
                                    summarization_usage.get(
                                        'cache_creation_input_tokens', 0) or 0)
                            m = WebSearchTool._GLOBAL_SUMMARY_USAGE_BY_MODEL.setdefault(
                                model, {
                                    'pages': 0,
                                    'api_calls': 0,
                                    'prompt_tokens': 0,
                                    'completion_tokens': 0,
                                    'cached_tokens': 0,
                                    'cache_creation_input_tokens': 0,
                                })
                            m['pages'] += int(
                                summarization_usage.get('pages', 0) or 0)
                            m['api_calls'] += int(
                                summarization_usage.get('api_calls', 0) or 0)
                            m['prompt_tokens'] += int(
                                summarization_usage.get('prompt_tokens', 0)
                                or 0)
                            m['completion_tokens'] += int(
                                summarization_usage.get(
                                    'completion_tokens', 0) or 0)
                            m['cached_tokens'] += int(
                                summarization_usage.get('cached_tokens', 0)
                                or 0)
                            m['cache_creation_input_tokens'] += int(
                                summarization_usage.get(
                                    'cache_creation_input_tokens', 0) or 0)
                        logger.info(
                            '[web_search_summarization_usage] '
                            f"model={summarization_usage.get('model', self._summarizer_model)} "
                            f"pages={summarization_usage.get('pages', 0)} "
                            f"api_calls={summarization_usage.get('api_calls', 0)} "
                            f"prompt_tokens={summarization_usage.get('prompt_tokens', 0)} "
                            f"completion_tokens={summarization_usage.get('completion_tokens', 0)} "
                            f"total_tokens={summarization_usage.get('total_tokens', 0)} "
                            f"cached_tokens={summarization_usage.get('cached_tokens', 0)} "
                            f"cache_creation_input_tokens={summarization_usage.get('cache_creation_input_tokens', 0)}"
                        )
                except Exception as e:
                    logger.warning(
                        f'Failed to record summarization usage: {e}')

                # Replace original content with summaries
                for sr in search_results:
                    url = sr.get('url', '')
                    if url in summaries:
                        original_len = len(sr.get('content', ''))
                        sr['content'] = summaries[url]
                        sr['content_summarized'] = True
                        sr['original_content_length'] = original_len
                        logger.debug(
                            f'Summarized content for {url[:50]}: '
                            f"{original_len} -> {len(sr['content'])} chars")

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
                # Add summarization metadata if applicable
                if sr.get('content_summarized'):
                    item['content_summarized'] = True
                    item['original_content_length'] = sr.get(
                        'original_content_length', 0)
                if self._enable_chunking and sr.get('chunks'):
                    item['chunks'] = sr['chunks']

            if engine_type != 'arxiv':
                # Include snippet if available for non-arxiv engines
                item['summary'] = sr.get('summary', '')

            # Add item to results for all engines
            output_results.append(item)

        # Build response with optimization metadata
        response = {
            'status': 'ok',
            'query': query,
            'engine': engine_type,
            'count': len(output_results),
            'results': output_results,
        }

        # Add optimization info
        if self._enable_rerank or self._enable_summarization:
            response['optimization'] = {
                'rerank_enabled': self._enable_rerank,
                'summarization_enabled': self._enable_summarization,
            }
            if self._enable_rerank:
                response['optimization'][
                    'original_result_count'] = original_count
                response['optimization']['filtered_to'] = len(output_results)
            if self._enable_summarization:
                summarized_count = sum(1 for r in output_results
                                       if r.get('content_summarized'))
                response['optimization']['pages_summarized'] = summarized_count
                # Include per-call usage + cumulative totals (separate from LLMAgent usage)
                if summarization_usage:
                    response['optimization'][
                        'summarization_usage'] = summarization_usage
                response['optimization']['summarization_usage_total'] = {
                    'model':
                    self._summary_usage_model or self._summarizer_model,
                    'api_calls':
                    self._summary_usage_total.get('api_calls', 0),
                    'prompt_tokens':
                    self._summary_usage_total.get('prompt_tokens', 0),
                    'completion_tokens':
                    self._summary_usage_total.get('completion_tokens', 0),
                    'total_tokens':
                    (self._summary_usage_total.get('prompt_tokens', 0)
                     + self._summary_usage_total.get('completion_tokens', 0)),
                    'cached_tokens':
                    self._summary_usage_total.get('cached_tokens', 0),
                    'cache_creation_input_tokens':
                    self._summary_usage_total.get(
                        'cache_creation_input_tokens', 0),
                }
                # Process-wide totals so far (across all WebSearchTool instances)
                response['optimization'][
                    'summarization_usage_process_total'
                ] = WebSearchTool.get_global_summarization_usage()  # yapf: disable

        return _json_dumps(response)

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
