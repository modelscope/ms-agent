# Copyright (c) ModelScope Contributors. All rights reserved.
"""Explicit catalog refresh. Queries remain offline and pinned for the process."""
from __future__ import annotations

import asyncio
import json
import math
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import model_catalog as catalog

_UPDATE_LOCK = threading.Lock()
_REFRESH_SECONDS = 24 * 3600
_RETRY_SECONDS = 15 * 60


def cache_dir() -> Path:
    from ms_agent.project.paths import global_home
    return global_home() / 'cache' / 'models.dev' / 'v1'


def policy() -> str:
    """auto: source startup refresh; local: cache allowed; bundled: fixed data."""
    value = os.environ.get('MS_AGENT_MODEL_CATALOG', 'auto').lower()
    if value not in ('auto', 'local', 'bundled'):
        raise ValueError(
            'MS_AGENT_MODEL_CATALOG must be auto, local or bundled')
    return value


def _state() -> dict:
    try:
        value = json.loads((cache_dir() / 'state.json').read_text())
        if (not isinstance(value, dict)
                or type(value.get('checked_at')) not in (int, float)
                or not math.isfinite(value['checked_at'])):
            return {}
        return value
    except (OSError, ValueError):
        return {}


def cached_bundle():
    if policy() == 'bundled':
        return None
    try:
        name = (cache_dir() / 'current').read_text().strip()
        if not name or Path(name).name != name or not name.startswith(
                'version-'):
            return None
        return catalog.validate_bundle(cache_dir() / name)
    except (OSError, ValueError, TypeError, RecursionError):
        return None


def choose_bundle(bundled):
    cached = cached_bundle()
    if cached and (not bundled
                   or _timestamp(cached[1]) > _timestamp(bundled[1])):
        return cached[0], dict(cached[1], location='cache')
    if bundled:
        return bundled[0], dict(bundled[1], location='bundled')
    return None


def _timestamp(manifest):
    return datetime.fromisoformat(manifest['fetched_at'].replace(
        'Z', '+00:00'))


def status() -> dict:
    active = catalog.catalog_info()
    try:
        bundled = catalog.validate_bundle(catalog.DATA_DIR)
    except (OSError, ValueError, TypeError, RecursionError):
        bundled = None
    candidate = choose_bundle(bundled)
    pending = candidate[1] if candidate and candidate[1]['revision'] != active[
        'revision'] else None
    return {
        'active': active,
        'pending': pending,
        'policy': policy(),
        'last_check': _state(),
        'updating': _UPDATE_LOCK.locked()
    }


async def download(timeout: float = 8) -> bytes:
    return await catalog.download(timeout)


def _publish(raw: bytes, fetched_at: str) -> dict:
    from ms_agent.utils.atomic_file import atomic_write_json, atomic_write_text

    manifest = catalog.manifest_for(raw, fetched_at)
    root = cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
            prefix='.download-', dir=root) as temporary:
        stage = Path(temporary)
        for name, data in ((catalog.SNAPSHOT, raw),
                           ('LICENSE',
                            (catalog.DATA_DIR / 'LICENSE').read_bytes())):
            with (stage / name).open('wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        atomic_write_json(stage / catalog.MANIFEST, manifest, fsync=True)
        catalog.validate_bundle(stage)
        # Publish the entire validated directory before switching the pointer.
        version = 'version-' + stage.name.removeprefix('.download-')
        os.replace(stage, root / version)
        atomic_write_text(root / 'current', version, fsync=True)
    return manifest


async def update(*, force: bool = False, timeout: float = 8) -> dict:
    """Refresh user data only; cancellation never publishes a partial download."""
    from ms_agent.utils.atomic_file import atomic_write_json
    from ms_agent.utils.file_lock import file_lock

    if policy() == 'bundled':
        return {'result': 'disabled'}
    if not _UPDATE_LOCK.acquire(blocking=False):
        return {'result': 'busy'}
    try:
        with file_lock(cache_dir() / 'update', timeout=0):
            previous = _state()
            interval = _REFRESH_SECONDS if previous.get(
                'result') == 'updated' else _RETRY_SECONDS
            if (not force and
                    time.time() - previous.get('checked_at', 0) < interval):
                if previous.get('result') != 'updated' or cached_bundle():
                    return {'result': 'cached'}
            try:
                raw = await download(timeout)
                # No await after this cancellation checkpoint until publication.
                await asyncio.sleep(0)
                manifest = _publish(raw,
                                    datetime.now(timezone.utc).isoformat())
                result = {
                    'result': 'updated',
                    'revision': manifest['revision']
                }
            except asyncio.CancelledError:
                raise
            except Exception as error:
                result = {
                    'result': 'failed',
                    'error_type': type(error).__name__
                }
            atomic_write_json(
                cache_dir() / 'state.json',
                dict(result, checked_at=time.time()),
                fsync=True)
            return result
    except TimeoutError:
        return {'result': 'busy'}
    except OSError as error:
        return {'result': 'failed', 'error_type': type(error).__name__}
    finally:
        _UPDATE_LOCK.release()


async def prepare_startup() -> dict:
    """Run before registry initialization. Installed distributions stay local."""
    source = (Path(catalog.__file__).resolve().parents[2]
              / 'setup.py').is_file()
    if policy() == 'auto' and source:
        return await update()
    return {'result': 'local'}
