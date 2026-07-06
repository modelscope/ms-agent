"""FTSRetriever — Phase 2 SQLite FTS5 full-text search over session JSONL.

Supports CJK character splitting (QwenPaw-style ``tokenize_query``) and
returns ranked snippets that can be LLM-summarised before injection.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

from ms_agent.utils.logger import get_logger

from ..config import MemoryConfig
from ..protocols import MemoryEntry

logger = get_logger()


def _is_cjk(char: str) -> bool:
    """Return True if *char* is a CJK ideograph."""
    try:
        name = unicodedata.name(char, "")
    except ValueError:
        return False
    return "CJK" in name


def tokenize_query(text: str, max_tokens: int = 50) -> str:
    """CJK-aware tokenization: split Chinese characters individually while
    keeping English words intact.  Capped at *max_tokens* terms.
    """
    tokens: List[str] = []
    buf: List[str] = []
    for ch in text:
        if _is_cjk(ch):
            if buf:
                tokens.append("".join(buf))
                buf.clear()
            tokens.append(ch)
        elif ch.isalnum() or ch == '_':
            buf.append(ch)
        else:
            if buf:
                tokens.append("".join(buf))
                buf.clear()
    if buf:
        tokens.append("".join(buf))
    tokens = tokens[:max_tokens]
    return " OR ".join(f'"{t}"' for t in tokens if t.strip())


class FTSRetriever:
    """Builds and queries a SQLite FTS5 index over session JSONL files."""

    def __init__(self, config: MemoryConfig):
        self.config = config
        self.base_dir = Path(config.base_dir)
        db_dir = self.base_dir / ".memory"
        db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_dir / "index.db"
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_schema()

    # ------------------------------------------------------------------
    # MemoryRetriever protocol
    # ------------------------------------------------------------------

    async def search(
        self, query: str, limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryEntry]:
        if not query or not query.strip():
            return []
        fts_query = tokenize_query(query,
                                   max_tokens=self.config.max_search_results)
        if not fts_query:
            return []
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT content, session_key, role, rank "
                "FROM sessions_fts WHERE sessions_fts MATCH ? "
                "ORDER BY rank LIMIT ?",
                (fts_query, limit),
            ).fetchall()
        except sqlite3.OperationalError as e:
            logger.debug(f"[fts] Query failed: {e}")
            return []

        results: List[MemoryEntry] = []
        for content, session_key, role, rank in rows:
            results.append(MemoryEntry(
                id=f"fts_{session_key}_{abs(hash(content)) % 10**8}",
                content=content,
                category="context",
                confidence=min(1.0, max(0.0, 1.0 + rank)),
                source=session_key,
                metadata={"role": role, "fts_rank": rank},
            ))
        return results

    # ------------------------------------------------------------------
    # Index maintenance
    # ------------------------------------------------------------------

    def index_session(self, session_key: str, messages: List[Dict]) -> int:
        """(Re-)index all messages from a session JSONL file."""
        conn = self._get_conn()
        conn.execute(
            "DELETE FROM session_messages WHERE session_key = ?",
            (session_key,))
        count = 0
        for msg in messages:
            if msg.get("_type") == "metadata":
                continue
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not content or not isinstance(content, str):
                continue
            conn.execute(
                "INSERT INTO session_messages (content, session_key, role) "
                "VALUES (?, ?, ?)",
                (content, session_key, role))
            count += 1
        conn.commit()
        return count

    def index_sessions_dir(self) -> int:
        """Walk ``sessions/`` and index all JSONL files."""
        sessions_dir = self.base_dir / "sessions"
        if not sessions_dir.exists():
            return 0
        total = 0
        for p in sessions_dir.glob("*.jsonl"):
            messages = []
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            total += self.index_session(p.stem, messages)
        logger.info(f"[fts] Indexed {total} messages from sessions/")
        return total

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
        return self._conn

    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS session_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                session_key TEXT NOT NULL,
                role TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
                content, session_key, role,
                content=session_messages,
                content_rowid=id
            );
            CREATE TRIGGER IF NOT EXISTS session_messages_ai
            AFTER INSERT ON session_messages BEGIN
                INSERT INTO sessions_fts(rowid, content, session_key, role)
                VALUES (new.id, new.content, new.session_key, new.role);
            END;
            CREATE TRIGGER IF NOT EXISTS session_messages_ad
            AFTER DELETE ON session_messages BEGIN
                INSERT INTO sessions_fts(sessions_fts, rowid, content, session_key, role)
                VALUES ('delete', old.id, old.content, old.session_key, old.role);
            END;
        """)
        conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
