"""MemoryOrchestrator — thin proxy that delegates to a MemoryBackend.

The Orchestrator itself contains NO business logic about storage formats,
prompt injection, retrieval strategies, or tool definitions.  All of that
lives inside the MemoryBackend implementation selected by configuration.

Registered as ``unified_memory`` in ``memory_mapping``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ms_agent.llm.utils import Message
from ms_agent.memory.base import Memory
from ms_agent.utils.logger import get_logger

from .config import MemoryConfig
from .protocols import MemoryBackend, MemoryEntry
from .registry import backend_registry

logger = get_logger()


class MemoryOrchestrator(Memory):
    """Thin adapter between the ms-agent ``Memory`` ABC and a
    ``MemoryBackend`` implementation.

    Responsibilities (and ONLY these):
    1. Parse config -> resolve the correct backend class from the registry.
    2. Forward ``run()`` -> ``backend.inject()``.
    3. Forward ``add()`` -> ``backend.on_messages()``.
    4. Expose ``flush()`` / ``search()`` / tool helpers as thin delegates.

    Everything else -- file I/O, snapshot caching, prompt formatting,
    tool definitions, security scanning -- is the backend's concern.
    """

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self.mem_config = self._parse_config(config)
        self._backend: Optional[MemoryBackend] = None
        self._started = False

    # ------------------------------------------------------------------
    # Lazy backend construction
    # ------------------------------------------------------------------

    def _get_backend(self) -> MemoryBackend:
        if self._backend is None:
            backend_name = self.mem_config.storage_backend
            cls = backend_registry.resolve(backend_name)
            self._backend = cls(self.mem_config)
            logger.info(
                f"[orchestrator] Created backend '{backend_name}' "
                f"-> {cls.__name__}")
        return self._backend

    async def _ensure_started(self, **kwargs: Any) -> MemoryBackend:
        backend = self._get_backend()
        if not self._started:
            await backend.start(**kwargs)
            self._started = True
        return backend

    # ------------------------------------------------------------------
    # Memory ABC -- run()
    # ------------------------------------------------------------------

    async def run(self, messages: List[Message]) -> List[Message]:
        if not self.mem_config.enabled:
            return messages

        backend = await self._ensure_started()
        msg_dicts = _messages_to_dicts(messages)
        injected = await backend.inject(msg_dicts)
        return _dicts_to_messages(injected)

    # ------------------------------------------------------------------
    # Memory ABC -- add()
    # ------------------------------------------------------------------

    async def add(self, messages: List[Message], **kwargs: Any) -> None:
        if not self.mem_config.enabled:
            return
        backend = await self._ensure_started()
        msg_dicts = _messages_to_dicts(messages)
        await backend.on_messages(msg_dicts, **kwargs)

    # ------------------------------------------------------------------
    # Flush (pre-compression)
    # ------------------------------------------------------------------

    async def flush(self, messages: List[Message]) -> None:
        if not self.mem_config.enabled:
            return
        backend = await self._ensure_started()
        msg_dicts = _messages_to_dicts(messages)
        await backend.on_pre_compress(msg_dicts)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(self, query: str, limit: int = 10) -> List[MemoryEntry]:
        backend = await self._ensure_started()
        return await backend.search(query, limit)

    # ------------------------------------------------------------------
    # Tool interface (called by the agent's ToolManager)
    # ------------------------------------------------------------------

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return self._get_backend().get_tool_schemas()

    async def handle_tool_call(
        self, tool_name: str, arguments: Dict[str, Any],
    ) -> str:
        backend = await self._ensure_started()
        return await backend.handle_tool_call(tool_name, arguments)

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def invalidate_snapshot(self) -> None:
        if self._backend is not None:
            self._backend.invalidate()

    # ------------------------------------------------------------------
    # LLM injection (for backends that need the agent's LLM)
    # ------------------------------------------------------------------

    def set_llm(self, llm: Any) -> None:
        backend = self._get_backend()
        if hasattr(backend, "set_llm"):
            backend.set_llm(llm)

    def init_update_queue(self) -> None:
        backend = self._get_backend()
        if hasattr(backend, "init_update_queue"):
            backend.init_update_queue()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def close(self) -> None:
        if self._backend is not None and self._started:
            await self._backend.close()
            self._started = False

    # ------------------------------------------------------------------
    # Config parsing
    # ------------------------------------------------------------------

    def _parse_config(self, config: Any) -> MemoryConfig:
        if isinstance(config, MemoryConfig):
            return config
        if hasattr(config, "memory") and hasattr(config.memory, "unified_memory"):
            return MemoryConfig.from_dict_config(config.memory.unified_memory)
        if hasattr(config, "unified_memory"):
            return MemoryConfig.from_dict_config(config.unified_memory)
        return MemoryConfig.from_dict_config(config)


# ===================================================================
# Message conversion helpers
# ===================================================================

def _messages_to_dicts(messages: List[Message]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for m in messages:
        if isinstance(m, dict):
            result.append(m)
        elif isinstance(m, Message):
            d: Dict[str, Any] = {"role": m.role, "content": m.content or ""}
            if m.tool_calls:
                d["tool_calls"] = m.tool_calls
            result.append(d)
        else:
            result.append({"role": "user", "content": str(m)})
    return result


def _dicts_to_messages(dicts: List[Dict[str, Any]]) -> List[Message]:
    result: List[Message] = []
    for d in dicts:
        if isinstance(d, Message):
            result.append(d)
        elif isinstance(d, dict):
            result.append(Message(
                role=d.get("role", "user"),
                content=d.get("content", ""),
                tool_calls=d.get("tool_calls"),
            ))
        else:
            result.append(Message(role="user", content=str(d)))
    return result
