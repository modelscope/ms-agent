"""WebUI-only field store (``<home>/webui_meta.json``).

Holds fields the SDK does not model so the frontend keeps working unchanged:
project description / auto-attach toggles, session preview, profile
agent_calls_user, agent-settings auto-attach masters, provider enabled /
generation params, model display/advanced params, and per-project memory items.

Generic nested store: section -> key -> value. Read-modify-write under a lock
(management routes run in the threadpool)."""
from __future__ import annotations

from pathlib import Path

from ms_agent.utils.atomic_file import atomic_write_json
from ms_agent.utils.file_lock import file_lock
from ms_agent.utils.json_store import read_json

from app.backends.ms_agent.common import home


def _path() -> Path:
    return Path(home()) / "webui_meta.json"


def transaction_lock():
    return file_lock(_path())


def _load() -> dict:
    return read_json(_path())


def _save(data: dict) -> None:
    atomic_write_json(_path(), data)


def get(section: str, key: str, default=None):
    with transaction_lock():
        return _load().get(section, {}).get(key, default)


def section(name: str) -> dict:
    with transaction_lock():
        return dict(_load().get(name, {}))


def put(section: str, key: str, value) -> None:
    with transaction_lock():
        data = _load()
        data.setdefault(section, {})[key] = value
        _save(data)


def merge(section: str, key: str, patch: dict) -> None:
    """Deep-merge a dict patch into section[key] (creating it as {})."""
    with transaction_lock():
        data = _load()
        current = data.setdefault(section, {}).setdefault(key, {})
        if not isinstance(current, dict):
            current = {}
        current.update(patch)
        data[section][key] = current
        _save(data)


def drop(section: str, key: str) -> None:
    with transaction_lock():
        data = _load()
        if section in data and key in data[section]:
            del data[section][key]
            _save(data)
