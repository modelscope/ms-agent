"""Backend selection.

``get_backend()`` returns a process-wide singleton chosen by
``settings.agent_backend``. The ms_agent backend is imported lazily so that
running in ``mock`` mode never requires the ms-agent SDK to be installed.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.settings import settings


@lru_cache(maxsize=1)
def get_backend():
    if settings.agent_backend == "ms_agent":
        from app.backends.ms_agent.backend import MsAgentBackend

        return MsAgentBackend()
    from app.backends.mock import MockBackend

    return MockBackend()
