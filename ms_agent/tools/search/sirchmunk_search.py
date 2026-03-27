# Copyright (c) ModelScope Contributors. All rights reserved.
"""Sirchmunk backend for the ``localsearch`` tool.

Configuration lives under ``tools.localsearch`` (same namespace as other tools).
Legacy top-level ``knowledge_search`` is still accepted for backward compatibility.
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger
from omegaconf import DictConfig


def _paths_from_block(block: Any) -> List[str]:
    if block is None:
        return []
    paths = block.get('paths', []) if hasattr(block, 'get') else []
    if isinstance(paths, str):
        paths = [paths] if str(paths).strip() else []
    out: List[str] = []
    for p in paths or []:
        if p is None or not str(p).strip():
            continue
        out.append(str(p).strip())
    return out


def effective_localsearch_settings(config: DictConfig) -> Optional[Any]:
    """Resolve the active localsearch / sirchmunk settings node.

    Precedence: ``tools.localsearch`` with non-empty ``paths``, else legacy
    ``knowledge_search`` with non-empty ``paths``. Returns ``None`` if local
    search is not configured.
    """
    tools = getattr(config, 'tools', None)
    tl = None
    if tools is not None:
        tl = tools.get('localsearch') if hasattr(tools, 'get') else getattr(
            tools, 'localsearch', None)
    ks = getattr(config, 'knowledge_search', None)

    if tl is not None and _paths_from_block(tl):
        return tl
    if ks is not None and _paths_from_block(ks):
        return ks
    return None


class SirchmunkSearch:
    """Sirchmunk-based local search (used by :class:`LocalSearchTool`).

    Configure in yaml under ``tools.localsearch`` (recommended), for example::

        tools:
          localsearch:
            paths:
              - ./src
              - ./docs
            work_path: ./.sirchmunk
            embedding_model: text-embedding-3-small
            cluster_sim_threshold: 0.85
            cluster_sim_top_k: 3
            reuse_knowledge: true
            mode: FAST

    Legacy: the same keys may be placed under top-level ``knowledge_search``.

    Args:
        config: Full agent config; sirchmunk options read from the effective
            block returned by :func:`effective_localsearch_settings`.
    """

    def __init__(self, config: DictConfig):
        self._validate_config(config)
        rag_config = effective_localsearch_settings(config)
        assert rag_config is not None

        paths = rag_config.get('paths', [])
        if isinstance(paths, str):
            paths = [paths]
        self.search_paths: List[str] = [
            str(Path(p).expanduser().resolve()) for p in paths
        ]

        _work_path = rag_config.get('work_path', './.sirchmunk')
        self.work_path: Path = Path(_work_path).expanduser().resolve()

        self.reuse_knowledge = rag_config.get('reuse_knowledge', True)
        self.cluster_sim_threshold = rag_config.get('cluster_sim_threshold',
                                                    0.85)
        self.cluster_sim_top_k = rag_config.get('cluster_sim_top_k', 3)
        self.search_mode = rag_config.get('mode', 'FAST')
        self.max_loops = rag_config.get('max_loops', 10)
        self.max_token_budget = rag_config.get('max_token_budget', 128000)

        self.llm_api_key = rag_config.get('llm_api_key', None)
        self.llm_base_url = rag_config.get('llm_base_url', None)
        self.llm_model_name = rag_config.get('llm_model_name', None)

        if (self.llm_api_key is None or self.llm_base_url is None
                or self.llm_model_name is None):
            llm_config = config.get('llm', {})
            if llm_config:
                service = getattr(llm_config, 'service', 'dashscope')
                if self.llm_api_key is None:
                    self.llm_api_key = getattr(llm_config,
                                               f'{service}_api_key', None)
                if self.llm_base_url is None:
                    self.llm_base_url = getattr(llm_config,
                                                f'{service}_base_url', None)
                if self.llm_model_name is None:
                    self.llm_model_name = getattr(llm_config, 'model', None)

        self.embedding_model_id = rag_config.get('embedding_model', None)
        self.embedding_model_cache_dir = rag_config.get(
            'embedding_model_cache_dir', None)

        self._searcher = None
        self._initialized = False
        self._cluster_cache_hit = False
        self._cluster_cache_hit_time: str | None = None
        self._last_search_result: List[Dict[str, Any]] | None = None

        self._log_callback = None
        self._search_logs: List[str] = []
        self._log_queue: asyncio.Queue | None = None
        self._streaming_callback: Callable | None = None

    def _validate_config(self, config: DictConfig):
        block = effective_localsearch_settings(config)
        if block is None:
            raise ValueError(
                'Missing localsearch configuration. Add '
                '`tools.localsearch` with non-empty `paths` (or legacy '
                '`knowledge_search.paths`).')
        paths = _paths_from_block(block)
        if not paths:
            raise ValueError(
                'tools.localsearch.paths (or legacy knowledge_search.paths) '
                'must be specified and non-empty')

    def resolve_tool_paths(
            self, paths: Optional[List[str]]) -> Optional[List[str]]:
        """Restrict per-call paths to configured search roots."""
        if not paths:
            return None
        roots = [Path(p).resolve() for p in self.search_paths]
        cleaned: List[str] = []
        for raw in paths:
            if raw is None or not str(raw).strip():
                continue
            p = Path(str(raw).strip()).expanduser().resolve()
            if not p.exists():
                logger.warning(f'localsearch: path does not exist, skipped: {p}')
                continue
            allowed = any(
                p == r or p.is_relative_to(r) for r in roots)
            if not allowed:
                logger.warning(
                    f'localsearch: path outside configured search roots, '
                    f'skipped: {p}')
                continue
            cleaned.append(str(p))
        return cleaned or None

    def _initialize_searcher(self):
        """Initialize the sirchmunk AgenticSearch instance."""
        if self._initialized:
            return

        try:
            from sirchmunk.llm.openai_chat import OpenAIChat
            from sirchmunk.search import AgenticSearch
            from sirchmunk.utils.embedding_util import EmbeddingUtil

            llm = OpenAIChat(
                api_key=self.llm_api_key,
                base_url=self.llm_base_url,
                model=self.llm_model_name,
                max_retries=3,
                log_callback=self._log_callback_wrapper(),
            )

            embedding_model_id = (
                self.embedding_model_id if self.embedding_model_id else None)
            embedding_cache_dir = (
                self.embedding_model_cache_dir
                if self.embedding_model_cache_dir else None)
            embedding = EmbeddingUtil(
                model_id=embedding_model_id, cache_dir=embedding_cache_dir)

            self._searcher = AgenticSearch(
                llm=llm,
                embedding=embedding,
                work_path=str(self.work_path),
                paths=self.search_paths,
                verbose=True,
                reuse_knowledge=self.reuse_knowledge,
                cluster_sim_threshold=self.cluster_sim_threshold,
                cluster_sim_top_k=self.cluster_sim_top_k,
                log_callback=self._log_callback_wrapper(),
            )

            self._initialized = True
            logger.info(
                f'SirschmunkSearch initialized with paths: {self.search_paths}'
            )

        except ImportError as e:
            raise ImportError(
                f'Failed to import sirchmunk: {e}. '
                'Please install sirchmunk: pip install sirchmunk')
        except Exception as e:
            raise RuntimeError(f'Failed to initialize SirchmunkSearch: {e}')

    def _log_callback_wrapper(self):
        """Create a callback wrapper to capture search logs.

        The sirchmunk LogCallback signature is:
            (level: str, message: str, end: str, flush: bool) -> None
        See sirchmunk/utils/log_utils.py for reference.
        """

        def log_callback(
            level: str,
            message: str,
            end: str = '\n',
            flush: bool = False,
        ):
            log_entry = f'[{level.upper()}] {message}'
            self._search_logs.append(log_entry)
            if self._streaming_callback:
                asyncio.create_task(self._streaming_callback(log_entry))

        return log_callback

    async def add_documents(self, documents: List[str]) -> bool:
        """Add documents to the search index.

        Note: Sirchmunk works by scanning existing files in the specified paths.
        This method is provided for RAG interface compatibility but doesn't
        directly add documents. Instead, documents should be saved to files
        within the search paths.

        Args:
            documents (List[str]): List of document contents to add.

        Returns:
            bool: True if successful (for interface compatibility).
        """
        logger.warning(
            'SirchmunkSearch does not support direct document addition. '
            'Documents should be saved to files within the configured search paths.'
        )
        if self._searcher and hasattr(self._searcher, 'knowledge_base'):
            try:
                await self._searcher.knowledge_base.refresh()
                return True
            except Exception as e:
                logger.error(f'Failed to refresh knowledge base: {e}')
                return False
        return True

    async def add_documents_from_files(self, file_paths: List[str]) -> bool:
        """Add documents from file paths.

        Args:
            file_paths (List[str]): List of file paths to scan.

        Returns:
            bool: True if successful.
        """
        self._initialize_searcher()

        if self._searcher and hasattr(self._searcher, 'scan_directory'):
            try:
                for file_path in file_paths:
                    if Path(file_path).exists():
                        await self._searcher.scan_directory(
                            str(Path(file_path).parent))
                return True
            except Exception as e:
                logger.error(f'Failed to scan files: {e}')
                return False
        return True

    async def retrieve(self,
                       query: str,
                       limit: int = 5,
                       score_threshold: float = 0.7,
                       **filters) -> List[Dict[str, Any]]:
        """Retrieve relevant documents using sirchmunk.

        Args:
            query (str): The search query.
            limit (int): Maximum number of results to return.
            score_threshold (float): Minimum relevance score threshold.
            **filters: Additional filters (mode, max_loops, etc.).

        Returns:
            List[Dict[str, Any]]: List of search results with 'text', 'score',
                                  'metadata' fields.
        """
        self._initialize_searcher()
        self._search_logs.clear()

        try:
            mode = filters.get('mode', self.search_mode)
            max_loops = filters.get('max_loops', self.max_loops)
            max_token_budget = filters.get('max_token_budget',
                                           self.max_token_budget)

            result = await self._searcher.search(
                query=query,
                mode=mode,
                max_loops=max_loops,
                max_token_budget=max_token_budget,
                return_context=True,
            )

            self._cluster_cache_hit = False
            self._cluster_cache_hit_time = None
            if hasattr(result, 'cluster') and result.cluster is not None:
                self._cluster_cache_hit = any(
                    'Found similar cluster' in entry
                    or 'Reused existing knowledge cluster' in entry
                    for entry in self._search_logs
                )
                if hasattr(result.cluster, 'last_modified'):
                    self._cluster_cache_hit_time = getattr(
                        result.cluster, 'last_modified', None)

            return self._parse_search_result(result, score_threshold, limit)

        except Exception as e:
            logger.error(f'SirschmunkSearch retrieve failed: {e}')
            return []

    async def query(
        self,
        query: str,
        *,
        paths: Optional[List[str]] = None,
        mode: Optional[str] = None,
        max_depth: Optional[int] = None,
        top_k_files: Optional[int] = None,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ) -> str:
        """Query sirchmunk and return a synthesized answer (or filename hits).

        Optional arguments are forwarded to ``AgenticSearch.search`` where supported.
        ``paths`` must already be restricted to configured search roots (see
        :meth:`resolve_tool_paths`).

        Args:
            query: The search query.
            paths: Override search roots (subset of configured paths), or None.
            mode: ``FAST``, ``DEEP``, or ``FILENAME_ONLY``; None uses config default.
            max_depth: Directory depth cap for filesystem search.
            top_k_files: Max files for evidence / filename ranking.
            include: Glob patterns to include (e.g. ``*.py``).
            exclude: Glob patterns to exclude (e.g. ``node_modules``).

        Returns:
            Answer string, or JSON string for ``FILENAME_ONLY`` list results.
        """
        self._initialize_searcher()
        self._search_logs.clear()

        try:
            mode_eff = mode if mode is not None else self.search_mode
            if isinstance(mode_eff, str):
                mode_eff = mode_eff.strip().upper()
            allowed_modes = ('FAST', 'DEEP', 'FILENAME_ONLY')
            if mode_eff not in allowed_modes:
                return (
                    f'Invalid mode {mode_eff!r}; use one of {allowed_modes}.')

            kw: Dict[str, Any] = dict(
                query=query,
                paths=paths,
                mode=mode_eff,
                max_loops=self.max_loops,
                max_token_budget=self.max_token_budget,
                return_context=True,
            )
            if max_depth is not None:
                kw['max_depth'] = max_depth
            if top_k_files is not None:
                kw['top_k_files'] = top_k_files
            if include is not None:
                kw['include'] = include
            if exclude is not None:
                kw['exclude'] = exclude

            result = await self._searcher.search(**kw)

            if isinstance(result, list):
                self._cluster_cache_hit = False
                self._cluster_cache_hit_time = None
                self._last_search_result = []
                for item in result[:20]:
                    if isinstance(item, dict):
                        src = (item.get('path') or item.get('file_path')
                               or item.get('file') or '')
                        self._last_search_result.append({
                            'text':
                            json.dumps(item, ensure_ascii=False),
                            'score':
                            1.0,
                            'metadata': {
                                'source': str(src),
                                'type': 'filename_match',
                            },
                        })
                return json.dumps(result, ensure_ascii=False, indent=2)

            self._cluster_cache_hit = False
            self._cluster_cache_hit_time = None
            if hasattr(result, 'cluster') and result.cluster is not None:
                # Detect cluster reuse from search logs: sirchmunk emits
                # "[SUCCESS] Found similar cluster: ..." or
                # "[SUCCESS] Reused existing knowledge cluster" when a cached
                # cluster is reused.  KnowledgeCluster has no _reused_from_cache
                # attribute, so log-based detection is the correct approach.
                self._cluster_cache_hit = any(
                    'Found similar cluster' in entry
                    or 'Reused existing knowledge cluster' in entry
                    for entry in self._search_logs
                )
                if hasattr(result.cluster, 'last_modified'):
                    self._cluster_cache_hit_time = getattr(
                        result.cluster, 'last_modified', None)

            self._last_search_result = self._parse_search_result(
                result, score_threshold=0.7, limit=5)

            if hasattr(result, 'answer') and getattr(result, 'answer',
                                                       None) is not None:
                return result.answer

            if isinstance(result, str):
                return result

            return str(result)

        except Exception as e:
            logger.error(f'SirschmunkSearch query failed: {e}')
            return f'Query failed: {e}'

    def _parse_search_result(self, result: Any, score_threshold: float,
                             limit: int) -> List[Dict[str, Any]]:
        """Parse sirchmunk search result into standard format.

        Args:
            result: The raw search result from sirchmunk.
            score_threshold: Minimum score threshold.
            limit: Maximum number of results.

        Returns:
            List[Dict[str, Any]]: Parsed results.
        """
        results = []

        if hasattr(result, 'cluster') and result.cluster is not None:
            cluster = result.cluster
            for unit in cluster.evidences:
                score = getattr(cluster, 'confidence', 1.0)
                if score >= score_threshold:
                    text_parts = []
                    source = str(getattr(unit, 'file_or_url', 'unknown'))
                    for snippet in getattr(unit, 'snippets', []):
                        if isinstance(snippet, dict):
                            text_parts.append(snippet.get('snippet', ''))
                        else:
                            text_parts.append(str(snippet))

                    results.append({
                        'text':
                        '\n'.join(text_parts) if text_parts else getattr(
                            unit, 'summary', ''),
                        'score':
                        score,
                        'metadata': {
                            'source':
                            source,
                            'type':
                            getattr(unit, 'abstraction_level', 'text')
                            if hasattr(unit, 'abstraction_level') else 'text',
                        },
                    })

        elif hasattr(result, 'evidence_units'):
            for unit in result.evidence_units:
                score = getattr(unit, 'confidence', 1.0)
                if score >= score_threshold:
                    results.append({
                        'text':
                        str(unit.content)
                        if hasattr(unit, 'content') else str(unit),
                        'score':
                        score,
                        'metadata': {
                            'source': getattr(unit, 'source_file', 'unknown'),
                            'type': getattr(unit, 'abstraction_level', 'text'),
                        },
                    })

        elif isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    score = item.get('score', item.get('confidence', 1.0))
                    if score >= score_threshold:
                        results.append({
                            'text':
                            item.get('content', item.get('text', str(item))),
                            'score':
                            score,
                            'metadata':
                            item.get('metadata', {}),
                        })

        elif isinstance(result, dict):
            score = result.get('score', result.get('confidence', 1.0))
            if score >= score_threshold:
                results.append({
                    'text':
                    result.get('content', result.get('text', str(result))),
                    'score':
                    score,
                    'metadata':
                    result.get('metadata', {}),
                })

        results.sort(key=lambda x: x.get('score', 0), reverse=True)
        return results[:limit]

    def get_last_retrieved_chunks(self) -> List[Dict[str, Any]]:
        """Parsed evidence chunks from the last `query` or `retrieve` call."""
        return list(self._last_search_result or [])

    def get_search_logs(self) -> List[str]:
        """Get the captured search logs.

        Returns:
            List[str]: List of log messages from the search operation.
        """
        return self._search_logs.copy()

    def get_search_details(self) -> Dict[str, Any]:
        """Get detailed search information including logs and metadata.

        Returns:
            Dict[str, Any]: Search details including logs, mode, and paths.
        """
        return {
            'logs': self._search_logs.copy(),
            'mode': self.search_mode,
            'paths': self.search_paths,
            'work_path': str(self.work_path),
            'reuse_knowledge': self.reuse_knowledge,
            'cluster_cache_hit': self._cluster_cache_hit,
            'cluster_cache_hit_time': self._cluster_cache_hit_time,
        }

    def enable_streaming_logs(self, callback: Callable):
        """Enable streaming mode for search logs.

        Args:
            callback: Async callback function to receive log entries in real-time.
                      Signature: async def callback(log_entry: str) -> None
        """
        self._streaming_callback = callback
        self._search_logs.clear()
