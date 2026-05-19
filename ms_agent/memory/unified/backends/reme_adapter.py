"""ReMeBackend — adapter for the reme-ai (ReMeLight) memory system.

Wraps ``reme.ReMeLight`` as a ``MemoryBackend``, allowing ReMe to be
used as a drop-in backend for ms-agent's unified memory system.

Configuration::

    memory:
      unified_memory:
        storage:
          backend: "reme"
        reme:
          working_dir: "."
          embedding_model: "text-embedding-v4"
          fts_enabled: true
          vector_enabled: false
          auto_memory_search: true

Dependencies: ``pip install reme-ai``
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..config import MemoryConfig
from ..protocols import BaseMemoryBackend, MemoryEntry
from ..registry import backend_registry

logger = logging.getLogger(__name__)


class ReMeBackend(BaseMemoryBackend):
    """MemoryBackend adapter for ReMeLight.

    Delegates to ``reme.ReMeLight`` for:
    - File-based storage (MEMORY.md + memory/YYYY-MM-DD.md)
    - Hybrid retrieval (vector + BM25)
    - ReActAgent-based summarization
    - Dream optimization

    The adapter handles message format conversion between ms-agent's
    ``{"role": ..., "content": ...}`` dicts and agentscope's ``Msg``.
    """

    def __init__(self, config: MemoryConfig) -> None:
        self._config = config
        self._reme: Any = None
        self._started = False
        self._snapshot: Optional[str] = None
        self._snapshot_dirty = True

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self, **kwargs: Any) -> None:
        from reme.reme_light import ReMeLight

        reme_cfg = self._config.backend_options.get("reme", {})
        working_dir = reme_cfg.get("working_dir", self._config.base_dir)

        self._reme = ReMeLight(
            working_dir=working_dir,
            default_file_store_config={
                "backend": reme_cfg.get("store_backend", "local"),
                "store_name": "memory",
                "vector_enabled": reme_cfg.get("vector_enabled", False),
                "fts_enabled": reme_cfg.get("fts_enabled", True),
            },
        )
        await self._reme.start()
        self._started = True
        logger.info("[reme_backend] ReMeLight started")

    async def close(self) -> None:
        if self._reme and self._started:
            await self._reme.close()
            self._started = False
            logger.info("[reme_backend] ReMeLight closed")

    # ── inject ───────────────────────────────────────────────────────

    async def inject(
        self, messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        snapshot = self._build_snapshot()
        if not snapshot:
            return messages

        messages = list(messages)
        if messages and messages[0].get("role") == "system":
            sys_msg = {**messages[0]}
            block = f"\n\n<long-term-memory>\n{snapshot}\n</long-term-memory>"
            if "<long-term-memory>" not in (sys_msg.get("content") or ""):
                sys_msg["content"] = (sys_msg.get("content") or "") + block
            messages[0] = sys_msg

        # Auto memory search: inject relevant context into user message
        query = self._extract_query(messages)
        if query and self._reme:
            try:
                result = await self._reme.memory_search(
                    query=query, max_results=5, min_score=0.1)
                context = self._format_search_result(result)
                if context:
                    messages = self._inject_context(messages, context)
            except Exception as e:
                logger.debug(f"[reme_backend] memory_search failed: {e}")

        return messages

    # ── on_messages ──────────────────────────────────────────────────

    async def on_messages(
        self, messages: List[Dict[str, Any]], **kwargs: Any,
    ) -> None:
        # ReMe handles persistence through summary_memory, triggered by
        # context pressure or periodic intervals — not per-step.
        pass

    # ── on_pre_compress ──────────────────────────────────────────────

    async def on_pre_compress(
        self, messages: List[Dict[str, Any]],
    ) -> None:
        if not self._reme:
            return
        try:
            as_msgs = self._to_agentscope_msgs(messages)
            await self._reme.summary_memory(messages=as_msgs)
            self._snapshot_dirty = True
            logger.info("[reme_backend] summary_memory completed (pre-compress)")
        except Exception as e:
            logger.warning(f"[reme_backend] summary_memory failed: {e}")

    # ── Tools ────────────────────────────────────────────────────────

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [{
            "tool_name": "memory_search",
            "description": (
                "Search MEMORY.md and memory/*.md files semantically. "
                "Use before answering questions about prior work, "
                "decisions, dates, people, preferences, or todos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The semantic search query.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return.",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        }]

    async def handle_tool_call(
        self, tool_name: str, arguments: Dict[str, Any],
    ) -> str:
        if tool_name != "memory_search" or not self._reme:
            return json.dumps({"error": f"unknown tool: {tool_name}"})

        query = arguments.get("query", "")
        max_results = arguments.get("max_results", 5)
        result = await self._reme.memory_search(
            query=query, max_results=max_results, min_score=0.1)
        return json.dumps({"results": str(result)}, ensure_ascii=False)

    # ── Search ───────────────────────────────────────────────────────

    async def search(
        self, query: str, limit: int = 10,
    ) -> List[MemoryEntry]:
        if not self._reme:
            return []
        result = await self._reme.memory_search(
            query=query, max_results=limit, min_score=0.1)
        return [MemoryEntry(content=str(result), source="reme")]

    # ── Cache ────────────────────────────────────────────────────────

    def invalidate(self) -> None:
        self._snapshot = None
        self._snapshot_dirty = True

    # ── Internal helpers ─────────────────────────────────────────────

    def _build_snapshot(self) -> str:
        if self._snapshot and not self._snapshot_dirty:
            return self._snapshot
        try:
            from pathlib import Path
            md_path = Path(self._config.base_dir) / "MEMORY.md"
            if md_path.exists():
                self._snapshot = md_path.read_text(encoding="utf-8").strip()
            else:
                self._snapshot = ""
        except Exception:
            self._snapshot = ""
        self._snapshot_dirty = False
        return self._snapshot

    @staticmethod
    def _extract_query(messages: List[Dict[str, Any]]) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                content = m.get("content") or ""
                if isinstance(content, str):
                    return content[:100].strip()
        return ""

    @staticmethod
    def _format_search_result(result: Any) -> str:
        if result is None:
            return ""
        text = str(result)
        return text[:500] if text else ""

    @staticmethod
    def _inject_context(
        messages: List[Dict[str, Any]], context: str,
    ) -> List[Dict[str, Any]]:
        messages = list(messages)
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                user_copy = {**messages[i]}
                user_copy["content"] = (
                    f"{user_copy['content']}\n\n"
                    f"<memory-context>\n{context}\n</memory-context>"
                )
                messages[i] = user_copy
                break
        return messages

    @staticmethod
    def _to_agentscope_msgs(messages: List[Dict[str, Any]]) -> List[Any]:
        """Convert ms-agent dicts to agentscope Msg objects."""
        try:
            from agentscope.message import Msg, TextBlock
            result = []
            for m in messages:
                content = m.get("content", "")
                msg = Msg(
                    name=m.get("role", "user"),
                    role=m.get("role", "user"),
                    content=[TextBlock(type="text", text=content)]
                    if isinstance(content, str) else content,
                )
                result.append(msg)
            return result
        except ImportError:
            return messages


# ── Self-register ────────────────────────────────────────────────────

backend_registry.register("reme", ReMeBackend)
