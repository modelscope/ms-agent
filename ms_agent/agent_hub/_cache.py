# Copyright (c) ModelScope Contributors. All rights reserved.
"""Agent cache path helpers.

Cache layout (under ``~/.cache/modelscope/agent/``)::

::

    agent/
    ├── {name}_{timestamp}.zip   # local backups
    ├── sync_{name}.json         # bidirectional sync baseline
    ├── logs/watch.log           # runtime logs
    └── watch.pid                # background process PID

Honours ``MODELSCOPE_CACHE`` via :class:`~modelscope_hub.config.HubConfig`.
"""
from __future__ import annotations

import json
from pathlib import Path

__all__ = [
    'cache_dir',
    'log_file',
    'pid_file',
    'stop_file',
    'sync_state_file',
    'load_sync_state',
    'save_sync_state',
]


def _agent_home() -> Path:
    """Agent data root directory (derives from HubConfig.cache_dir)."""
    from modelscope_hub.config import get_default_config

    return get_default_config().cache_dir / 'agent'


def cache_dir() -> Path:
    """Root cache directory for agent operations."""
    d = _agent_home()
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_file() -> Path:
    """Log file path for the watch daemon."""
    d = cache_dir() / 'logs'
    d.mkdir(parents=True, exist_ok=True)
    return d / 'watch.log'


def pid_file() -> Path:
    """PID file for the background watch process."""
    return cache_dir() / 'watch.pid'


def stop_file() -> Path:
    """Stop signal file: presence tells the watch loop to exit gracefully.

    Cross-platform mechanism -- works on both Unix and Windows where signal
    delivery is unreliable.
    """
    return cache_dir() / 'watch.stop'


# ---- Sync state persistence ----


def sync_state_file(name: str) -> Path:
    """Sync state file: ``{cache}/sync_{name}.json``."""
    return cache_dir() / f'sync_{name}.json'


def load_sync_state(name: str) -> dict:
    """Load sync state from disk.

    Returns ``{"remote_files": {}}``
    if the file does not exist or is corrupted.
    """
    default: dict = {'remote_files': {}}
    path = sync_state_file(name)
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return default
        data.setdefault('remote_files', {})
        data.pop('local_files', None)
        data.pop('last_commit_date', None)  # legacy: no longer tracked
        return data
    except (json.JSONDecodeError, OSError):
        return default


def save_sync_state(name: str, remote_files: dict[str, str]) -> None:
    """Persist sync state to disk (atomic write)."""
    path = sync_state_file(name)
    tmp = path.with_suffix('.tmp')
    payload = json.dumps(
        {
            'remote_files': remote_files,
        },
        ensure_ascii=False,
        indent=2,
    )
    tmp.write_text(payload, encoding='utf-8')
    tmp.replace(path)
