import asyncio
import os
import uuid
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Dict, List, Optional

from ms_agent.agent.base import Agent
from ms_agent.agent.loader import AgentLoader
from ms_agent.config.config import Config
from ms_agent.llm.utils import Message
from ms_agent.utils.logger import get_logger
from omegaconf import DictConfig

from .errors import AgentLoadError, ConfigError, MaxTasksError

logger = get_logger()


@dataclass
class A2ATaskEntry:
    """In-memory state for a single A2A task's backing agent."""

    task_id: str
    agent: Agent
    config: DictConfig
    config_path: str
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


class A2AAgentStore:
    """Manages agent instances backing A2A tasks.

    Parameters:
        config_path: Path to the agent YAML config.
        trust_remote_code: Whether to trust remote code in config.
        max_tasks: Upper bound on concurrent agent instances.
        task_timeout: Seconds of inactivity before eviction eligibility.
    """

    def __init__(
        self,
        config_path: str,
        trust_remote_code: bool = False,
        max_tasks: int = 8,
        task_timeout: int = 3600,
        cleanup_interval: int = 300,
    ):
        self.config_path = config_path
        self.trust_remote_code = trust_remote_code
        self.max_tasks = max_tasks
        self.task_timeout = task_timeout
        self.cleanup_interval = cleanup_interval
        self._tasks: Dict[str, A2ATaskEntry] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    async def get_or_create(self, task_id: str) -> A2ATaskEntry:
        """Return an existing task entry or create a new one."""
        if task_id in self._tasks:
            entry = self._tasks[task_id]
            entry.touch()
            return entry

        if len(self._tasks) >= self.max_tasks:
            evicted_id = self._evict_lru()
            if evicted_id is None:
                raise MaxTasksError(self.max_tasks)
            await self._cleanup_entry(evicted_id)

        if not self.config_path or not os.path.exists(self.config_path):
            raise ConfigError(f'Config not found: {self.config_path}')

        try:
            config = Config.from_task(self.config_path)
            agent = AgentLoader.build(
                config_dir_or_id=self.config_path,
                config=config,
                trust_remote_code=self.trust_remote_code,
            )
        except Exception as e:
            raise AgentLoadError(str(e)) from e

        now = monotonic()
        entry = A2ATaskEntry(
            task_id=task_id,
            agent=agent,
            config=config,
            config_path=self.config_path,
            created_at=now,
            last_activity=now,
        )
        self._tasks[task_id] = entry
        self._ensure_cleanup_running()
        logger.info('A2A agent created for task: %s (config=%s)', task_id,
                    self.config_path)
        return entry

    def get(self, task_id: str) -> A2ATaskEntry | None:
        entry = self._tasks.get(task_id)
        if entry:
            entry.touch()
        return entry

    async def remove(self, task_id: str) -> None:
        await self._cleanup_entry(task_id)

    async def close_all(self) -> None:
        for tid in list(self._tasks):
            await self._cleanup_entry(tid)
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    def _evict_lru(self) -> Optional[str]:
        idle = [(tid, t) for tid, t in self._tasks.items() if not t.is_running]
        if not idle:
            return None
        return min(idle, key=lambda x: x[1].last_activity)[0]

    async def _cleanup_entry(self, task_id: str) -> None:
        entry = self._tasks.pop(task_id, None)
        if entry is None:
            return
        try:
            if hasattr(entry.agent, 'cleanup_tools'):
                await entry.agent.cleanup_tools()
        except Exception:
            logger.warning(
                'Error cleaning up A2A task %s', task_id, exc_info=True)
        logger.info('A2A agent removed for task: %s', task_id)

    def _ensure_cleanup_running(self) -> None:
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def _periodic_cleanup(self) -> None:
        while True:
            await asyncio.sleep(self.cleanup_interval)
            now = monotonic()
            expired = [
                tid for tid, t in self._tasks.items()
                if (now
                    - t.last_activity > self.task_timeout and not t.is_running)
            ]
            for tid in expired:
                logger.info('Evicting timed-out A2A task %s', tid)
                await self._cleanup_entry(tid)
