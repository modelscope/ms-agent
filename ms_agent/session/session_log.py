"""SessionLog — append-only JSONL session log.

The source of truth for message history.  Every message is appended with
a monotonic ``seq`` number; nothing is ever overwritten or deleted.
Compaction events are recorded as special markers so that the full timeline
(including *when* and *why* context was compressed) is preserved.

``last_consolidated`` stores a **seq** value (not an array index).  The
visible window consists of all messages whose ``seq >= last_consolidated``.
Because compaction_events are filtered out of ``get_all_messages()``, using
seq avoids the fragile mapping between array positions and JSONL line
numbers.

JSONL format::

    {"_type": "metadata", "session_key": "abc", "created_at": "...", "last_consolidated": 0, ...}
    {"role": "system", "content": "...", "seq": 0, "timestamp": "..."}
    {"role": "user",   "content": "...", "seq": 1, "timestamp": "...", "tokens": 42}
    {"_type": "compaction_event", "seq": 4, "strategy": "summary_compactor", ...}
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class SessionLog:
    """Append-only JSONL session log — the source of truth for message history."""

    def __init__(
        self,
        session_dir: str | Path,
        session_key: str | None = None,
    ) -> None:
        self._dir = Path(session_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self.session_key = session_key or f"session_{uuid.uuid4().hex[:8]}"
        self._path = self._dir / f"{self.session_key}.jsonl"

        self._metadata: Optional[Dict[str, Any]] = None
        self._messages: Optional[List[Dict[str, Any]]] = None
        self._seq: int = 0

        self._ensure_metadata()

    # ------------------------------------------------------------------
    # Write path (append-only)
    # ------------------------------------------------------------------

    def append(self, message: Dict[str, Any]) -> int:
        """Append a message record.  Returns its ``seq`` number.

        The write is crash-safe: each line is flushed individually.
        """
        seq = self._next_seq()
        record: Dict[str, Any] = {**message, "seq": seq}
        if "timestamp" not in record:
            record["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._append_line(record)
        if self._messages is not None:
            self._messages.append(record)
        return seq

    def append_messages(self, messages: List[Dict[str, Any]]) -> List[int]:
        """Append multiple messages.  Returns list of seq numbers."""
        return [self.append(m) for m in messages]

    def record_compaction(self, event: Dict[str, Any]) -> None:
        """Record a compaction event (non-destructive marker)."""
        seq = self._next_seq()
        record = {
            "_type": "compaction_event",
            "seq": seq,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        self._append_line(record)

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    @property
    def last_consolidated(self) -> int:
        meta = self._load_metadata()
        return meta.get("last_consolidated", 0)

    @last_consolidated.setter
    def last_consolidated(self, value: int) -> None:
        meta = self._load_metadata()
        meta["last_consolidated"] = value
        self._rewrite_metadata(meta)

    def get_all_messages(self) -> List[Dict[str, Any]]:
        """All messages (excluding metadata and compaction events)."""
        if self._messages is not None:
            return self._messages
        msgs: List[Dict[str, Any]] = []
        if not self._path.exists():
            self._messages = msgs
            return msgs
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("_type") in ("metadata", "compaction_event"):
                continue
            msgs.append(record)
        self._messages = msgs
        # Update seq counter to be past the last message
        if msgs:
            max_seq = max(m.get("seq", 0) for m in msgs)
            self._seq = max(self._seq, max_seq + 1)
        return msgs

    def get_visible_messages(self) -> List[Dict[str, Any]]:
        """Messages whose ``seq >= last_consolidated`` (the LLM window).

        Because ``last_consolidated`` is a seq value, this correctly skips
        compaction_events (which are filtered by ``get_all_messages``) without
        relying on fragile array-index arithmetic.
        """
        all_msgs = self.get_all_messages()
        lc_seq = self.last_consolidated
        for i, m in enumerate(all_msgs):
            if m.get("seq", 0) >= lc_seq:
                return all_msgs[i:]
        return []

    def get_compaction_events(self) -> List[Dict[str, Any]]:
        """All compaction events in chronological order."""
        events: List[Dict[str, Any]] = []
        if not self._path.exists():
            return events
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("_type") == "compaction_event":
                events.append(record)
        return events

    def get_metadata(self) -> Dict[str, Any]:
        """Session metadata (title, created_at, status, counts, etc.)."""
        meta = self._load_metadata()
        all_msgs = self.get_all_messages()
        return {
            "session_key": self.session_key,
            "created_at": meta.get("created_at", ""),
            "title": meta.get("title", ""),
            "status": meta.get("status", "idle"),
            "last_consolidated": meta.get("last_consolidated", 0),
            "message_count": len(all_msgs),
            "total_tokens": sum(m.get("tokens", 0) for m in all_msgs),
        }

    def set_metadata_field(self, key: str, value: Any) -> None:
        """Update a single metadata field (e.g. title, status)."""
        meta = self._load_metadata()
        meta[key] = value
        self._rewrite_metadata(meta)

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def invalidate_cache(self) -> None:
        """Force re-read from disk on next access."""
        self._metadata = None
        self._messages = None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq += 1
        return seq

    def _ensure_metadata(self) -> None:
        """Write the metadata header if the file does not exist yet."""
        if not self._path.exists():
            meta = {
                "_type": "metadata",
                "session_key": self.session_key,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_consolidated": 0,
                "title": "",
                "status": "idle",
            }
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                f.write(json.dumps(meta, ensure_ascii=False) + "\n")
            self._metadata = meta
        else:
            # Scan existing file to set seq counter
            self._load_all_to_set_seq()

    def _load_all_to_set_seq(self) -> None:
        """Scan the file to find the highest seq number."""
        max_seq = -1
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                s = record.get("seq", -1)
                if s > max_seq:
                    max_seq = s
            except json.JSONDecodeError:
                continue
        self._seq = max_seq + 1

    def _load_metadata(self) -> Dict[str, Any]:
        if self._metadata is not None:
            return self._metadata
        if not self._path.exists():
            self._metadata = {"last_consolidated": 0}
            return self._metadata
        with open(self._path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        if first_line:
            try:
                record = json.loads(first_line)
                if record.get("_type") == "metadata":
                    self._metadata = record
                    return record
            except json.JSONDecodeError:
                pass
        self._metadata = {"last_consolidated": 0}
        return self._metadata

    def _rewrite_metadata(self, meta: Dict[str, Any]) -> None:
        """Rewrite the first line (metadata header) of the JSONL file."""
        if not self._path.exists():
            self._ensure_metadata()
            return
        lines = self._path.read_text(encoding="utf-8").splitlines()
        meta_line = json.dumps(
            {**meta, "_type": "metadata"}, ensure_ascii=False
        )
        if lines and lines[0].strip():
            try:
                first = json.loads(lines[0])
                if first.get("_type") == "metadata":
                    lines[0] = meta_line
                else:
                    lines.insert(0, meta_line)
            except json.JSONDecodeError:
                lines.insert(0, meta_line)
        else:
            lines.insert(0, meta_line)
        self._path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._metadata = meta

    def _append_line(self, record: Dict[str, Any]) -> None:
        """Append a single JSON line and flush."""
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
