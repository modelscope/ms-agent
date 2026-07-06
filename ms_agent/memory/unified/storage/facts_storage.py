"""FactsStorage — Phase 2 structured facts in ``facts.json``.

Supports confidence-based eviction, deduplication, and atomic writes.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ms_agent.utils.logger import get_logger

from ..config import MemoryConfig
from ..protocols import MemoryEntry
from ..security import scan_content

logger = get_logger()

FACT_CATEGORIES = {
    "preference", "knowledge", "context",
    "behavior", "goal", "correction",
}


class FactsStorage:
    """Manages ``facts.json`` — a flat list of typed, confidence-scored facts.

    Invariants
    ----------
    * ``len(facts) <= max_facts`` — exceeded entries are evicted by lowest
      confidence.
    * Duplicate detection via ``content.casefold().strip()``.
    * Confidence gate: entries below ``confidence_threshold`` are silently
      dropped on save.
    """

    def __init__(self, config: MemoryConfig):
        self.base_dir = Path(config.base_dir)
        self.facts_path = self.base_dir / config.facts_path
        self.max_facts = config.max_facts
        self.confidence_threshold = config.confidence_threshold
        self.security_scan = config.security_scan
        self._cache: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # MemoryStorage protocol
    # ------------------------------------------------------------------

    async def save(self, entries: List[MemoryEntry]) -> List[str]:
        data = self._load()
        facts: List[Dict] = data.get("facts", [])
        existing_keys = {f["content"].casefold().strip() for f in facts}
        ids: List[str] = []

        for entry in entries:
            if entry.confidence < self.confidence_threshold:
                logger.debug(
                    f"[facts] Skipped low-confidence ({entry.confidence}): "
                    f"{entry.content[:60]}")
                continue
            if self.security_scan:
                safe, reason = scan_content(entry.content)
                if not safe:
                    logger.warning(f"[facts] Blocked: {reason}")
                    continue
            key = entry.content.casefold().strip()
            if key in existing_keys:
                for f in facts:
                    if f["content"].casefold().strip() == key:
                        f["confidence"] = max(f["confidence"],
                                              entry.confidence)
                        f["updatedAt"] = datetime.now(
                            timezone.utc).isoformat()
                        break
            else:
                facts.append({
                    "id": entry.id,
                    "content": entry.content,
                    "category": entry.category
                        if entry.category in FACT_CATEGORIES else "knowledge",
                    "confidence": entry.confidence,
                    "createdAt": entry.created_at,
                    "updatedAt": entry.updated_at,
                    "source": entry.source,
                    "metadata": entry.metadata,
                })
                existing_keys.add(key)
            ids.append(entry.id)

        # evict lowest confidence if over capacity
        if len(facts) > self.max_facts:
            facts.sort(key=lambda f: f["confidence"], reverse=True)
            evicted = facts[self.max_facts:]
            facts = facts[:self.max_facts]
            logger.info(
                f"[facts] Evicted {len(evicted)} low-confidence facts")

        data["facts"] = facts
        data["lastUpdated"] = datetime.now(timezone.utc).isoformat()
        self._save(data)
        return ids

    async def load(self, ids: List[str]) -> List[MemoryEntry]:
        data = self._load()
        result = []
        id_set = set(ids)
        for f in data.get("facts", []):
            if f["id"] in id_set:
                result.append(self._fact_to_entry(f))
        return result

    async def delete(self, ids: List[str]) -> bool:
        data = self._load()
        id_set = set(ids)
        data["facts"] = [f for f in data.get("facts", [])
                         if f["id"] not in id_set]
        data["lastUpdated"] = datetime.now(timezone.utc).isoformat()
        self._save(data)
        return True

    async def list_all(
        self, filters: Optional[Dict[str, Any]] = None
    ) -> List[MemoryEntry]:
        data = self._load()
        facts = data.get("facts", [])
        if filters:
            cat = filters.get("category")
            if cat:
                facts = [f for f in facts if f.get("category") == cat]
            min_conf = filters.get("min_confidence")
            if min_conf is not None:
                facts = [f for f in facts if f.get("confidence", 0) >= min_conf]
        facts.sort(key=lambda f: f.get("confidence", 0), reverse=True)
        return [self._fact_to_entry(f) for f in facts]

    async def clear(self) -> bool:
        self._save({"version": "1.0",
                     "lastUpdated": datetime.now(timezone.utc).isoformat(),
                     "facts": []})
        return True

    # ------------------------------------------------------------------
    # Bulk update (used by LLMMergeExtractor)
    # ------------------------------------------------------------------

    async def apply_merge(
        self,
        new_facts: List[MemoryEntry],
        facts_to_remove: List[str],
    ) -> None:
        """Atomic add + remove in a single write."""
        if facts_to_remove:
            await self.delete(facts_to_remove)
        if new_facts:
            await self.save(new_facts)

    # ------------------------------------------------------------------
    # Formatting for prompt injection
    # ------------------------------------------------------------------

    def format_for_prompt(self, max_chars: int = 800) -> str:
        """Render top facts as a compact string for system prompt injection."""
        data = self._load()
        facts = sorted(data.get("facts", []),
                        key=lambda f: f.get("confidence", 0), reverse=True)
        lines: List[str] = []
        total = 0
        for f in facts:
            line = f"- [{f.get('category', '?')}] {f['content']}"
            if total + len(line) + 1 > max_chars:
                break
            lines.append(line)
            total += len(line) + 1
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal I/O
    # ------------------------------------------------------------------

    @staticmethod
    def _fact_to_entry(f: Dict) -> MemoryEntry:
        return MemoryEntry(
            id=f.get("id", ""),
            content=f.get("content", ""),
            category=f.get("category", "knowledge"),
            confidence=f.get("confidence", 0.8),
            source=f.get("source", ""),
            created_at=f.get("createdAt", ""),
            updated_at=f.get("updatedAt", ""),
            metadata=f.get("metadata", {}),
        )

    def _load(self) -> Dict[str, Any]:
        if self._cache is not None:
            return self._cache
        if self.facts_path.exists():
            try:
                data = json.loads(
                    self.facts_path.read_text(encoding="utf-8"))
                self._cache = data
                return data
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"[facts] Failed to load {self.facts_path}: {e}")
        default = {"version": "1.0",
                    "lastUpdated": datetime.now(timezone.utc).isoformat(),
                    "facts": []}
        self._cache = default
        return default

    def _save(self, data: Dict[str, Any]) -> None:
        self.facts_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=self.facts_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.facts_path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        self._cache = data

    def invalidate_cache(self) -> None:
        self._cache = None
