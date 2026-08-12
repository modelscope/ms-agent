"""WebUI-only field store (``<home>/webui_meta.json``).

Holds fields the SDK does not model so the frontend keeps working unchanged:
project description / auto-attach toggles, session preview, profile
agent_calls_user, agent-settings auto-attach masters, provider enabled /
generation params, model display/advanced params, and per-project memory items.

Generic nested store: section -> key -> value. Read-modify-write under a lock
(management routes run in the threadpool)."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from app.backends.ms_agent.common import home

_lock = threading.Lock()


def _path() -> Path:
    return Path(home()) / "webui_meta.json"


def _load() -> dict:
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def get(section: str, key: str, default=None):
    with _lock:
        return _load().get(section, {}).get(key, default)


def section(name: str) -> dict:
    with _lock:
        return dict(_load().get(name, {}))


def put(section: str, key: str, value) -> None:
    with _lock:
        data = _load()
        data.setdefault(section, {})[key] = value
        _save(data)


def merge(section: str, key: str, patch: dict) -> None:
    """Deep-merge a dict patch into section[key] (creating it as {})."""
    with _lock:
        data = _load()
        current = data.setdefault(section, {}).setdefault(key, {})
        if not isinstance(current, dict):
            current = {}
        current.update(patch)
        data[section][key] = current
        _save(data)


def drop(section: str, key: str) -> None:
    with _lock:
        data = _load()
        if section in data and key in data[section]:
            del data[section][key]
            _save(data)
