# flake8: noqa
import os
import threading
from exa_py import Exa
from typing import TYPE_CHECKING, List, Optional, Set, Union

from ms_agent.tools.search.exa.schema import ExaSearchRequest, ExaSearchResult
from ms_agent.tools.search.search_base import SearchEngine, SearchEngineType
from ms_agent.utils.logger import get_logger

if TYPE_CHECKING:
    from ms_agent.llm.utils import Tool

logger = get_logger()


class ExaSearch(SearchEngine):
    """
    Search engine using Exa API.

    Best for: semantic understanding, finding similar content,
    recent web pages with date filtering.

    Supports a pool of API keys: when one key's credits are exhausted (HTTP 402),
    the engine automatically rotates to the next available key and retries.
    Keys can be supplied as a comma-separated string or a list.

    Exhausted-key state is tracked at the **class level** so that all
    ``ExaSearch`` instances within the same process share the knowledge
    of which keys have been used up (e.g. across multiple searcher sub-agents).
    """

    engine_type = SearchEngineType.EXA

    # Process-wide tracking of exhausted key values (shared across instances).
    _global_exhausted_keys: Set[str] = set()
    _global_lock = threading.Lock()

    def __init__(self, api_key: Union[str, list, None] = None, api_keys: Union[str, list, None] = None):
        all_keys = self._collect_keys(api_key, api_keys)
        assert all_keys, 'EXA_API_KEY or EXA_API_KEYS must be set either as arguments or as environment variables'

        self._api_keys: List[str] = all_keys
        self._lock = threading.Lock()

        # Pick the first key that hasn't been globally exhausted yet.
        start_idx = 0
        with ExaSearch._global_lock:
            for i, k in enumerate(all_keys):
                if k not in ExaSearch._global_exhausted_keys:
                    start_idx = i
                    break

        self._current_key_idx: int = start_idx
        self.client = Exa(api_key=all_keys[start_idx])

        if len(all_keys) > 1:
            with ExaSearch._global_lock:
                n_exhausted = sum(1 for k in all_keys if k in ExaSearch._global_exhausted_keys)
            logger.info(
                f'Exa key pool: {len(all_keys)} keys, '
                f'{n_exhausted} previously exhausted, '
                f'starting at key {start_idx + 1}/{len(all_keys)}'
            )

    @staticmethod
    def _collect_keys(
        api_key: Union[str, list, None] = None,
        api_keys: Union[str, list, None] = None,
    ) -> List[str]:
        """Collect unique API keys from arguments and environment variables.

        All sources are **merged** (deduplicated), so keys from both YAML config
        and ``EXA_API_KEYS`` env var are combined into a single pool.

        Sources (in merge order):
        1. ``api_keys`` argument (list or comma-separated string)
        2. ``api_key`` argument  (single key or comma-separated string)
        3. ``EXA_API_KEYS`` env var (comma-separated) -- always merged
        4. ``EXA_API_KEY`` env var  (only if no keys found so far)
        """
        seen: set = set()
        result: List[str] = []

        def _add(raw: str):
            for k in raw.split(','):
                k = k.strip()
                if k and k not in seen:
                    seen.add(k)
                    result.append(k)

        def _add_source(value):
            if value is None:
                return
            if isinstance(value, str):
                _add(value)
            elif hasattr(value, '__iter__'):
                for item in value:
                    if item is not None:
                        _add(str(item))

        _add_source(api_keys)
        _add_source(api_key)

        # Always merge the pool env var so that keys from YAML config and
        # EXA_API_KEYS are combined (the old code gated this behind
        # ``if not result`` which made it unreachable when api_key was set).
        _add_source(os.getenv('EXA_API_KEYS'))

        if not result:
            _add_source(os.getenv('EXA_API_KEY'))

        return result

    @staticmethod
    def _is_credits_exhausted(error: Exception) -> bool:
        """Detect Exa 402 / NO_MORE_CREDITS errors."""
        msg = str(error)
        return '402' in msg and ('credits' in msg.lower() or 'NO_MORE_CREDITS' in msg)

    @staticmethod
    def _mask_key(key: str) -> str:
        if len(key) <= 8:
            return '****'
        return f'{key[:4]}...{key[-4:]}'

    def _is_key_exhausted(self, idx: int) -> bool:
        with ExaSearch._global_lock:
            return self._api_keys[idx] in ExaSearch._global_exhausted_keys

    def _mark_key_exhausted(self, idx: int) -> None:
        with ExaSearch._global_lock:
            ExaSearch._global_exhausted_keys.add(self._api_keys[idx])

    def search(self, search_request: ExaSearchRequest) -> ExaSearchResult:
        """
        Perform a search using the Exa API with the provided search request parameters.

        If the current key is exhausted (HTTP 402 / NO_MORE_CREDITS), the engine
        rotates to the next available key and retries, up to ``len(api_keys)`` times.

        :param search_request: An instance of ExaSearchRequest containing search parameters.
        :return: An instance of ExaSearchResult containing the search results.
        """
        search_args: dict = search_request.to_dict()
        search_result: ExaSearchResult = ExaSearchResult(
            query=search_request.query,
            arguments=search_args,
        )

        last_error: Optional[Exception] = None
        max_attempts = len(self._api_keys)
        instance_exhausted: Set[int] = set()

        for _attempt in range(max_attempts):
            with self._lock:
                client = self.client
                key_idx = self._current_key_idx

            try:
                search_result.response = client.search_and_contents(**search_args)
                return search_result
            except Exception as e:
                if not self._is_credits_exhausted(e):
                    raise RuntimeError(f'Failed to perform search: {e}') from e

                last_error = e
                instance_exhausted.add(key_idx)
                self._mark_key_exhausted(key_idx)

                with self._lock:
                    logger.warning(
                        f'Exa API key {self._mask_key(self._api_keys[key_idx])} '
                        f'credits exhausted '
                        f'({len(instance_exhausted)}/{len(self._api_keys)} keys used up)'
                    )
                    rotated = False
                    for i in range(len(self._api_keys)):
                        if i not in instance_exhausted and not self._is_key_exhausted(i):
                            self._current_key_idx = i
                            self.client = Exa(api_key=self._api_keys[i])
                            logger.info(
                                f'Rotated to Exa API key '
                                f'{self._mask_key(self._api_keys[i])} '
                                f'({i + 1}/{len(self._api_keys)})'
                            )
                            rotated = True
                            break
                    if not rotated:
                        raise RuntimeError(
                            f'All {len(self._api_keys)} Exa API keys have been exhausted. Last error: {e}'
                        ) from e

        raise RuntimeError(
            f'All {len(self._api_keys)} Exa API keys have been exhausted. Last error: {last_error}'
        ) from last_error

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
                'Supports neural search (meaning-based) and keyword search.'
            ),
            parameters={
                'type': 'object',
                'properties': {
                    'query': {
                        'type': 'string',
                        'description': (
                            'The search query. For neural search, use natural language '
                            'descriptions. For keyword search, use Google-style queries.'
                        ),
                    },
                    'num_results': {
                        'type': 'integer',
                        'minimum': 1,
                        'maximum': 10,
                        'description': 'Number of results to return. Default is 5.',
                    },
                    'type': {
                        'type': 'string',
                        'enum': ['auto', 'neural', 'keyword'],
                        'description': (
                            'Search type. "neural" for semantic similarity, '
                            '"keyword" for exact matching, "auto" to let Exa decide. '
                            'Default is "auto".'
                        ),
                    },
                    'start_published_date': {
                        'type': 'string',
                        'description': (
                            'Filter results published on/after this date. Format: YYYY-MM-DD (e.g., "2024-01-01").'
                        ),
                    },
                    'end_published_date': {
                        'type': 'string',
                        'description': (
                            'Filter results published on/before this date. Format: YYYY-MM-DD (e.g., "2024-12-31").'
                        ),
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
