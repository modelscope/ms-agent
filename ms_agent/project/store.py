from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JSONFileStore:
    """Atomic JSON file read/write. Writes to .tmp then renames to prevent corruption."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def exists(self) -> bool:
        return self._path.exists()

    def read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        with open(self._path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.rename(self._path)
