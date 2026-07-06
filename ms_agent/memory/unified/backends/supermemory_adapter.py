"""SupermemoryBackend — adapter for the Supermemory cloud memory engine.

Provides semantic long-term memory via the ``supermemory`` Python SDK:
profile recall, semantic search, explicit memory tools, and automatic
turn capture with entity extraction.

Dependencies: ``pip install supermemory``

Configuration::

    memory:
      unified_memory:
        storage:
          backend: "supermemory"
        supermemory:
          api_key: <SUPERMEMORY_API_KEY>   # or env var
          container_tag: "ms-agent"
          search_mode: "hybrid"            # hybrid | memories | documents
          auto_capture: true
          min_capture_length: 100
          max_recall_results: 10
          api_timeout: 5.0
          entity_context: "Conversation from an AI agent session."
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Any, Dict, List, Optional

from ..config import MemoryConfig
from ..protocols import BaseMemoryBackend, MemoryEntry
from ..registry import backend_registry

logger = logging.getLogger(__name__)

_DEFAULT_CONTAINER_TAG = "ms-agent"
_DEFAULT_SEARCH_MODE = "hybrid"
_VALID_SEARCH_MODES = ("hybrid", "memories", "documents")
_DEFAULT_API_TIMEOUT = 5.0
_DEFAULT_MAX_RECALL = 10
_MIN_CAPTURE_LEN = 100

_DEFAULT_ENTITY_CONTEXT = (
    "User-assistant conversation. "
    "Only extract things useful in future conversations. "
    "Remember lasting personal facts, preferences, routines, tools, "
    "ongoing projects, and working context. "
    "Do not remember temporary intents, one-time tasks, or in-progress status. "
    "When in doubt, store less."
)

_TRIVIAL_RE = re.compile(
    r"^(ok|okay|thanks|thank you|got it|sure|yes|no|yep|nope|k|ty|thx|np)\.?$",
    re.IGNORECASE,
)

_CONTEXT_STRIP_RE = re.compile(
    r"<(?:long-term-memory|memory-context|supermemory-context)>"
    r"[\s\S]*?"
    r"</(?:long-term-memory|memory-context|supermemory-context)>\s*",
    re.DOTALL,
)


def _sanitize_tag(raw: str) -> str:
    tag = re.sub(r"[^a-zA-Z0-9_]", "_", raw or "")
    tag = re.sub(r"_+", "_", tag)
    return tag.strip("_") or _DEFAULT_CONTAINER_TAG


def _clean_for_capture(text: str) -> str:
    text = _CONTEXT_STRIP_RE.sub("", text or "")
    return text.strip()


def _is_trivial(text: str) -> bool:
    return bool(_TRIVIAL_RE.match((text or "").strip()))


# -- Tool schemas ----------------------------------------------------------

_STORE_SCHEMA = {
    "tool_name": "supermemory_store",
    "description": "Store an explicit memory for future recall.",
    "parameters": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The memory content to store.",
            },
            "metadata": {
                "type": "object",
                "description": "Optional metadata attached to the memory.",
            },
        },
        "required": ["content"],
    },
}

_SEARCH_SCHEMA = {
    "tool_name": "supermemory_search",
    "description": "Search long-term memory by semantic similarity.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to search for.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results to return (1-20).",
            },
        },
        "required": ["query"],
    },
}

_FORGET_SCHEMA = {
    "tool_name": "supermemory_forget",
    "description": "Forget a memory by exact id or by best-match query.",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "Exact memory id to delete.",
            },
            "query": {
                "type": "string",
                "description": "Query to find the memory to forget.",
            },
        },
    },
}

_PROFILE_SCHEMA = {
    "tool_name": "supermemory_profile",
    "description": (
        "Retrieve persistent profile facts and recent memory context."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional query to focus the profile.",
            },
        },
    },
}


class SupermemoryBackend(BaseMemoryBackend):
    """MemoryBackend adapter for Supermemory cloud memory.

    Maps MemoryBackend methods to the supermemory Python SDK:
    - inject()          -> client.profile() -> inject results
    - on_messages()     -> client.documents.add() (background)
    - tools             -> supermemory_store, _search, _forget, _profile
    """

    def __init__(self, config: MemoryConfig) -> None:
        self._config = config
        opts = config.backend_options.get("supermemory", {})
        self._api_key = opts.get("api_key", "")
        self._container_tag = _sanitize_tag(
            opts.get("container_tag", _DEFAULT_CONTAINER_TAG))
        self._search_mode = opts.get("search_mode", _DEFAULT_SEARCH_MODE)
        if self._search_mode not in _VALID_SEARCH_MODES:
            self._search_mode = _DEFAULT_SEARCH_MODE
        self._auto_capture = opts.get("auto_capture", True)
        self._min_capture_len = opts.get(
            "min_capture_length", _MIN_CAPTURE_LEN)
        self._max_recall = opts.get(
            "max_recall_results", _DEFAULT_MAX_RECALL)
        self._api_timeout = opts.get("api_timeout", _DEFAULT_API_TIMEOUT)
        self._entity_context = opts.get(
            "entity_context", _DEFAULT_ENTITY_CONTEXT)

        self._client: Any = None
        self._active = False
        self._turn_count = 0
        self._sync_thread: Optional[threading.Thread] = None

    # -- Lifecycle ---------------------------------------------------------

    async def start(self, **kwargs: Any) -> None:
        api_key = self._api_key or os.environ.get("SUPERMEMORY_API_KEY", "")
        if not api_key:
            logger.warning(
                "[supermemory_backend] No API key. "
                "Set SUPERMEMORY_API_KEY env var or supermemory.api_key config.")
            return

        try:
            from supermemory import Supermemory
            self._client = Supermemory(
                api_key=api_key,
                timeout=self._api_timeout,
                max_retries=0,
            )
            self._active = True
            logger.info(
                "[supermemory_backend] Initialized (container=%s)",
                self._container_tag)
        except ImportError:
            logger.warning(
                "[supermemory_backend] supermemory not installed. "
                "Install with: pip install supermemory")
        except Exception as e:
            logger.warning("[supermemory_backend] Init failed: %s", e)

    async def close(self) -> None:
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)
        self._client = None
        self._active = False

    # -- inject ------------------------------------------------------------

    async def inject(
        self, messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not self._active or not self._client:
            return messages

        query = self._extract_query(messages)
        if not query:
            return messages

        try:
            profile = self._client.profile(
                container_tag=self._container_tag,
                q=query[:200],
            )
        except Exception as e:
            logger.debug("[supermemory_backend] profile() failed: %s", e)
            return messages

        profile_data = getattr(profile, "profile", None)
        search_data = (
            getattr(profile, "search_results", None)
            or getattr(profile, "searchResults", None)
        )

        static = (getattr(profile_data, "static", []) or []) if profile_data else []
        dynamic = (getattr(profile_data, "dynamic", []) or []) if profile_data else []

        raw_results = getattr(search_data, "results", None) or search_data or []
        search_results = []
        if isinstance(raw_results, list):
            for item in raw_results[:self._max_recall]:
                if isinstance(item, dict):
                    search_results.append(item)
                else:
                    search_results.append({
                        "memory": getattr(item, "memory", ""),
                        "similarity": getattr(item, "similarity", None),
                    })

        if not static and not dynamic and not search_results:
            return messages

        messages = list(messages)

        # System prompt: profile facts
        profile_lines = []
        for fact in static[:self._max_recall]:
            if fact:
                profile_lines.append(f"- {fact}")
        for fact in dynamic[:self._max_recall]:
            if fact:
                profile_lines.append(f"- {fact}")

        if profile_lines and messages and messages[0].get("role") == "system":
            sys_msg = {**messages[0]}
            block = (
                "\n\n<long-term-memory>\n"
                "# User Profile\n"
                + "\n".join(profile_lines)
                + "\n</long-term-memory>"
            )
            if "<long-term-memory>" not in (sys_msg.get("content") or ""):
                sys_msg["content"] = (sys_msg.get("content") or "") + block
                messages[0] = sys_msg

        # User message: search results
        memory_lines = []
        for item in search_results:
            mem_text = item.get("memory", "") if isinstance(item, dict) else ""
            if mem_text:
                memory_lines.append(f"- {mem_text[:300]}")

        if memory_lines:
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user":
                    user_copy = {**messages[i]}
                    context_block = (
                        "\n\n<memory-context>\n"
                        "[System note: Retrieved from long-term memory]\n"
                        + "\n".join(memory_lines)
                        + "\n</memory-context>"
                    )
                    user_copy["content"] = (
                        (user_copy.get("content") or "") + context_block)
                    messages[i] = user_copy
                    break

        return messages

    # -- on_messages -------------------------------------------------------

    async def on_messages(
        self, messages: List[Dict[str, Any]], **kwargs: Any,
    ) -> None:
        if not self._active or not self._auto_capture or not self._client:
            return

        self._turn_count += 1
        user_content = ""
        assistant_content = ""
        for m in messages:
            if m.get("role") == "user":
                user_content = _clean_for_capture(str(m.get("content", "")))
            elif m.get("role") == "assistant":
                assistant_content = _clean_for_capture(str(m.get("content", "")))

        if not user_content or not assistant_content:
            return
        if (len(user_content) < self._min_capture_len
                or len(assistant_content) < self._min_capture_len):
            return
        if _is_trivial(user_content):
            return

        content = (
            f"[role: user]\n{user_content[:3000]}\n[user:end]\n\n"
            f"[role: assistant]\n{assistant_content[:3000]}\n[assistant:end]"
        )
        self._background_add(content)

    # -- Tools -------------------------------------------------------------

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        if not self._active:
            return []
        return [_STORE_SCHEMA, _SEARCH_SCHEMA, _FORGET_SCHEMA, _PROFILE_SCHEMA]

    async def handle_tool_call(
        self, tool_name: str, arguments: Dict[str, Any],
    ) -> str:
        if not self._active or not self._client:
            return json.dumps({"error": "supermemory not configured"})

        if tool_name == "supermemory_store":
            return self._tool_store(arguments)
        elif tool_name == "supermemory_search":
            return self._tool_search(arguments)
        elif tool_name == "supermemory_forget":
            return self._tool_forget(arguments)
        elif tool_name == "supermemory_profile":
            return self._tool_profile(arguments)
        return json.dumps({"error": f"unknown tool: {tool_name}"})

    # -- Search ------------------------------------------------------------

    async def search(
        self, query: str, limit: int = 10,
    ) -> List[MemoryEntry]:
        if not self._active or not self._client:
            return []

        try:
            response = self._client.search.memories(
                q=query,
                container_tag=self._container_tag,
                limit=min(limit, 20),
                search_mode=self._search_mode,
            )
            entries = []
            for item in (getattr(response, "results", None) or []):
                entries.append(MemoryEntry(
                    id=getattr(item, "id", ""),
                    content=getattr(item, "memory", ""),
                    source="supermemory",
                    metadata={
                        "similarity": getattr(item, "similarity", None),
                    },
                ))
            return entries
        except Exception as e:
            logger.debug("[supermemory_backend] search failed: %s", e)
            return []

    # -- Cache -------------------------------------------------------------

    def invalidate(self) -> None:
        pass

    # -- Internal helpers --------------------------------------------------

    @staticmethod
    def _extract_query(messages: List[Dict[str, Any]]) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                content = m.get("content", "")
                return str(content)[:200].strip() if content else ""
        return ""

    def _background_add(self, content: str) -> None:
        """Add a memory document in a background thread."""
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=2.0)

        def _add():
            try:
                self._client.documents.add(
                    content=content,
                    container_tags=[self._container_tag],
                    entity_context=self._entity_context,
                    metadata={
                        "source": "ms-agent",
                        "type": "conversation_turn",
                    },
                )
            except Exception as e:
                logger.debug("[supermemory_backend] add failed: %s", e)

        self._sync_thread = threading.Thread(
            target=_add, daemon=True, name="supermemory-add")
        self._sync_thread.start()

    def _tool_store(self, args: Dict[str, Any]) -> str:
        content = str(args.get("content") or "").strip()
        if not content:
            return json.dumps({"error": "content is required"})

        metadata = args.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["source"] = "ms-agent-tool"

        try:
            result = self._client.documents.add(
                content=content,
                container_tags=[self._container_tag],
                entity_context=self._entity_context,
                metadata=metadata,
            )
            return json.dumps({
                "saved": True,
                "id": getattr(result, "id", ""),
                "preview": content[:80],
            })
        except Exception as e:
            return json.dumps({"error": f"Store failed: {e}"})

    def _tool_search(self, args: Dict[str, Any]) -> str:
        query = str(args.get("query") or "").strip()
        if not query:
            return json.dumps({"error": "query is required"})

        limit = max(1, min(20, int(args.get("limit", 5) or 5)))
        try:
            response = self._client.search.memories(
                q=query,
                container_tag=self._container_tag,
                limit=limit,
                search_mode=self._search_mode,
            )
            results = []
            for item in (getattr(response, "results", None) or []):
                entry: Dict[str, Any] = {
                    "id": getattr(item, "id", ""),
                    "content": getattr(item, "memory", ""),
                }
                sim = getattr(item, "similarity", None)
                if sim is not None:
                    try:
                        entry["similarity"] = round(float(sim) * 100)
                    except Exception:
                        pass
                results.append(entry)
            return json.dumps({"results": results, "count": len(results)})
        except Exception as e:
            return json.dumps({"error": f"Search failed: {e}"})

    def _tool_forget(self, args: Dict[str, Any]) -> str:
        memory_id = str(args.get("id") or "").strip()
        query = str(args.get("query") or "").strip()
        if not memory_id and not query:
            return json.dumps({"error": "Provide either id or query"})

        try:
            if memory_id:
                self._client.memories.forget(
                    container_tag=self._container_tag, id=memory_id)
                return json.dumps({"forgotten": True, "id": memory_id})

            response = self._client.search.memories(
                q=query,
                container_tag=self._container_tag,
                limit=5,
                search_mode=self._search_mode,
            )
            results = getattr(response, "results", None) or []
            if not results:
                return json.dumps({"error": "No matching memory found."})

            target = results[0]
            target_id = getattr(target, "id", "")
            if not target_id:
                return json.dumps({"error": "Best match has no id."})

            self._client.memories.forget(
                container_tag=self._container_tag, id=target_id)
            preview = (getattr(target, "memory", "") or "")[:100]
            return json.dumps({
                "forgotten": True,
                "id": target_id,
                "preview": preview,
            })
        except Exception as e:
            return json.dumps({"error": f"Forget failed: {e}"})

    def _tool_profile(self, args: Dict[str, Any]) -> str:
        query = str(args.get("query") or "").strip() or None
        try:
            profile = self._client.profile(
                container_tag=self._container_tag,
                q=query,
            )
            profile_data = getattr(profile, "profile", None)
            static = (getattr(profile_data, "static", []) or []) if profile_data else []
            dynamic = (getattr(profile_data, "dynamic", []) or []) if profile_data else []

            sections = []
            if static:
                sections.append(
                    "## Persistent Facts\n"
                    + "\n".join(f"- {item}" for item in static))
            if dynamic:
                sections.append(
                    "## Recent Context\n"
                    + "\n".join(f"- {item}" for item in dynamic))

            return json.dumps({
                "profile": "\n\n".join(sections),
                "static_count": len(static),
                "dynamic_count": len(dynamic),
            })
        except Exception as e:
            return json.dumps({"error": f"Profile failed: {e}"})


# -- Self-register ---------------------------------------------------------

backend_registry.register("supermemory", SupermemoryBackend)
