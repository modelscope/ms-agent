from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class FileEntry:
    name: str
    type: str
    size: int = 0
    modified: str = ''
    children_count: int = 0


class Workspace:
    """Project workspace file operations. All paths are validated against traversal."""

    def __init__(self, workspace_root: str | Path) -> None:
        self._root = Path(workspace_root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def list_dir(self, rel_path: str = '.') -> list[FileEntry]:
        target = self._resolve_safe(rel_path)
        if not target.is_dir():
            raise FileNotFoundError(f'Not a directory: {rel_path}')
        entries: list[FileEntry] = []
        for item in sorted(target.iterdir()):
            if item.name.startswith('.'):
                continue
            if item.is_dir():
                children = sum(
                    1 for c in item.iterdir() if not c.name.startswith('.')
                )
                entries.append(
                    FileEntry(name=item.name, type='dir', children_count=children)
                )
            else:
                stat = item.stat()
                entries.append(
                    FileEntry(
                        name=item.name,
                        type='file',
                        size=stat.st_size,
                        modified=datetime.fromtimestamp(
                            stat.st_mtime, tz=timezone.utc
                        ).isoformat(),
                    )
                )
        return entries

    def read_file(self, rel_path: str) -> str:
        target = self._resolve_safe(rel_path)
        if not target.is_file():
            raise FileNotFoundError(f'Not a file: {rel_path}')
        return target.read_text(encoding='utf-8')

    def write_file(self, rel_path: str, content: str) -> None:
        target = self._resolve_safe(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')

    def delete(self, rel_path: str) -> None:
        target = self._resolve_safe(rel_path)
        if not target.exists():
            raise FileNotFoundError(f'Path not found: {rel_path}')
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    def import_path(self, source: str) -> None:
        src = Path(source).resolve()
        if not src.exists():
            raise FileNotFoundError(f'Source not found: {source}')
        dest = self._root / src.name
        if src.is_dir():
            shutil.copytree(src, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dest)

    def _resolve_safe(self, rel_path: str) -> Path:
        target = (self._root / rel_path).resolve()
        if not str(target).startswith(str(self._root)):
            raise PermissionError(f'Path traversal blocked: {rel_path}')
        return target
