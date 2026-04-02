# Copyright (c) ModelScope Contributors. All rights reserved.
import asyncio
import multiprocessing as mp
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ms_agent.utils.logger import get_logger

logger = get_logger()


@dataclass
class BackgroundTask:
    task_id: str
    task_type: str          # 'agent' | 'shell'
    tool_name: str          # which tool spawned this
    description: str
    status: str = 'running'  # 'running' | 'completed' | 'failed' | 'killed'
    proc: Optional[Any] = field(default=None, repr=False)  # mp.Process or asyncio.Task
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: float = field(default_factory=time.monotonic)
    ended_at: Optional[float] = None


class TaskManager:
    """
    Agent-level registry for background tasks (agent sub-tasks, shell tasks, etc.).
    Holds a notification queue that LLMAgent drains each turn to inject
    completion notices into the conversation.
    """

    def __init__(self):
        self._tasks: Dict[str, BackgroundTask] = {}
        self._lock = asyncio.Lock()
        self._notification_queue: asyncio.Queue = asyncio.Queue()

    def register(
        self,
        task_type: str,
        tool_name: str,
        description: str,
        proc: Optional[Any] = None,
        task_id: Optional[str] = None,
    ) -> str:
        task_id = task_id or uuid.uuid4().hex[:12]
        task = BackgroundTask(
            task_id=task_id,
            task_type=task_type,
            tool_name=tool_name,
            description=description,
            proc=proc,
        )
        self._tasks[task_id] = task
        logger.info(f'[TaskManager] registered {task_type} task {task_id}: {description}')
        return task_id

    async def complete(self, task_id: str, result: str) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        task.status = 'completed'
        task.result = result
        task.ended_at = time.monotonic()
        await self._notification_queue.put(self._format_notification(task))

    async def fail(self, task_id: str, error: str) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        task.status = 'failed'
        task.error = error
        task.ended_at = time.monotonic()
        await self._notification_queue.put(self._format_notification(task))

    def kill(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        if task.status != 'running':
            return
        if task.proc is not None:
            try:
                if isinstance(task.proc, mp.Process):
                    task.proc.terminate()
                elif asyncio.isfuture(task.proc) or asyncio.iscoroutine(task.proc):
                    task.proc.cancel()
            except Exception as e:
                logger.warning(f'[TaskManager] kill {task_id} failed: {e}')
        task.status = 'killed'
        task.ended_at = time.monotonic()

    def kill_all(self) -> None:
        for task_id in list(self._tasks):
            if self._tasks[task_id].status == 'running':
                self.kill(task_id)

    def drain_notifications(self) -> List[str]:
        """Drain all pending notifications synchronously. Called from run_loop."""
        notifications = []
        while not self._notification_queue.empty():
            try:
                notifications.append(self._notification_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return notifications

    def get_task(self, task_id: str) -> Optional[BackgroundTask]:
        return self._tasks.get(task_id)

    def running_tasks(self) -> List[BackgroundTask]:
        return [t for t in self._tasks.values() if t.status == 'running']

    @staticmethod
    def _format_notification(task: BackgroundTask) -> str:
        status_line = f'status: {task.status}'
        result_line = f'\nresult: {task.result}' if task.result else ''
        error_line = f'\nerror: {task.error}' if task.error else ''
        duration = ''
        if task.ended_at:
            duration = f'\nduration_s: {task.ended_at - task.started_at:.1f}'
        return (
            f'<task-notification>\n'
            f'<task-id>{task.task_id}</task-id>\n'
            f'<task-type>{task.task_type}</task-type>\n'
            f'<tool-name>{task.tool_name}</tool-name>\n'
            f'<description>{task.description}</description>\n'
            f'<{status_line}/>{result_line}{error_line}{duration}\n'
            f'</task-notification>'
        )
