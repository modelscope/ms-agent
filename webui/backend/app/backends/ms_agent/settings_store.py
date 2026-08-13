"""Process-local guard for SDK settings.json read-modify-write sequences."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from collections.abc import Iterator

_settings_lock = threading.RLock()


@contextmanager
def settings_lock() -> Iterator[None]:
    """Serialize settings.json mutations made through SDK manager adapters.

    The SDK managers rewrite the whole settings file. FastAPI sync routes run in
    a threadpool, so two management requests can otherwise load the same old
    file and save incompatible partial updates.
    """
    with _settings_lock:
        yield
