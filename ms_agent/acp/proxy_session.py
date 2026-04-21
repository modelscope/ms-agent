import asyncio
import uuid
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Dict, List, Optional

from ms_agent.utils.logger import get_logger

from .errors import MaxSessionsError, SessionNotFoundError

logger = get_logger()


@dataclass
class ProxySessionEntry:
    """A proxy session maps a client-facing session ID to a backend ACP
    connection.  No LLM or agent instance is held here."""

    id: str
    backend_name: str
    backend_sid: str
    backend_conn: Any
    backend_proc: Any
    ctx_manager: Any
    cwd: str
    created_at: float
    last_activity: float
    is_running: bool = False
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    def touch(self) -> None:
        self.last_activity = monotonic()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()


class ProxySessionStore:
    """Manages proxy session lifecycle with LRU eviction and TTL cleanup.

    Parameters:
        max_sessions: Upper bound on concurrent proxy sessions.
        session_timeout: Seconds of inactivity before a session is eligible
            for eviction.
        cleanup_interval: Seconds between periodic cleanup sweeps.
    """

    def __init__(
        self,
        max_sessions: int = 8,
        session_timeout: int = 3600,
        cleanup_interval: int = 300,
    ):
        self.max_sessions = max_sessions
        self.session_timeout = session_timeout
        self.cleanup_interval = cleanup_interval
        self._sessions: Dict[str, ProxySessionEntry] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    def register(
        self,
        backend_name: str,
        backend_sid: str,
        backend_conn: Any,
        backend_proc: Any,
        ctx_manager: Any,
        cwd: str,
    ) -> ProxySessionEntry:
        """Register a newly established backend connection as a proxy session.

        Raises ``MaxSessionsError`` synchronously if the limit is reached and
        no idle session can be evicted (eviction itself is sync here because
        the async cleanup is best-effort).
        """
        if len(self._sessions) >= self.max_sessions:
            evicted_id = self._evict_lru()
            if evicted_id is None:
                raise MaxSessionsError(self.max_sessions)
            self._force_remove(evicted_id)

        now = monotonic()
        session_id = f'pxy_{uuid.uuid4().hex[:12]}'
        entry = ProxySessionEntry(
            id=session_id,
            backend_name=backend_name,
            backend_sid=backend_sid,
            backend_conn=backend_conn,
            backend_proc=backend_proc,
            ctx_manager=ctx_manager,
            cwd=cwd,
            created_at=now,
            last_activity=now,
        )
        self._sessions[session_id] = entry
        self._ensure_cleanup_running()
        logger.info(
            'Proxy session created: %s -> backend %s (sid=%s)',
            session_id,
            backend_name,
            backend_sid,
        )
        return entry

    def get(self, session_id: str) -> ProxySessionEntry:
        try:
            entry = self._sessions[session_id]
        except KeyError:
            raise SessionNotFoundError(session_id)
        entry.touch()
        return entry

    def list_sessions(self) -> List[Dict[str, Any]]:
        return [{
            'session_id': e.id,
            'backend': e.backend_name,
            'cwd': e.cwd,
            'is_running': e.is_running,
        } for e in self._sessions.values()]

    async def remove(self, session_id: str) -> None:
        await self._cleanup_session(session_id)

    async def close_all(self) -> None:
        for sid in list(self._sessions):
            await self._cleanup_session(sid)
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    def _evict_lru(self) -> Optional[str]:
        idle = [(sid, s) for sid, s in self._sessions.items()
                if not s.is_running]
        if not idle:
            return None
        return min(idle, key=lambda x: x[1].last_activity)[0]

    def _force_remove(self, session_id: str) -> None:
        """Synchronous best-effort removal (subprocess killed but not awaited)."""
        entry = self._sessions.pop(session_id, None)
        if entry is None:
            return
        try:
            if entry.ctx_manager is not None:
                asyncio.ensure_future(
                    entry.ctx_manager.__aexit__(None, None, None))
        except Exception:
            logger.warning(
                'Error force-removing proxy session %s',
                session_id,
                exc_info=True)
        logger.info('Proxy session force-removed: %s', session_id)

    async def _cleanup_session(self, session_id: str) -> None:
        entry = self._sessions.pop(session_id, None)
        if entry is None:
            return
        if entry.ctx_manager is not None:
            try:
                await entry.ctx_manager.__aexit__(None, None, None)
            except Exception:
                logger.warning(
                    'Error cleaning up proxy session %s',
                    session_id,
                    exc_info=True)
        logger.info('Proxy session removed: %s', session_id)

    def _ensure_cleanup_running(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = loop.create_task(self._periodic_cleanup())

    async def _periodic_cleanup(self) -> None:
        while True:
            await asyncio.sleep(self.cleanup_interval)
            now = monotonic()
            expired = [
                sid for sid, s in self._sessions.items()
                if (now - s.last_activity > self.session_timeout
                    and not s.is_running)
            ]
            for sid in expired:
                logger.info('Evicting timed-out proxy session %s', sid)
                await self._cleanup_session(sid)
