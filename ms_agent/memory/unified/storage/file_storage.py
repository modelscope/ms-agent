"""FileMemoryStorage — MEMORY.md backed storage with atomic writes,
character budget, and entry-level add / replace / remove operations.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ms_agent.utils.logger import get_logger

from ..config import MemoryConfig
from ..protocols import MemoryEntry
from ..security import scan_content

logger = get_logger()


class FileMemoryStorage:
    """Phase 1 default storage — all state lives in a single MEMORY.md file.

    Supports two write modes:

    * **entry ops** (``add`` / ``replace`` / ``remove``) — fine-grained edits
      triggered by the interactive ``memory`` tool.
    * **full replace** — overwrites the entire file, used by the consolidation
      ``save_memory`` tool.

    All writes are *atomic* (write-to-temp then ``os.replace``).
    """

    def __init__(self, config: MemoryConfig):
        self.base_dir = Path(config.base_dir)
        self.memory_path = self.base_dir / config.memory_path
        self.char_limit = config.char_limit
        self.security_scan = config.security_scan
        self._content_cache: Optional[str] = None

    # ------------------------------------------------------------------
    # MemoryStorage protocol
    # ------------------------------------------------------------------

    async def save(self, entries: List[MemoryEntry]) -> List[str]:
        """Persist entries by appending to MEMORY.md (entry-level add)."""
        ids: List[str] = []
        for entry in entries:
            if self.security_scan:
                safe, reason = scan_content(entry.content)
                if not safe:
                    logger.warning(f"[file_storage] Skipped entry: {reason}")
                    continue
            self._add_entry(entry.content)
            ids.append(entry.id)
        return ids

    async def load(self, ids: List[str]) -> List[MemoryEntry]:
        """Load by id — not directly applicable for markdown storage.

        Returns single entry wrapping the full MEMORY.md content.
        """
        content = self._read()
        if content:
            return [MemoryEntry(id="memory_md", content=content,
                                category="knowledge")]
        return []

    async def delete(self, ids: List[str]) -> bool:
        return True

    async def list_all(
        self, filters: Optional[Dict[str, Any]] = None
    ) -> List[MemoryEntry]:
        content = self._read()
        if content:
            return [MemoryEntry(id="memory_md", content=content,
                                category="knowledge")]
        return []

    async def clear(self) -> bool:
        self._write("")
        return True

    # ------------------------------------------------------------------
    # Entry-level operations (used by the ``memory`` tool)
    # ------------------------------------------------------------------

    def _add_entry(self, content: str) -> bool:
        current = self._read()
        deduped = list(dict.fromkeys(
            [l for l in current.splitlines() if l.strip()] +
            [content.strip()]
        ))
        new_content = "\n".join(deduped) + "\n"
        if len(new_content) > self.char_limit:
            logger.warning(
                f"[file_storage] MEMORY.md would exceed char limit "
                f"({len(new_content)} > {self.char_limit}), skipping add"
            )
            return False
        self._write(new_content)
        return True

    def replace_entry(self, old_content: str, new_content: str) -> bool:
        if self.security_scan:
            safe, reason = scan_content(new_content)
            if not safe:
                logger.warning(f"[file_storage] Replace blocked: {reason}")
                return False
        current = self._read()
        if old_content.strip() not in current:
            logger.warning("[file_storage] Old content not found for replace")
            return False
        updated = current.replace(old_content.strip(), new_content.strip(), 1)
        if len(updated) > self.char_limit:
            logger.warning("[file_storage] Replace would exceed char limit")
            return False
        self._write(updated)
        return True

    def remove_entry(self, content: str) -> bool:
        current = self._read()
        target = content.strip()
        lines = current.splitlines()
        new_lines = [l for l in lines if l.strip() != target]
        if len(new_lines) == len(lines):
            # try substring match
            new_lines = [l for l in lines if target not in l]
        self._write("\n".join(new_lines) + "\n" if new_lines else "")
        return True

    def full_replace(self, content: str) -> bool:
        """Overwrite MEMORY.md entirely (used by consolidation)."""
        if self.security_scan:
            safe, reason = scan_content(content)
            if not safe:
                logger.warning(
                    f"[file_storage] Full replace blocked: {reason}")
                return False
        if len(content) > self.char_limit:
            content = content[:self.char_limit]
            logger.warning("[file_storage] Truncated to char limit")
        self._write(content)
        return True

    def get_content(self) -> str:
        return self._read()

    # ------------------------------------------------------------------
    # Raw archive fallback
    # ------------------------------------------------------------------

    def append_archive(self, content: str) -> None:
        """Append to ``.memory/archive.md`` when LLM consolidation fails."""
        archive_dir = self.base_dir / ".memory"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / "archive.md"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        block = f"\n---\n### Archive {ts}\n\n{content}\n"
        with open(archive_path, "a", encoding="utf-8") as f:
            f.write(block)
        logger.info(f"[file_storage] Appended to raw archive: {archive_path}")

    # ------------------------------------------------------------------
    # Internal I/O (atomic writes)
    # ------------------------------------------------------------------

    def _read(self) -> str:
        if self._content_cache is not None:
            return self._content_cache
        if self.memory_path.exists():
            content = self.memory_path.read_text(encoding="utf-8")
            self._content_cache = content
            return content
        return ""

    def _write(self, content: str) -> None:
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=self.memory_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, self.memory_path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        self._content_cache = content

    def invalidate_cache(self) -> None:
        self._content_cache = None
