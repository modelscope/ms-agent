from __future__ import annotations

import shutil
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING

from ms_agent.utils.file_lock import locked
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

    def __init__(self, project: Project, *, base_dir: str | Path | None = None,
                 auto_initialize: bool = True, require_project: bool = False) -> None:
        from ms_agent.project.paths import global_home
        self._project = project
        self._base = Path(base_dir).expanduser().resolve() if base_dir is not None else global_home().resolve()
        self._projects_root = self._base / 'projects'
        self._sessions_dir = self._projects_root / project.id / 'sessions'
        self._legacy_dir = Path(project.path) / '.ms-agent' / 'sessions'
        self._migration_marker = self._projects_root / project.id / '.sessions-migrated'
        self._require_project = require_project
        if auto_initialize:
            self.initialize()

    def _check_project(self) -> None:
        if self._require_project:
            from ms_agent.project.manager import ProjectManager
            if ProjectManager(str(self._base), auto_initialize=False).get(self._project.id) is None:
                raise ValueError(f'Project {self._project.id} not found')

    @locked(lambda self: self._projects_root)
    def initialize(self) -> None:
        """Prepare session storage and resume legacy copies without overwrites."""
        self._check_project()
        if not self._migration_marker.exists() and self._legacy_dir.is_dir():
            import os
            import tempfile
            for source in self._legacy_dir.rglob('*'):
                if not source.is_file():
                    continue
                target = self._sessions_dir / source.relative_to(self._legacy_dir)
                if target.exists():
                    if source.read_bytes() != target.read_bytes():
                        raise ValueError('Conflicting legacy session data; originals were preserved')
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(dir=target.parent, prefix='.migration-')
                os.close(fd)
                try:
                    shutil.copyfile(source, temporary)
                    os.replace(temporary, target)
                finally:
                    Path(temporary).unlink(missing_ok=True)
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        if not self._migration_marker.exists():
            JSONFileStore(self._migration_marker).write({'version': 1})

    @property
    def project(self) -> Project:
        return self._project

    @property
    def sessions_dir(self) -> Path:
        return self._sessions_dir

    @locked(lambda self, *args, **kwargs: self._projects_root)
    def create(self, name: str = '', model: str | None = None,
               model_provider: str | None = None) -> Session:
        self.initialize()
        session_id = uuid.uuid4().hex[:12]
        session_key = f'session_{session_id}'
        session = Session(
            id=session_id,
            project_id=self._project.id,
            name=name or f'Session {session_id[:6]}',
            model=model,
            model_provider=model_provider,
            session_key=session_key,
        )
        self._save_meta(session)
        return session

    def get(self, session_id: str) -> Session | None:
        store = self._meta_store(session_id)
        if not store.exists():
            return None
        data = store.read()
        if not data:
            return None
        if 'status' in data and isinstance(data['status'], str):
            data['status'] = SessionStatus(data['status'])
        return Session(**{k: v for k, v in data.items() if k in Session.__dataclass_fields__})

    def list(self) -> list[Session]:
        sessions: list[Session] = []
        try:
            entries = list(self._sessions_dir.iterdir())
        except FileNotFoundError:
            return sessions
        for entry in entries:
            if not entry.is_dir():
                continue
            meta = entry / self.META_FILE
            if meta.exists():
                store = JSONFileStore(meta)
                data = store.read()
                try:
                    if 'status' in data and isinstance(data['status'], str):
                        data['status'] = SessionStatus(data['status'])
                    sessions.append(Session(**{k: v for k, v in data.items()
                                              if k in Session.__dataclass_fields__}))
                except (TypeError, KeyError, ValueError):
                    pass
        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions

    def update_status(self, session_id: str, status: SessionStatus) -> Session:
        return self.update(session_id, status=status)

    @locked(lambda self, *args, **kwargs: self._projects_root)
    def update(self, session_id: str, *, preserve_updated_at: bool = False,
               **kwargs: object) -> Session:
        self._check_project()
        old = self.get(session_id)
        if old is None:
            raise ValueError(f'Session {session_id} not found')
        kwargs['updated_at'] = old.updated_at if preserve_updated_at else _now_iso()
        if 'status' in kwargs and isinstance(kwargs['status'], str):
            kwargs['status'] = SessionStatus(kwargs['status'])
        new = replace(old, **kwargs)
        self._save_meta(new)
        return new

    @locked(lambda self, *args, **kwargs: self._projects_root)
    def update_if(self, session_id: str, *, expected: dict, **kwargs) -> Session | None:
        with self.transaction_lock():
            current = self.get(session_id)
            if current is None:
                return None
            if any(getattr(current, key) != value for key, value in expected.items()):
                return current
            return self.update(session_id, **kwargs)

    def transaction_lock(self):
        from ms_agent.utils.file_lock import file_lock
        return file_lock(self._projects_root)

    @locked(lambda self, *args, **kwargs: self._projects_root)
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
                'Ensure the feat/memory_update branch (PR#912) is merged.')

    # -- internal --

    def _meta_store(self, session_id: str) -> JSONFileStore:
        return JSONFileStore(self._sessions_dir / session_id / self.META_FILE)

    def _save_meta(self, session: Session) -> None:
        session_dir = self._sessions_dir / session.id
        session_dir.mkdir(parents=True, exist_ok=True)
        store = JSONFileStore(session_dir / self.META_FILE)
        data = store.read()
        data.update(asdict(session))
        data['status'] = session.status.value
        store.write(data)
