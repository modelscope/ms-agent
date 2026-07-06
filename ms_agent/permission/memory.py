"""PermissionMemory: persist user ``allow_always`` decisions across sessions.

Two storage scopes:
  - Project: ``.ms_agent/permission_memory.json``
  - Global:  ``~/.ms_agent/permission_memory.json``

Session-level memory (``allow_session``) lives only in-process.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Sequence

from .matcher import PermissionMatcher


@dataclass(frozen=True)
class MemoryEntry:
    pattern: str
    scope: Literal['project', 'global']
    source: Literal['user', 'plugin', 'hook'] = 'user'
    created_at: str = ''


class PermissionMemory:
    """Manages persistent and session-level permission rules."""

    def __init__(
        self,
        project_path: str | Path | None = None,
        global_path: str | Path | None = None,
    ) -> None:
        self._matcher = PermissionMatcher()

        self._project_file: Path | None = None
        if project_path is not None:
            self._project_file = Path(project_path) / '.ms_agent' / 'permission_memory.json'

        if global_path is not None:
            self._global_file = Path(global_path)
        else:
            self._global_file = Path.home() / '.ms_agent' / 'permission_memory.json'

        self._project_entries: list[MemoryEntry] = []
        self._global_entries: list[MemoryEntry] = []
        self._session_patterns: list[str] = []

        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        pattern: str,
        scope: Literal['project', 'global'] = 'project',
        source: Literal['user', 'plugin', 'hook'] = 'user',
    ) -> None:
        entries = self._project_entries if scope == 'project' else self._global_entries
        if any(e.pattern == pattern for e in entries):
            return
        entry = MemoryEntry(
            pattern=pattern,
            scope=scope,
            source=source,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        entries.append(entry)
        self._save(scope)

    def add_session(self, pattern: str) -> None:
        if pattern not in self._session_patterns:
            self._session_patterns.append(pattern)

    def matches(self, tool_name: str, tool_args: dict[str, Any]) -> bool:
        for pattern in self._session_patterns:
            if self._matcher.match_with_content(pattern, tool_name, tool_args):
                return True
        for entry in self._project_entries:
            if self._matcher.match_with_content(entry.pattern, tool_name, tool_args):
                return True
        for entry in self._global_entries:
            if self._matcher.match_with_content(entry.pattern, tool_name, tool_args):
                return True
        return False

    def revoke(self, pattern: str) -> int:
        """Remove all entries matching the given pattern. Returns count removed."""
        count = 0
        before = len(self._project_entries)
        self._project_entries = [e for e in self._project_entries if e.pattern != pattern]
        count += before - len(self._project_entries)

        before = len(self._global_entries)
        self._global_entries = [e for e in self._global_entries if e.pattern != pattern]
        count += before - len(self._global_entries)

        self._session_patterns = [p for p in self._session_patterns if p != pattern]

        if count > 0:
            self._save('project')
            self._save('global')
        return count

    def list_all(self) -> list[MemoryEntry]:
        return list(self._project_entries) + list(self._global_entries)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        self._project_entries = self._load_file(self._project_file, 'project')
        self._global_entries = self._load_file(self._global_file, 'global')

    @staticmethod
    def _load_file(path: Path | None, scope: str) -> list[MemoryEntry]:
        if path is None or not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            return [
                MemoryEntry(
                    pattern=e['pattern'],
                    scope=e.get('scope', scope),
                    source=e.get('source', 'user'),
                    created_at=e.get('created_at', ''),
                )
                for e in data
            ]
        except (json.JSONDecodeError, KeyError, TypeError):
            return []

    def _save(self, scope: Literal['project', 'global']) -> None:
        if scope == 'project':
            self._save_file(self._project_file, self._project_entries)
        else:
            self._save_file(self._global_file, self._global_entries)

    @staticmethod
    def _save_file(path: Path | None, entries: list[MemoryEntry]) -> None:
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(e) for e in entries]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
