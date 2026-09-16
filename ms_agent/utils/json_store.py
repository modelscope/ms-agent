"""Strict JSON objects and short, atomic read-modify-write transactions."""
from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ms_agent.utils.atomic_file import atomic_write_json
from ms_agent.utils.file_lock import file_lock


def read_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        with path.open(encoding='utf-8') as stream:
            data = json.load(stream)
    except FileNotFoundError:
        return {}
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError(f'{path.name} must contain valid JSON') from None
    if not isinstance(data, dict):
        raise ValueError(f'{path.name} must contain a JSON object')
    return data


@contextmanager
def json_transaction(path: str | Path):
    """Apply changes to the latest object; abort on errors, skip unchanged writes."""
    with file_lock(path):
        data = read_json(path)
        before = copy.deepcopy(data)
        yield data
        if data != before:
            atomic_write_json(path, data)
