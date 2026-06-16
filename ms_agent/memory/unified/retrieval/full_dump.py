"""FullDumpRetriever — loads MEMORY.md in its entirety and injects it
into the system prompt as a frozen snapshot (Phase 1 default).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..config import MemoryConfig
from ..protocols import MemoryEntry
from ..storage.file_storage import FileMemoryStorage


class FullDumpRetriever:
    """Simply returns the whole MEMORY.md content wrapped in a MemoryEntry.

    The orchestrator is responsible for injecting the returned content into
    the system prompt's frozen snapshot section.
    """

    def __init__(self, config: MemoryConfig,
                 storage: FileMemoryStorage):
        self.storage = storage
        self.config = config

    async def search(
        self, query: str, limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryEntry]:
        content = self.storage.get_content()
        if not content or not content.strip():
            return []
        return [MemoryEntry(
            id="full_dump",
            content=content.strip(),
            category="knowledge",
            confidence=1.0,
            source="MEMORY.md",
        )]
