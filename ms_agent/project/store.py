from __future__ import annotations

from pathlib import Path
from typing import Any

from ms_agent.utils.atomic_file import atomic_write_json
from ms_agent.utils.json_store import read_json


class JSONFileStore:
    """Atomic JSON file read/write. Writes to a temp file then renames to
    prevent corruption."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def exists(self) -> bool:
        return self._path.exists()

    def read(self) -> dict[str, Any]:
        return read_json(self._path)

    def write(self, data: dict[str, Any]) -> None:
        atomic_write_json(self._path, data)
