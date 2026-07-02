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

import json
import logging
from typing import Any, Dict, List, Optional

from ..config import MemoryConfig
from ..protocols import BaseMemoryBackend, MemoryEntry
from ..registry import backend_registry

logger = logging.getLogger(__name__)


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
        self._snapshot: Optional[str] = None
        self._snapshot_dirty = True

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self, **kwargs: Any) -> None:
        try:
            from mem0 import Memory
            mem0_cfg = self._config.backend_options.get("mem0", {})
            self._mem0 = Memory.from_config(mem0_cfg) if mem0_cfg else Memory()
            self._user_id = kwargs.get("user_id", self._config.user_id)
            logger.info("[mem0_backend] mem0 initialized")
        except Exception as e:
            logger.warning(f"[mem0_backend] mem0 init failed: {e}")
            self._mem0 = None

    async def close(self) -> None:
        self._mem0 = None

    # ── inject ───────────────────────────────────────────────────────

    async def inject(
        self, messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not self._mem0:
            return messages

        query = self._extract_query(messages)
        if not query:
            return messages

        try:
            results = self._mem0.search(query, user_id=self._user_id)
            if not results:
                return messages
        except Exception as e:
            logger.debug(f"[mem0_backend] search failed: {e}")
            return messages

        formatted = self._format_results(results)
        if not formatted:
            return messages

        messages = list(messages)
        if messages and messages[0].get("role") == "system":
            sys_msg = {**messages[0]}
            block = f"\n\n<long-term-memory>\n{formatted}\n</long-term-memory>"
            sys_msg["content"] = (sys_msg.get("content") or "") + block
            messages[0] = sys_msg

        return messages

    # ── on_messages ──────────────────────────────────────────────────

    async def on_messages(
        self, messages: List[Dict[str, Any]], **kwargs: Any,
    ) -> None:
        if not self._mem0:
            return
        try:
            self._mem0.add(messages, user_id=self._user_id)
        except Exception as e:
            logger.warning(f"[mem0_backend] add failed: {e}")

    # ── Search ───────────────────────────────────────────────────────

    async def search(
        self, query: str, limit: int = 10,
    ) -> List[MemoryEntry]:
        if not self._mem0:
            return []
        try:
            results = self._mem0.search(query, user_id=self._user_id)
            return [
                MemoryEntry(
                    id=r.get("id", ""),
                    content=r.get("memory", r.get("text", "")),
                    source="mem0",
                    metadata=r.get("metadata", {}),
                )
                for r in (results or [])[:limit]
            ]
        except Exception:
            return []

    # ── Cache ────────────────────────────────────────────────────────

    def invalidate(self) -> None:
        self._snapshot = None
        self._snapshot_dirty = True

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _extract_query(messages: List[Dict[str, Any]]) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                content = m.get("content", "")
                return str(content)[:200] if content else ""
        return ""

    @staticmethod
    def _format_results(results: Any) -> str:
        if not results:
            return ""
        lines = []
        for r in results[:10]:
            text = r.get("memory", r.get("text", ""))
            if text:
                lines.append(f"- {text}")
        return "\n".join(lines)


# ── Self-register ────────────────────────────────────────────────────

backend_registry.register("mem0", Mem0Backend)
