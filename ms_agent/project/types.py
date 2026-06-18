from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


DEFAULT_PROJECT_ID = '_default'


@dataclass(frozen=True)
class Project:
    """Immutable project entity. Mutations produce new instances via replace()."""

    id: str
    name: str
    path: str
    instruction: str = ''
    memory_enabled: bool = False
    memory_backend: str | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)


class SessionStatus(str, Enum):
    IDLE = 'idle'
    RUNNING = 'running'
    WAITING_PERMISSION = 'waiting_permission'
    COMPLETED = 'completed'
    ERROR = 'error'


@dataclass(frozen=True)
class Session:
    """Immutable session metadata.

    Message storage is delegated to ms_agent.session.SessionLog. 
    The session_key field bridges SessionManager and SessionLog.
    """

    id: str
    project_id: str
    name: str = ''
    status: SessionStatus = SessionStatus.IDLE
    model: str | None = None
    session_key: str = ''
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
