import asyncio
import os
import uuid
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Dict, List, Optional

from ms_agent.agent.base import Agent
from ms_agent.agent.loader import AgentLoader
from ms_agent.config.config import Config
from ms_agent.config.env import Env
from ms_agent.llm.utils import Message
from ms_agent.utils.logger import get_logger
from omegaconf import DictConfig, OmegaConf

from .errors import ConfigError, MaxSessionsError, SessionNotFoundError

logger = get_logger()


@dataclass
class ACPSessionEntry:
    """In-memory representation of a single ACP session."""

    id: str
    agent: Agent
    config: DictConfig
    config_path: str
    cwd: str
    created_at: float
    last_activity: float
    messages: List[Message] = field(default_factory=list)
    is_running: bool = False
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    def touch(self) -> None:
        self.last_activity = monotonic()

    def request_cancel(self) -> None:
        self._cancel_event.set()
        if self.agent.runtime is not None:
            self.agent.runtime.should_stop = True

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()


class ACPSessionStore:
    """Manages ACP session lifecycle with concurrency and timeout controls.

    Parameters:
        max_sessions: Upper bound on concurrent in-memory sessions.
        session_timeout: Seconds of inactivity before a session becomes
            eligible for eviction.
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
        self._sessions: Dict[str, ACPSessionEntry] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    async def create(
        self,
        config_path: str,
        cwd: str,
        trust_remote_code: bool = False,
        mcp_servers: list | None = None,
        meta: dict | None = None,
    ) -> ACPSessionEntry:
        """Create a new session backed by a freshly loaded agent."""
        if len(self._sessions) >= self.max_sessions:
            evicted_id = self._evict_lru()
            if evicted_id is None:
                raise MaxSessionsError(self.max_sessions)
            await self._cleanup_session(evicted_id)

        if not config_path or not os.path.exists(config_path):
            raise ConfigError(f'Config not found: {config_path}')

        config = Config.from_task(config_path)
        agent = AgentLoader.build(
            config_dir_or_id=config_path,
            config=config,
            trust_remote_code=trust_remote_code,
        )

        now = monotonic()
        session_id = f'ses_{uuid.uuid4().hex[:12]}'
        entry = ACPSessionEntry(
            id=session_id,
            agent=agent,
            config=config,
            config_path=config_path,
            cwd=cwd,
            created_at=now,
            last_activity=now,
        )
        self._sessions[session_id] = entry
        self._ensure_cleanup_running()
        logger.info('ACP session created: %s (config=%s)', session_id,
                    config_path)
        return entry

    def get(self, session_id: str) -> ACPSessionEntry:
        """Return a session entry or raise ``SessionNotFoundError``."""
        try:
            entry = self._sessions[session_id]
        except KeyError:
            raise SessionNotFoundError(session_id)
        entry.touch()
        return entry

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Return metadata for every active session."""
        result = []
        for sid, entry in self._sessions.items():
            result.append({
                'session_id': sid,
                'config_path': entry.config_path,
                'cwd': entry.cwd,
                'is_running': entry.is_running,
            })
        return result

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
        """Pick the least-recently-used *idle* session for eviction."""
        idle = [(sid, s) for sid, s in self._sessions.items()
                if not s.is_running]
        if not idle:
            return None
        return min(idle, key=lambda x: x[1].last_activity)[0]

    async def _cleanup_session(self, session_id: str) -> None:
        entry = self._sessions.pop(session_id, None)
        if entry is None:
            return
        try:
            if hasattr(entry.agent, 'cleanup_tools'):
                await entry.agent.cleanup_tools()
        except Exception:
            logger.warning(
                'Error cleaning up session %s', session_id, exc_info=True)
        logger.info('ACP session removed: %s', session_id)

    def _ensure_cleanup_running(self) -> None:
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def _periodic_cleanup(self) -> None:
        """Background loop that evicts timed-out sessions."""
        while True:
            await asyncio.sleep(self.cleanup_interval)
            now = monotonic()
            expired = [
                sid for sid, s in self._sessions.items()
                if (now - s.last_activity > self.session_timeout
                    and not s.is_running)
            ]
            for sid in expired:
                logger.info('Evicting timed-out session %s', sid)
                await self._cleanup_session(sid)
