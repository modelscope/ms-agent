"""Unified Memory — a protocol-driven, backend-pluggable memory system.

Register ``unified_memory`` in ``memory_mapping`` to use this system.

Architecture::

    Orchestrator  --delegates-to-->  MemoryBackend (Protocol)
                                         |
                        +----------------+----------------+
                        v                v                v
                  FileBasedBackend  ReMeBackend    MempalaceBackend  ...
                  (built-in)       (adapter)      (adapter)

Switch backends via YAML config::

    storage:
      backend: "file"   # or "reme", "mempalace", "mem0", "byterover", "supermemory"
"""
from .config import MemoryConfig
from .orchestrator import MemoryOrchestrator
from .protocols import (
    BaseMemoryBackend,
    MemoryBackend,
    MemoryEntry,
    MemoryEvent,
    MemoryEventBus,
    MemoryNamespace,
)
from .registry import backend_registry

# Import backends so they self-register
from .backends import file_based as _fb  # noqa: F401

__all__ = [
    "MemoryConfig",
    "MemoryOrchestrator",
    # Layer 2 — primary contract
    "MemoryBackend",
    "BaseMemoryBackend",
    "backend_registry",
    # Layer 1 — data structures
    "MemoryEntry",
    "MemoryEvent",
    "MemoryEventBus",
    "MemoryNamespace",
]
