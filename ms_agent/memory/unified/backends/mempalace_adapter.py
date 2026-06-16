"""MempalaceBackend — adapter for the mempalace memory system.

Wraps mempalace's ChromaDB-backed palace storage, MemoryStack (L0-L3
layers), and semantic search as a ``MemoryBackend``.

Two complementary integration paths are available:

1. **This adapter** (passive): automatic wake-up injection + auto-search
   on every turn.  Configured via ``storage.backend: "mempalace"``.

2. **MCP tools** (active): agent-initiated KG queries, diary writes,
   graph traversal — configured in the ``tools:`` YAML section::

       tools:
         mempalace:
           mcp: true
           command: python
           args: ["-m", "mempalace.mcp_server"]

   Both paths can be used simultaneously.

Configuration::

    memory:
      unified_memory:
        storage:
          backend: "mempalace"
        mempalace:
          palace_path: "~/.mempalace/palace"
          wing: "default"
          collection_name: "mempalace_drawers"
          auto_search: true
          max_search_results: 5
          max_distance: 1.5
          inject_protocol: true

Dependencies: ``pip install mempalace``
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import MemoryConfig
from ..protocols import BaseMemoryBackend, MemoryEntry
from ..registry import backend_registry

logger = logging.getLogger(__name__)

_CONDENSED_PROTOCOL = (
    "MemPalace Memory Protocol:\n"
    "1. BEFORE RESPONDING about any person, project, or past event: "
    "call palace_search FIRST. Never guess — verify.\n"
    "2. Use palace_add to save important facts, decisions, and preferences.\n"
    "3. When facts change: add the corrected fact via palace_add."
)


def _safe_sanitize_name(value: str, label: str = "name") -> str:
    """Sanitize a wing/room name, falling back to basic cleaning."""
    try:
        from mempalace.config import sanitize_name
        return sanitize_name(value, label)
    except (ImportError, Exception):
        import re
        cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "_", value or "")
        return cleaned[:128].strip("_") or "default"


def _safe_sanitize_content(content: str) -> str:
    """Sanitize drawer content, falling back to length trim."""
    try:
        from mempalace.config import sanitize_content
        return sanitize_content(content)
    except (ImportError, Exception):
        return (content or "")[:100000].strip()


def _safe_sanitize_query(query: str) -> str:
    """Sanitize a search query against prompt contamination."""
    try:
        from mempalace.config import sanitize_query
        result = sanitize_query(query)
        return result.get("clean_query", query) if isinstance(result, dict) else str(result)
    except (ImportError, Exception):
        return (query or "").strip()[:500]


def _deterministic_drawer_id(wing: str, room: str, content: str) -> str:
    """Content-based deterministic ID matching mempalace MCP convention."""
    raw = (wing + room + content).encode()
    return f"drawer_{wing}_{room}_{hashlib.sha256(raw).hexdigest()[:24]}"


class MempalaceBackend(BaseMemoryBackend):
    """MemoryBackend adapter for mempalace.

    Delegates to mempalace for:
    - File-based + ChromaDB storage (drawers, closets)
    - Hybrid retrieval (vector + BM25)
    - MemoryStack (L0 identity + L1 essential story) for prompt injection
    """

    def __init__(self, config: MemoryConfig) -> None:
        self._config = config
        opts = config.backend_options.get("mempalace", {})
        self._palace_path = opts.get(
            "palace_path", "~/.mempalace/palace")
        self._wing = opts.get("wing", "default")
        self._collection_name = opts.get(
            "collection_name", "mempalace_drawers")
        self._auto_search = opts.get("auto_search", True)
        self._max_results = opts.get("max_search_results", 5)
        self._max_distance = opts.get("max_distance", 1.5)
        self._identity_path = opts.get("identity_path", None)
        self._inject_protocol = opts.get("inject_protocol", True)

        self._collection: Any = None
        self._stack: Any = None
        self._wake_up_cache: Optional[str] = None

    # -- Lifecycle ---------------------------------------------------------

    async def start(self, **kwargs: Any) -> None:
        try:
            from mempalace.palace import get_collection
            from mempalace.layers import MemoryStack

            self._collection = get_collection(
                self._palace_path,
                collection_name=self._collection_name,
            )
            stack_kwargs: Dict[str, Any] = {
                "palace_path": self._palace_path,
            }
            if self._identity_path is not None:
                stack_kwargs["identity_path"] = self._identity_path
            self._stack = MemoryStack(**stack_kwargs)
            logger.info("[mempalace_backend] Palace initialized")
        except ImportError:
            logger.warning(
                "[mempalace_backend] mempalace not installed. "
                "Install with: pip install mempalace")
        except Exception as e:
            logger.warning("[mempalace_backend] Init failed: %s", e)

    async def close(self) -> None:
        self._collection = None
        self._stack = None
        self._wake_up_cache = None

    # -- inject ------------------------------------------------------------

    async def inject(
        self, messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        messages = list(messages)

        # 1. Inject wake-up text (L0 + L1) + optional protocol
        wake_up = self._get_wake_up()
        if wake_up and messages and messages[0].get("role") == "system":
            sys_msg = {**messages[0]}
            protocol = (
                f"\n\n{_CONDENSED_PROTOCOL}" if self._inject_protocol else "")
            block = (
                f"\n\n<long-term-memory>\n{wake_up}{protocol}"
                f"\n</long-term-memory>"
            )
            if "<long-term-memory>" not in (sys_msg.get("content") or ""):
                sys_msg["content"] = (sys_msg.get("content") or "") + block
            messages[0] = sys_msg

        # 2. Semantic search -> inject into user message
        if self._auto_search and self._collection is not None:
            query = self._extract_query(messages)
            if query:
                try:
                    results = self._search_drawers(query)
                    if results:
                        messages = self._inject_context(messages, results)
                except Exception as e:
                    logger.debug("[mempalace_backend] Search failed: %s", e)

        return messages

    # -- on_messages -------------------------------------------------------

    async def on_messages(
        self, messages: List[Dict[str, Any]], **kwargs: Any,
    ) -> None:
        pass

    # -- Tools -------------------------------------------------------------

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [
            {
                "tool_name": "palace_search",
                "description": (
                    "Search the memory palace for relevant memories. "
                    "Use before answering questions about prior work, "
                    "decisions, preferences, or people."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The semantic search query.",
                        },
                        "wing": {
                            "type": "string",
                            "description": "Optional wing filter.",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Max results (default 5).",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "tool_name": "palace_add",
                "description": (
                    "Add a new memory (drawer) to the palace. "
                    "Use to save important facts, preferences, or decisions. "
                    "Idempotent: adding the same content twice is a no-op."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The memory content to store.",
                        },
                        "wing": {
                            "type": "string",
                            "description": "Wing to store in.",
                        },
                        "room": {
                            "type": "string",
                            "description": "Room within the wing.",
                        },
                    },
                    "required": ["content"],
                },
            },
        ]

    async def handle_tool_call(
        self, tool_name: str, arguments: Dict[str, Any],
    ) -> str:
        if tool_name == "palace_search":
            return await self._handle_search(arguments)
        elif tool_name == "palace_add":
            return await self._handle_add(arguments)
        return json.dumps({"error": f"unknown tool: {tool_name}"})

    # -- Search ------------------------------------------------------------

    async def search(
        self, query: str, limit: int = 10,
    ) -> List[MemoryEntry]:
        results = self._search_drawers(query, limit=limit)
        return [
            MemoryEntry(
                id=r.get("id", ""),
                content=r.get("document", ""),
                source="mempalace",
                metadata=r.get("metadata", {}),
            )
            for r in results
        ]

    # -- Cache -------------------------------------------------------------

    def invalidate(self) -> None:
        self._wake_up_cache = None

    # -- Internal helpers --------------------------------------------------

    def _get_wake_up(self) -> str:
        if self._wake_up_cache is not None:
            return self._wake_up_cache
        if self._stack is None:
            return ""
        try:
            text = self._stack.wake_up(wing=self._wing)
            self._wake_up_cache = text
            return text
        except Exception as e:
            logger.debug("[mempalace_backend] wake_up failed: %s", e)
            return ""

    def _search_drawers(
        self, query: str, limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if self._collection is None:
            return []
        max_r = limit or self._max_results
        sanitized = _safe_sanitize_query(query)
        try:
            from mempalace.searcher import search_memories
            results = search_memories(
                sanitized,
                palace_path=self._palace_path,
                wing=self._wing,
                n_results=max_r,
                max_distance=self._max_distance,
                collection_name=self._collection_name,
            )
            if isinstance(results, dict):
                if self._is_transient_error(results):
                    time.sleep(1)
                    results = search_memories(
                        sanitized,
                        palace_path=self._palace_path,
                        wing=self._wing,
                        n_results=max_r,
                        max_distance=self._max_distance,
                        collection_name=self._collection_name,
                    )

                hits = results.get("results", [])
                if isinstance(hits, list):
                    return [
                        {
                            "id": h.get("id", str(i)),
                            "document": h.get("text", ""),
                            "metadata": {
                                k: v for k, v in h.items() if k != "text"
                            },
                        }
                        for i, h in enumerate(hits)
                    ]
            if isinstance(results, list):
                return results
        except Exception as e:
            logger.debug("[mempalace_backend] search failed: %s", e)
        return []

    @staticmethod
    def _is_transient_error(result: Dict[str, Any]) -> bool:
        err = str(result.get("error", ""))
        return "segment" in err.lower() or "hnsw" in err.lower()

    @staticmethod
    def _extract_query(messages: List[Dict[str, Any]]) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                content = m.get("content", "")
                return str(content)[:300].strip() if content else ""
        return ""

    @staticmethod
    def _inject_context(
        messages: List[Dict[str, Any]],
        results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        lines = []
        for r in results[:5]:
            doc = r.get("document", "")
            if doc:
                lines.append(f"- {doc[:300]}")
        if not lines:
            return messages
        context = "\n".join(lines)

        messages = list(messages)
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                user_copy = {**messages[i]}
                user_copy["content"] = (
                    f"{user_copy['content']}\n\n"
                    f"<memory-context>\n"
                    f"[System note: Retrieved from memory palace]\n"
                    f"{context}\n"
                    f"</memory-context>"
                )
                messages[i] = user_copy
                break
        return messages

    async def _handle_search(self, args: Dict[str, Any]) -> str:
        query = args.get("query", "")
        max_r = args.get("max_results", self._max_results)
        results = self._search_drawers(query, limit=max_r)
        if not results:
            return json.dumps({"results": []}, ensure_ascii=False)
        formatted = [
            {
                "content": r.get("document", "")[:500],
                "metadata": r.get("metadata", {}),
            }
            for r in results
        ]
        return json.dumps({"results": formatted}, ensure_ascii=False)

    async def _handle_add(self, args: Dict[str, Any]) -> str:
        content = args.get("content", "")
        if not content.strip():
            return json.dumps({"error": "empty content"})

        wing = _safe_sanitize_name(
            args.get("wing", self._wing), "wing")
        room = _safe_sanitize_name(
            args.get("room", "general"), "room")
        content = _safe_sanitize_content(content)

        if self._collection is None:
            return json.dumps({"error": "palace not initialized"})

        try:
            doc_id = _deterministic_drawer_id(wing, room, content)

            # Idempotency: skip if already exists
            try:
                existing = self._collection.get(ids=[doc_id], include=[])
                if existing and existing.get("ids"):
                    return json.dumps({
                        "status": "already_exists",
                        "id": doc_id,
                    })
            except Exception:
                pass

            self._collection.upsert(
                ids=[doc_id],
                documents=[content],
                metadatas=[{
                    "wing": wing,
                    "room": room,
                    "added_by": "ms-agent",
                    "filed_at": datetime.now().isoformat(),
                    "chunk_index": 0,
                }],
            )
            self._wake_up_cache = None
            return json.dumps({
                "status": "saved",
                "id": doc_id,
                "wing": wing,
                "room": room,
            })
        except Exception as e:
            return json.dumps({"error": str(e)})


# -- Self-register ---------------------------------------------------------

backend_registry.register("mempalace", MempalaceBackend)
