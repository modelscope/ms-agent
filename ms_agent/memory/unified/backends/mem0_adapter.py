"""Mem0Backend — adapter for mem0 vector memory.

Wraps the existing ms-agent ``DefaultMemory`` (mem0) as a MemoryBackend,
providing backward compatibility with the legacy memory system.

Configuration::

    memory:
      unified_memory:
        storage:
          backend: "mem0"
        mem0:
          vector_store:
            provider: "qdrant"
            config:
              collection_name: "memory"
              url: "localhost"
              port: 6333
"""
from __future__ import annotations

import asyncio
import json
import logging
from functools import partial
from typing import Any, Dict, List, Optional

from ..config import MemoryConfig
from ..protocols import BaseMemoryBackend, MemoryEntry
from ..registry import backend_registry

logger = logging.getLogger(__name__)


async def _offload(fn, *args, **kwargs):
    """Run a blocking mem0 call (LLM extraction / embedding / vector IO) in a
    worker thread so the agent event loop stays responsive."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(fn, *args, **kwargs))


def _result_list(results: Any) -> List[Dict[str, Any]]:
    """mem0 v1 returns a list; v2 wraps it as {'results': [...]}. Normalize."""
    if isinstance(results, dict):
        results = results.get('results', [])
    return list(results or [])


def _mem0_search(m0: Any, query: str, user_id: str) -> Any:
    """mem0 2.x moved entity params into ``filters=``; 1.x uses kwargs."""
    try:
        return m0.search(query, filters={'user_id': user_id})
    except TypeError:
        return m0.search(query, user_id=user_id)


class Mem0Backend(BaseMemoryBackend):
    """MemoryBackend adapter wrapping the legacy mem0/DefaultMemory.

    Maps MemoryBackend methods to mem0's API:
    - inject()         → mem0.search() → format → inject system prompt
    - on_messages()    → mem0.add(messages)
    - search()         → mem0.search(query)
    """

    def __init__(self, config: MemoryConfig) -> None:
        self._config = config
        self._mem0: Any = None  # mem0.Memory instance
        self._user_id: str = config.user_id
        # Per-turn retrieval cache: one turn = one embedding + one vector
        # search. The turn key is the latest user message — every round of a
        # multi-round (tool-calling) turn injects with the same user message,
        # so rounds 2..N reuse the round-1 results instead of paying another
        # embedding round-trip each. Invalidated on writes/deletes.
        self._turn_cache_key: Optional[str] = None
        self._turn_cache_results: Optional[list] = None

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self, **kwargs: Any) -> None:
        try:
            from mem0 import Memory
            mem0_cfg = self._config.backend_options.get('mem0', {})
            self._mem0 = Memory.from_config(mem0_cfg) if mem0_cfg else Memory()
            self._user_id = kwargs.get('user_id', self._config.user_id)
            logger.info('[mem0_backend] mem0 initialized')
        except Exception as e:
            logger.warning(f'[mem0_backend] mem0 init failed: {e}')
            self._mem0 = None

    async def close(self) -> None:
        # Drop the vector client explicitly. Embedded stores (qdrant/chroma on a
        # local path) hold an exclusive OS file lock, so merely releasing the
        # reference leaves the store locked until GC gets around to it -- long
        # enough that the next agent, or any other process on the same path,
        # fails with "already accessed by another instance".
        client = getattr(getattr(self._mem0, 'vector_store', None), 'client',
                         None)
        if client is not None:
            try:
                client.close()
            except Exception as e:  # pragma: no cover - best-effort teardown
                logger.debug(f'[mem0_backend] vector client close failed: {e}')
        self._mem0 = None

    # ── inject ───────────────────────────────────────────────────────

    async def inject(
        self,
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not self._mem0:
            return messages

        query = self._extract_query(messages)
        if not query:
            return messages

        turn_key = f'{self._user_id}\x1f{query}'
        if turn_key == self._turn_cache_key \
                and self._turn_cache_results is not None:
            results = self._turn_cache_results
        else:
            try:
                results = _result_list(
                    await _offload(_mem0_search, self._mem0, query,
                                   self._user_id))
            except Exception as e:
                logger.debug(f'[mem0_backend] search failed: {e}')
                return messages
            self._turn_cache_key = turn_key
            self._turn_cache_results = results
        if not results:
            return messages

        formatted = self._format_results(results)
        if not formatted:
            return messages

        messages = list(messages)
        if messages and messages[0].get('role') == 'system':
            sys_msg = {**messages[0]}
            block = f'\n\n<long-term-memory>\n{formatted}\n</long-term-memory>'
            sys_msg['content'] = (sys_msg.get('content') or '') + block
            messages[0] = sys_msg

        return messages

    # ── on_messages ──────────────────────────────────────────────────

    async def on_messages(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> int:
        """Ingest via mem0's fact extraction. Returns the number of memory
        events mem0 produced (ADD/UPDATE/DELETE). Raises on failure — the
        orchestrator owns the swallow-and-report policy, and needs the
        exception to know the write did NOT land (so its delta ledger keeps
        the messages for a retry instead of marking them ingested)."""
        if not self._mem0:
            return 0
        # mem0 rejects non-chat fields and roles like `tool`; feed it the
        # user/assistant text turns only.
        convo = [
            {
                'role': m['role'],
                'content': m['content']
            } for m in messages
            if m.get('role') in ('user', 'assistant') and m.get('content')
        ]
        if not convo:
            return 0
        result = await _offload(self._mem0.add, convo, user_id=self._user_id)
        # A write changes what retrieval should see.
        self._turn_cache_key = None
        self._turn_cache_results = None
        if isinstance(result, dict):
            return len(result.get('results') or [])
        return len(result or [])

    # ── Search ───────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> List[MemoryEntry]:
        if not self._mem0:
            return []
        try:
            results = _result_list(await _offload(_mem0_search, self._mem0,
                                                  query, self._user_id))
            return [
                MemoryEntry(
                    id=r.get('id', ''),
                    content=r.get('memory', r.get('text', '')),
                    source='mem0',
                    metadata=r.get('metadata', {}) or {},
                ) for r in results[:limit]
            ]
        except Exception:
            return []

    # ── Cache ────────────────────────────────────────────────────────

    def invalidate(self) -> None:
        # External edit (UI delete, another writer): next inject re-queries.
        self._turn_cache_key = None
        self._turn_cache_results = None

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _extract_query(messages: List[Dict[str, Any]]) -> str:
        for m in reversed(messages):
            if m.get('role') == 'user':
                content = m.get('content', '')
                return str(content)[:200] if content else ''
        return ''

    @staticmethod
    def _format_results(results: Any) -> str:
        lines = []
        for r in _result_list(results)[:10]:
            text = r.get('memory', r.get('text', ''))
            if text:
                lines.append(f'- {text}')
        return '\n'.join(lines)


# ── Self-register ────────────────────────────────────────────────────

backend_registry.register('mem0', Mem0Backend)
