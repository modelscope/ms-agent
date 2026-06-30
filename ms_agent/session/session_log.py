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

**Mutable metadata lives in a sidecar file**, not in the main log.  Values
that change during a session (``last_consolidated``, ``round``, ``status``,
``title``) are stored in ``{session_key}.meta.json`` and updated with a small
atomic write.  This keeps the main ``.jsonl`` strictly append-only: it is
never rewritten, so a crash can never corrupt the message history.  The main
log still carries an immutable header (``session_key`` / ``created_at``) on
its first line so it remains self-describing.

JSONL format::

    {"_type": "metadata", "session_key": "abc", "created_at": "..."}
    {"role": "system", "content": "...", "seq": 0, "timestamp": "..."}
    {"role": "user",   "content": "...", "seq": 1, "timestamp": "...", "tokens": 42}
    {"_type": "compaction_event", "seq": 4, "strategy": "summary_compactor", ...}

Sidecar (``{session_key}.meta.json``)::

    {"session_key": "abc", "created_at": "...", "last_consolidated": 0,
     "round": 0, "title": "", "status": "idle"}
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
        self._meta_path = self._dir / f"{self.session_key}.meta.json"

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
        return self._read_meta().get("last_consolidated", 0)

    @last_consolidated.setter
    def last_consolidated(self, value: int) -> None:
        self._update_meta("last_consolidated", value)

    @property
    def round(self) -> int:
        """The last persisted agent-loop round (for resume)."""
        return self._read_meta().get("round", 0)

    @round.setter
    def round(self, value: int) -> None:
        self._update_meta("round", value)

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
        meta = self._read_meta()
        all_msgs = self.get_all_messages()
        return {
            "session_key": self.session_key,
            "created_at": meta.get("created_at", ""),
            "title": meta.get("title", ""),
            "status": meta.get("status", "idle"),
            "last_consolidated": meta.get("last_consolidated", 0),
            "round": meta.get("round", 0),
            "message_count": len(all_msgs),
            "total_tokens": sum(m.get("tokens", 0) for m in all_msgs),
        }

    def set_metadata_field(self, key: str, value: Any) -> None:
        """Update a single metadata field (e.g. title, status)."""
        self._update_meta(key, value)

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

    def _default_meta(self, created_at: str) -> Dict[str, Any]:
        return {
            "session_key": self.session_key,
            "created_at": created_at,
            "last_consolidated": 0,
            "round": 0,
            "title": "",
            "status": "idle",
        }

    def _ensure_metadata(self) -> None:
        """Create the immutable log header and the mutable sidecar if missing."""
        if not self._path.exists():
            created_at = datetime.now(timezone.utc).isoformat()
            header = {
                "_type": "metadata",
                "session_key": self.session_key,
                "created_at": created_at,
            }
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                f.write(json.dumps(header, ensure_ascii=False) + "\n")
            self._write_meta(self._default_meta(created_at))
        else:
            # Scan existing file to set seq counter
            self._load_all_to_set_seq()
            # Make sure a sidecar exists (migrates legacy header-based metadata)
            self._read_meta()

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

    def _read_meta(self) -> Dict[str, Any]:
        """Load mutable metadata from the sidecar (cached).

        Falls back to migrating a legacy in-log metadata header the first time
        a pre-sidecar session is opened.
        """
        if self._metadata is not None:
            return self._metadata

        # 1. Preferred: the sidecar file.
        if self._meta_path.exists():
            try:
                self._metadata = json.loads(
                    self._meta_path.read_text(encoding="utf-8"))
                return self._metadata
            except (json.JSONDecodeError, OSError):
                pass

        # 2. Migration: read a legacy header from the main log, persist sidecar.
        legacy = self._read_legacy_header()
        if legacy is not None:
            meta = self._default_meta(legacy.get("created_at", ""))
            for key in ("last_consolidated", "round", "title", "status"):
                if key in legacy:
                    meta[key] = legacy[key]
            self._write_meta(meta)
            return self._metadata  # set by _write_meta

        # 3. Brand new / unreadable: defaults.
        self._metadata = self._default_meta("")
        return self._metadata

    def _update_meta(self, key: str, value: Any) -> None:
        meta = dict(self._read_meta())
        meta[key] = value
        self._write_meta(meta)

    def _write_meta(self, meta: Dict[str, Any]) -> None:
        """Atomically persist the sidecar (write temp + os.replace)."""
        tmp = self._meta_path.parent / (self._meta_path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(meta, ensure_ascii=False, indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._meta_path)
        self._metadata = meta

    def _read_legacy_header(self) -> Optional[Dict[str, Any]]:
        """Return the first-line metadata record of the main log, if any."""
        if not self._path.exists():
            return None
        with open(self._path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        if first_line:
            try:
                record = json.loads(first_line)
                if record.get("_type") == "metadata":
                    return record
            except json.JSONDecodeError:
                pass
        return None

    def _append_line(self, record: Dict[str, Any]) -> None:
        """Append a single JSON line and flush."""
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
