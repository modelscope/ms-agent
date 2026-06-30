"""Core data structures and the MemoryBackend contract.

Design hierarchy
================

Layer 1 -- **Data structures** (MemoryEntry, MemoryNamespace, MemoryEvent)
    Universal currency across all layers.  Framework-agnostic.

Layer 2 -- **MemoryBackend Protocol** (the primary contract)
    The *only* interface the Orchestrator programs against.  Every memory
    system -- built-in or external -- is exposed to the agent loop through
    this single Protocol.

Layer 3 -- **BaseMemoryBackend ABC**
    Convenience base class with sensible no-op defaults for every optional
    hook.  Adapter authors subclass this and override only what they need.

Layer 4 -- **MemoryEventBus Protocol**
    Decoupled event pub/sub for future service-oriented scenarios.

Fine-grained Protocols (MemoryStorage, MemoryRetriever, MemoryExtractor,
MemoryInjector) are NOT part of the public API.  They are internal
building blocks used by the built-in FileBasedBackend to compose a
memory system from interchangeable parts.  External backends (ReMe,
mempalace, mem0, byterover, supermemory) implement MemoryBackend directly.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)


# ===================================================================
# Layer 1 -- Data structures
# ===================================================================

@dataclass
class MemoryNamespace:
    """Isolation unit for multi-tenant scenarios.

    Phase 1 only uses *user_id*; the remaining fields are reserved for
    future service-oriented deployments.
    """
    user_id: str = "default"
    agent_id: str = "default"
    tenant_id: str = "local"

    @property
    def storage_key(self) -> str:
        return f"{self.tenant_id}/{self.user_id}/{self.agent_id}"


@dataclass
class MemoryEntry:
    """A single memory record -- the universal currency across all layers."""
    id: str = field(default_factory=lambda: f"mem_{uuid.uuid4().hex[:12]}")
    content: str = ""
    category: str = "knowledge"
    confidence: float = 0.8
    source: str = "session"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryEntry":
        return cls(**{k: v for k, v in data.items()
                      if k in cls.__dataclass_fields__})


@dataclass
class MemoryEvent:
    """Lightweight event emitted after every memory mutation."""
    event_type: str  # created | updated | deleted | searched
    namespace: MemoryNamespace = field(default_factory=MemoryNamespace)
    entry_ids: List[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "agent"


# ===================================================================
# Layer 2 -- MemoryBackend Protocol (the ONE contract)
# ===================================================================

@runtime_checkable
class MemoryBackend(Protocol):
    """Complete contract for a pluggable memory system.

    The Orchestrator delegates ALL memory logic to a MemoryBackend.
    It does not touch files, build snapshots, or format prompts -- the
    backend owns those decisions.

    Mapping to the agent loop (``LLMAgent``)::

        condense_memory()  ->  backend.inject(messages)
        add_memory()       ->  backend.on_messages(messages)
        (pre-compress)     ->  backend.on_pre_compress(messages)
        (consolidation)    ->  backend.consolidate(messages)
        (tool dispatch)    ->  backend.handle_tool_call(name, args)
        (agent shutdown)   ->  backend.close()
    """

    # -- Lifecycle ----------------------------------------------------

    async def start(self, **kwargs: Any) -> None:
        """Initialize resources (files, DBs, indexes).

        Called once before the first ``inject()``.  Typical kwargs:
            llm, base_dir, user_id, agent_id, session_id, platform
        """
        ...

    async def close(self) -> None:
        """Flush pending writes and release resources."""
        ...

    # -- Agent loop (called every step) --------------------------------

    async def inject(
        self, messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Inject memory context into *messages* before the LLM call.

        The backend decides WHAT/WHERE/HOW to inject.
        Must return a (possibly modified) message list without mutating
        the input.
        """
        ...

    async def on_messages(
        self, messages: List[Dict[str, Any]], **kwargs: Any,
    ) -> None:
        """Post-step hook -- persist observations from the latest messages."""
        ...

    # -- Compression hooks --------------------------------------------

    async def on_pre_compress(
        self, messages: List[Dict[str, Any]],
    ) -> None:
        """Extract and persist important info before messages are discarded."""
        ...

    async def consolidate(
        self, messages: List[Dict[str, Any]],
        target_remove_count: int = 0,
    ) -> List[Dict[str, Any]]:
        """Token-pressure-driven consolidation.

        Backends with their own session management (ReMe) may
        implement custom consolidation.  Others can use the no-op default
        in BaseMemoryBackend (the ContextAssembler handles compression).
        """
        ...

    # -- Tools --------------------------------------------------------

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Return tool definitions for the agent's ToolManager."""
        ...

    async def handle_tool_call(
        self, tool_name: str, arguments: Dict[str, Any],
    ) -> str:
        """Dispatch a tool call.  Returns a JSON-serializable string."""
        ...

    # -- Search -------------------------------------------------------

    async def search(
        self, query: str, limit: int = 10,
    ) -> List[MemoryEntry]:
        """Search memory.  Used by the orchestrator and external callers."""
        ...

    # -- Cache --------------------------------------------------------

    def invalidate(self) -> None:
        """Force the backend to rebuild its prompt cache on next inject()."""
        ...


# ===================================================================
# Layer 3 -- BaseMemoryBackend ABC (convenience base class)
# ===================================================================

class BaseMemoryBackend(ABC):
    """Convenience base class for MemoryBackend implementations.

    Required overrides (3 methods -- the minimum viable backend):
        ``inject``   -- inject memory into messages
        ``start``    -- initialize resources
        ``close``    -- release resources

    Everything else has a sensible no-op default.
    """

    # -- Required -----------------------------------------------------

    @abstractmethod
    async def start(self, **kwargs: Any) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def inject(
        self, messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]: ...

    # -- Optional (no-op defaults) ------------------------------------

    async def on_messages(
        self, messages: List[Dict[str, Any]], **kwargs: Any,
    ) -> None:
        pass

    async def on_pre_compress(
        self, messages: List[Dict[str, Any]],
    ) -> None:
        pass

    async def consolidate(
        self, messages: List[Dict[str, Any]],
        target_remove_count: int = 0,
    ) -> List[Dict[str, Any]]:
        return messages

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return []

    async def handle_tool_call(
        self, tool_name: str, arguments: Dict[str, Any],
    ) -> str:
        return f'{{"error": "unknown tool: {tool_name}"}}'

    async def search(
        self, query: str, limit: int = 10,
    ) -> List[MemoryEntry]:
        return []

    def invalidate(self) -> None:
        pass


# ===================================================================
# Layer 4 -- Event bus Protocol
# ===================================================================

@runtime_checkable
class MemoryEventBus(Protocol):
    """Decoupled event pub/sub.  Phase 1: in-memory queue."""

    async def publish(self, event: MemoryEvent) -> None: ...
    async def subscribe(
        self, event_type: str,
        callback: Callable[[MemoryEvent], Any],
    ) -> str: ...
    async def unsubscribe(self, subscription_id: str) -> None: ...
