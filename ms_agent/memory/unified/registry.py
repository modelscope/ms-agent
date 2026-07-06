"""Backend registry — configuration-driven selection of MemoryBackend.

Usage::

    # Register at import time (each backend module calls this)
    backend_registry.register("file", FileBasedBackend)
    backend_registry.register("reme", ReMeBackend)

    # Orchestrator resolves at init time
    backend_cls = backend_registry.get("file")
    backend = backend_cls(config)

External backends can self-register via entry_points or explicit import.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Type

from .protocols import BaseMemoryBackend

logger = logging.getLogger(__name__)


class BackendRegistry:
    """Thread-safe registry mapping string keys to backend classes."""

    def __init__(self) -> None:
        self._backends: Dict[str, Type[BaseMemoryBackend]] = {}

    def register(
        self,
        name: str,
        cls: Type[BaseMemoryBackend],
        *,
        override: bool = False,
    ) -> None:
        if name in self._backends and not override:
            logger.warning(
                f"[registry] Backend '{name}' already registered "
                f"({self._backends[name].__name__}), skipping "
                f"{cls.__name__}. Pass override=True to replace.")
            return
        self._backends[name] = cls
        logger.debug(f"[registry] Registered backend '{name}' → {cls.__name__}")

    def get(self, name: str) -> Optional[Type[BaseMemoryBackend]]:
        return self._backends.get(name)

    def resolve(
        self, name: str, fallback: str = "file",
    ) -> Type[BaseMemoryBackend]:
        """Get a backend class or fall back to *fallback*."""
        cls = self._backends.get(name)
        if cls is not None:
            return cls
        logger.warning(
            f"[registry] Backend '{name}' not found. "
            f"Available: {list(self._backends)}. "
            f"Falling back to '{fallback}'.")
        cls = self._backends.get(fallback)
        if cls is None:
            raise ValueError(
                f"Neither '{name}' nor fallback '{fallback}' registered. "
                f"Available: {list(self._backends)}")
        return cls

    def list_available(self) -> list[str]:
        return list(self._backends.keys())


# Module-level singleton
backend_registry = BackendRegistry()
