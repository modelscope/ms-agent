# Copyright (c) ModelScope Contributors. All rights reserved.
"""Sirchmunk-based knowledge search integration.

This module wraps sirchmunk's AgenticSearch to work with the ms_agent framework,
providing document retrieval capabilities similar to RAG but optimized for
codebase and documentation search.
"""

import asyncio
from loguru import logger
from omegaconf import DictConfig
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Callable

from ms_agent.rag.base import RAG


class SirchmunkSearch(RAG):
    """Sirchmunk-based knowledge search class.

    This class wraps the sirchmunk library to provide intelligent codebase search
    capabilities. Unlike traditional RAG that uses vector embeddings, Sirchmunk
    uses a combination of keyword search, semantic clustering, and LLM-powered
    analysis to find relevant information from codebases.

    The configuration needed in the config yaml:
        - name: SirchmunkSearch
        - paths: List of paths to search, required
        - work_path: Working directory for sirchmunk cache, default './.sirchmunk'
        - embedding_model: Embedding model for clustering, default 'text-embedding-3-small'
        - cluster_sim_threshold: Threshold for cluster similarity, default 0.85
        - cluster_sim_top_k: Top K clusters to consider, default 3
        - reuse_knowledge: Whether to reuse previous search results, default True
        - mode: Search mode (DEEP, FAST, FILENAME_ONLY), default 'FAST'

    Args:
        config (DictConfig): Configuration object containing sirchmunk settings.
    """

    def __init__(self, config: DictConfig):
        super().__init__(config)

        self._validate_config(config)

        # Extract configuration parameters
        rag_config = config.get('knowledge_search', {})

        # Search paths - required
        paths = rag_config.get('paths', [])
        if isinstance(paths, str):
            paths = [paths]
        self.search_paths: List[str] = [
            str(Path(p).expanduser().resolve()) for p in paths
        ]

        # Work path for sirchmunk cache
        _work_path = rag_config.get('work_path', './.sirchmunk')
        self.work_path: Path = Path(_work_path).expanduser().resolve()

        # Sirchmunk search parameters
        self.reuse_knowledge = rag_config.get('reuse_knowledge', True)
        self.cluster_sim_threshold = rag_config.get('cluster_sim_threshold', 0.85)
        self.cluster_sim_top_k = rag_config.get('cluster_sim_top_k', 3)
        self.search_mode = rag_config.get('mode', 'FAST')
        self.max_loops = rag_config.get('max_loops', 10)
        self.max_token_budget = rag_config.get('max_token_budget', 128000)

        # LLM configuration for sirchmunk
        # First try knowledge_search.llm_api_key, then fall back to main llm config
        self.llm_api_key = rag_config.get('llm_api_key', None)
        self.llm_base_url = rag_config.get('llm_base_url', None)
        self.llm_model_name = rag_config.get('llm_model_name', None)

        # Fall back to main llm config if not specified in knowledge_search
        if (
            self.llm_api_key is None
            or self.llm_base_url is None
            or self.llm_model_name is None
        ):
            llm_config = config.get('llm', {})
            if llm_config:
                service = getattr(llm_config, 'service', 'dashscope')
                if self.llm_api_key is None:
                    self.llm_api_key = getattr(llm_config, f"{service}_api_key", None)
                if self.llm_base_url is None:
                    self.llm_base_url = getattr(llm_config, f"{service}_base_url", None)
                if self.llm_model_name is None:
                    self.llm_model_name = getattr(llm_config, 'model', None)

        # Embedding model configuration
        self.embedding_model_id = rag_config.get('embedding_model', None)
        self.embedding_model_cache_dir = rag_config.get(
            'embedding_model_cache_dir', None
        )

        # Runtime state
        self._searcher = None
        self._initialized = False
        self._cluster_cache_hit = False
        self._cluster_cache_hit_time: str | None = None
        self._last_search_result: List[Dict[str, Any]] | None = None

        # Callback for capturing logs
        self._log_callback = None
        self._search_logs: List[str] = []
        # Async queue for streaming logs in real-time
        self._log_queue: asyncio.Queue | None = None
        self._streaming_callback: Callable | None = None

    def _validate_config(self, config: DictConfig):
        """Validate configuration parameters."""
        if not hasattr(config, 'knowledge_search') or config.knowledge_search is None:
            raise ValueError(
                'Missing knowledge_search configuration. '
                'Please add knowledge_search section to your config with at least "paths" specified.'
            )

        rag_config = config.knowledge_search
        paths = rag_config.get('paths', [])
        if not paths:
            raise ValueError('knowledge_search.paths must be specified and non-empty')

    def _initialize_searcher(self):
        """Initialize the sirchmunk AgenticSearch instance."""
        if self._initialized:
            return

        try:
            from sirchmunk.llm.openai_chat import OpenAIChat
            from sirchmunk.search import AgenticSearch
            from sirchmunk.utils.embedding_util import EmbeddingUtil

            # Create LLM client
            llm = OpenAIChat(
                api_key=self.llm_api_key,
                base_url=self.llm_base_url,
                model=self.llm_model_name,
                max_retries=3,
                log_callback=self._log_callback_wrapper(),
            )

            # Create embedding util
            # Handle empty strings by using None (which triggers DEFAULT_MODEL_ID)
            embedding_model_id = (
                self.embedding_model_id if self.embedding_model_id else None
            )
            embedding_cache_dir = (
                self.embedding_model_cache_dir
                if self.embedding_model_cache_dir
                else None
            )
            embedding = EmbeddingUtil(
                model_id=embedding_model_id, cache_dir=embedding_cache_dir
            )

            # Create AgenticSearch instance
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
            logger.info(f"SirschmunkSearch initialized with paths: {self.search_paths}")

        except ImportError as e:
            raise ImportError(
                f"Failed to import sirchmunk: {e}. "
                'Please install sirchmunk: pip install sirchmunk'
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize SirchmunkSearch: {e}")

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
            log_entry = f"[{level.upper()}] {message}"
            self._search_logs.append(log_entry)
            # Stream log in real-time if streaming callback is set
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
        # Trigger re-scan of the search paths
        if self._searcher and hasattr(self._searcher, 'knowledge_base'):
            try:
                await self._searcher.knowledge_base.refresh()
                return True
            except Exception as e:
                logger.error(f"Failed to refresh knowledge base: {e}")
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
                        await self._searcher.scan_directory(str(Path(file_path).parent))
                return True
            except Exception as e:
                logger.error(f"Failed to scan files: {e}")
                return False
        return True

    async def retrieve(
        self, query: str, limit: int = 5, score_threshold: float = 0.7, **filters
    ) -> List[Dict[str, Any]]:
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
            max_token_budget = filters.get('max_token_budget', self.max_token_budget)

            # Perform search
            result = await self._searcher.search(
                query=query,
                mode=mode,
                max_loops=max_loops,
                max_token_budget=max_token_budget,
                return_context=True,
            )

            # Check if cluster cache was hit
            self._cluster_cache_hit = False
            self._cluster_cache_hit_time = None
            if hasattr(result, 'cluster') and result.cluster is not None:
                # If a similar cluster was found and reused, it's a cache hit
                self._cluster_cache_hit = getattr(result.cluster, '_reused_from_cache', False)
                # Get the cluster cache hit time if available
                if hasattr(result.cluster, 'updated_at'):
                    self._cluster_cache_hit_time = getattr(result.cluster, 'updated_at', None)

            # Parse results into standard format
            return self._parse_search_result(result, score_threshold, limit)

        except Exception as e:
            logger.error(f"SirschmunkSearch retrieve failed: {e}")
            return []

    async def query(self, query: str) -> str:
        """Query sirchmunk and return a synthesized answer.

        This method performs a search and returns the LLM-synthesized answer
        along with search details that can be used for frontend display.

        Args:
            query (str): The search query.

        Returns:
            str: The synthesized answer from sirchmunk.
        """
        self._initialize_searcher()
        self._search_logs.clear()

        try:
            mode = self.search_mode
            max_loops = self.max_loops
            max_token_budget = self.max_token_budget

            # Single search with context so we get both the synthesized answer and
            # source units in one call, avoiding a redundant second search.
            result = await self._searcher.search(
                query=query,
                mode=mode,
                max_loops=max_loops,
                max_token_budget=max_token_budget,
                return_context=True,
            )

            # Check if cluster cache was hit
            self._cluster_cache_hit = False
            self._cluster_cache_hit_time = None
            if hasattr(result, 'cluster') and result.cluster is not None:
                self._cluster_cache_hit = getattr(result.cluster, '_reused_from_cache', False)
                if hasattr(result.cluster, 'updated_at'):
                    self._cluster_cache_hit_time = getattr(result.cluster, 'updated_at', None)

            # Store parsed context for frontend display
            self._last_search_result = self._parse_search_result(result, score_threshold=0.7, limit=5)

            # Extract the synthesized answer from the context result
            if hasattr(result, 'answer'):
                return result.answer

            # If result is already a plain string (some modes return str directly)
            if isinstance(result, str):
                return result

            # Fallback: convert to string
            return str(result)

        except Exception as e:
            logger.error(f"SirschmunkSearch query failed: {e}")
            return f"Query failed: {e}"

    def _parse_search_result(
        self, result: Any, score_threshold: float, limit: int
    ) -> List[Dict[str, Any]]:
        """Parse sirchmunk search result into standard format.

        Args:
            result: The raw search result from sirchmunk.
            score_threshold: Minimum score threshold.
            limit: Maximum number of results.

        Returns:
            List[Dict[str, Any]]: Parsed results.
        """
        results = []

        # Handle SearchContext format (returned when return_context=True)
        if hasattr(result, 'cluster') and result.cluster is not None:
            cluster = result.cluster
            for unit in cluster.evidences:
                # Extract score from snippets if available
                score = getattr(cluster, 'confidence', 1.0)
                if score >= score_threshold:
                    # Extract text from snippets
                    text_parts = []
                    source = str(getattr(unit, 'file_or_url', 'unknown'))
                    for snippet in getattr(unit, 'snippets', []):
                        if isinstance(snippet, dict):
                            text_parts.append(snippet.get('snippet', ''))
                        else:
                            text_parts.append(str(snippet))

                    results.append(
                        {
                            'text': '\n'.join(text_parts)
                            if text_parts
                            else getattr(unit, 'summary', ''),
                            'score': score,
                            'metadata': {
                                'source': source,
                                'type': getattr(unit, 'abstraction_level', 'text')
                                if hasattr(unit, 'abstraction_level')
                                else 'text',
                            },
                        }
                    )

        # Handle format with evidence_units attribute directly
        elif hasattr(result, 'evidence_units'):
            for unit in result.evidence_units:
                score = getattr(unit, 'confidence', 1.0)
                if score >= score_threshold:
                    results.append(
                        {
                            'text': str(unit.content)
                            if hasattr(unit, 'content')
                            else str(unit),
                            'score': score,
                            'metadata': {
                                'source': getattr(unit, 'source_file', 'unknown'),
                                'type': getattr(unit, 'abstraction_level', 'text'),
                            },
                        }
                    )

        # Handle list format
        elif isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    score = item.get('score', item.get('confidence', 1.0))
                    if score >= score_threshold:
                        results.append(
                            {
                                'text': item.get(
                                    'content', item.get('text', str(item))
                                ),
                                'score': score,
                                'metadata': item.get('metadata', {}),
                            }
                        )

        # Handle dict format
        elif isinstance(result, dict):
            score = result.get('score', result.get('confidence', 1.0))
            if score >= score_threshold:
                results.append(
                    {
                        'text': result.get('content', result.get('text', str(result))),
                        'score': score,
                        'metadata': result.get('metadata', {}),
                    }
                )

        # Sort by score and limit results
        results.sort(key=lambda x: x.get('score', 0), reverse=True)
        return results[:limit]

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
