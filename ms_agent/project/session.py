from __future__ import annotations

import shutil
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING

from ms_agent.project.store import JSONFileStore
from ms_agent.project.types import Project, Session, SessionStatus, _now_iso

if TYPE_CHECKING:
    from ms_agent.session.session_log import SessionLog


class SessionManager:
    """Session lifecycle management, bound to a Project.

    Responsibility split:
    - SessionManager: CRUD + metadata (create/list/status/delete)
    - SessionLog (feat/memory_update): message persistence + context assembly
    - Linked via session_key
    """

    META_FILE = 'session.json'

    def __init__(self, project: Project) -> None:
        self._project = project
        self._sessions_dir = (
            Path(project.path) / '.ms-agent' / 'sessions'
        )
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    @property
    def project(self) -> Project:
        return self._project

    @property
    def sessions_dir(self) -> Path:
        return self._sessions_dir

    def create(self, name: str = '', model: str | None = None) -> Session:
        session_id = uuid.uuid4().hex[:12]
        session_key = f'session_{session_id}'
        session = Session(
            id=session_id,
            project_id=self._project.id,
            name=name or f'Session {session_id[:6]}',
            model=model,
            session_key=session_key,
        )
        self._save_meta(session)
        return session

    def get(self, session_id: str) -> Session | None:
        store = self._meta_store(session_id)
        if not store.exists():
            return None
        data = store.read()
        if 'status' in data and isinstance(data['status'], str):
            data['status'] = SessionStatus(data['status'])
        return Session(**data)

    def list(self) -> list[Session]:
        sessions: list[Session] = []
        if not self._sessions_dir.exists():
            return sessions
        for entry in self._sessions_dir.iterdir():
            if not entry.is_dir():
                continue
            meta = entry / self.META_FILE
            if meta.exists():
                store = JSONFileStore(meta)
                try:
                    data = store.read()
                    if 'status' in data and isinstance(data['status'], str):
                        data['status'] = SessionStatus(data['status'])
                    sessions.append(Session(**data))
                except (TypeError, KeyError, ValueError):
                    pass
        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions

    def update_status(self, session_id: str, status: SessionStatus) -> Session:
        return self.update(session_id, status=status)

    def update(self, session_id: str, **kwargs: object) -> Session:
        old = self.get(session_id)
        if old is None:
            raise ValueError(f'Session {session_id} not found')
        kwargs['updated_at'] = _now_iso()
        if 'status' in kwargs and isinstance(kwargs['status'], str):
            kwargs['status'] = SessionStatus(kwargs['status'])
        new = replace(old, **kwargs)
        self._save_meta(new)
        return new

    def delete(self, session_id: str) -> None:
        session_dir = self._sessions_dir / session_id
        if session_dir.exists():
            shutil.rmtree(session_dir)

    def get_session_log(self, session: Session) -> 'SessionLog':
        """Get a SessionLog instance for message read/write.

        Delegates to ms_agent.session.SessionLog from feat/memory_update.
        Falls back to a lightweight stub if that module is not available.
        """
        try:
            from ms_agent.session.session_log import SessionLog
            return SessionLog(
                session_dir=str(self._sessions_dir / session.id),
                session_key=session.session_key,
            )
        except ImportError:
            raise ImportError(
                'ms_agent.session.SessionLog is not available. '
                'Ensure the feat/memory_update branch (PR#912) is merged.'
            )

    # -- internal --

    def _meta_store(self, session_id: str) -> JSONFileStore:
        return JSONFileStore(self._sessions_dir / session_id / self.META_FILE)

    def _save_meta(self, session: Session) -> None:
        session_dir = self._sessions_dir / session.id
        session_dir.mkdir(parents=True, exist_ok=True)
        store = JSONFileStore(session_dir / self.META_FILE)
        data = asdict(session)
        data['status'] = session.status.value
        store.write(data)
