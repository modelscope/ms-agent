"""Backend access.

``get_backend()`` returns a process-wide singleton for the ms-agent SDK backend.
It used to pick between that and an in-memory ``mock`` backend (frontend-only
development without the SDK); the mock backend and its seed data have been
removed, so ms_agent is the only implementation.
"""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def get_backend():
    from app.backends.ms_agent.backend import MsAgentBackend

    return MsAgentBackend()
