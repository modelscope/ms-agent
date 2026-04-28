# Copyright (c) ModelScope Contributors. All rights reserved.
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# Type alias for the coroutine that does the actual work.
# It receives the AsyncTask (for metadata / process attachment) and returns
# an arbitrary result dict on success.
WorkCoroutine = Callable[['AsyncTask'], Awaitable[Any]]

# Optional progress callback: given a task, return extra status fields.
ProgressCallback = Callable[['AsyncTask'], dict[str, Any]]


@dataclass
class AsyncTask:
    """Represents a single background task."""

    task_id: str
    task_type: str
    status: str = 'running'  # pending | running | completed | failed | cancelled
    created_at: str = ''
    completed_at: str = ''
    metadata: dict = field(default_factory=dict)
    result: Any = None
    error: str = ''

    # Internal handles -- not included in repr / comparison
    _asyncio_task: asyncio.Task | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _process: asyncio.subprocess.Process | None = field(
        default=None,
        repr=False,
        compare=False,
    )


class AsyncTaskManager:
    """Generic async task manager for long-running capabilities.

    Provides a reusable submit / check / get_result / cancel pattern so that
    any capability wrapper can run work in the background without reinventing
    task-tracking logic.

    All tasks are stored in a simple dict keyed by ``task_id``.  This is
    intentionally minimal -- no persistence, no inter-process sharing.

    Usage::

        from ms_agent.capabilities.async_task import get_default_manager, AsyncTask

        manager = get_default_manager()

        async def my_work(task: AsyncTask) -> dict:
            # do expensive work, reading task.metadata as needed
            return {"answer": 42}

        task = manager.submit("my_type", my_work, metadata={"key": "value"})
        info = manager.check(task.task_id)
        result = manager.get_result(task.task_id)
    """

    def __init__(self) -> None:
        self._tasks: dict[str, AsyncTask] = {}

    def submit(
        self,
        task_type: str,
        coroutine_fn: WorkCoroutine,
        metadata: dict | None = None,
    ) -> AsyncTask:
        """Create a task and start the work coroutine in the background.

        Parameters
        ----------
        task_type:
            A short label such as ``"research"`` or ``"agent_delegate"``.
        coroutine_fn:
            An ``async def fn(task: AsyncTask) -> Any`` that does the work.
            On success its return value is stored as ``task.result``.
            On failure the exception message is stored as ``task.error``.
        metadata:
            Arbitrary dict attached to the task for the coroutine to read.

        Returns
        -------
        The newly-created :class:`AsyncTask` (status will be ``"running"``).
        """
        task_id = uuid.uuid4().hex[:8]
        task = AsyncTask(
            task_id=task_id,
            task_type=task_type,
            status='running',
            created_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
            metadata=metadata or {},
        )
        self._tasks[task_id] = task

        async def _wrapper() -> None:
            try:
                result = await coroutine_fn(task)
                task.result = result
                task.status = 'completed'
            except asyncio.CancelledError:
                task.status = 'cancelled'
            except Exception as exc:
                task.status = 'failed'
                task.error = str(exc)
                logger.exception('Task %s (%s) failed', task_id, task_type)
            finally:
                task.completed_at = time.strftime('%Y-%m-%dT%H:%M:%S')

        task._asyncio_task = asyncio.create_task(_wrapper())
        return task

    def get(self, task_id: str) -> AsyncTask | None:
        """Look up a task by ID (returns ``None`` if unknown)."""
        return self._tasks.get(task_id)

    def list_all(self, task_type: str | None = None) -> list[AsyncTask]:
        """Return all tracked tasks, optionally filtered by type."""
        tasks = list(self._tasks.values())
        if task_type is not None:
            tasks = [t for t in tasks if t.task_type == task_type]
        return tasks

    def check(
        self,
        task_id: str,
        progress_fn: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """Return a status snapshot for the given task.

        If *progress_fn* is provided it will be called with the task and its
        return dict will be merged into the result.
        """
        task = self._tasks.get(task_id)
        if task is None:
            known = [t.task_id for t in self._tasks.values()]
            return {
                'error': f'Unknown task_id: {task_id}',
                'known_tasks': known
            }

        info: dict[str, Any] = {
            'task_id': task.task_id,
            'task_type': task.task_type,
            'status': task.status,
            'created_at': task.created_at,
        }
        if task.status == 'failed':
            info['error'] = task.error
        if task.status in ('completed', 'failed', 'cancelled'):
            info['completed_at'] = task.completed_at

        if progress_fn is not None:
            try:
                info.update(progress_fn(task))
            except Exception:
                logger.debug(
                    'progress_fn raised for task %s', task_id, exc_info=True)

        return info

    def get_result(self, task_id: str) -> dict[str, Any]:
        """Return the final result of a completed task."""
        task = self._tasks.get(task_id)
        if task is None:
            return {'error': f'Unknown task_id: {task_id}'}
        if task.status == 'running':
            return {
                'task_id': task_id,
                'status': 'running',
                'message': 'Task is still in progress.',
            }
        if task.status == 'failed':
            return {
                'task_id': task_id,
                'status': 'failed',
                'error': task.error
            }
        if task.status == 'cancelled':
            return {'task_id': task_id, 'status': 'cancelled'}
        return {
            'task_id': task_id,
            'status': 'completed',
            'result': task.result,
        }

    async def cancel(self, task_id: str) -> dict[str, Any]:
        """Cancel a running task (best-effort)."""
        task = self._tasks.get(task_id)
        if task is None:
            return {'error': f'Unknown task_id: {task_id}'}
        if task.status != 'running':
            return {
                'error':
                f'Task {task_id} is not running (status: {task.status})',
            }

        # Cancel the asyncio task first
        if task._asyncio_task and not task._asyncio_task.done():
            task._asyncio_task.cancel()

        # Kill subprocess if one was attached
        if task._process and task._process.returncode is None:
            try:
                task._process.kill()
            except ProcessLookupError:
                pass

        task.status = 'cancelled'
        task.completed_at = time.strftime('%Y-%m-%dT%H:%M:%S')
        return {'task_id': task_id, 'status': 'cancelled'}


_default_manager: Optional[AsyncTaskManager] = None


def get_default_manager() -> AsyncTaskManager:
    """Return the process-wide default :class:`AsyncTaskManager`."""
    global _default_manager
    if _default_manager is None:
        _default_manager = AsyncTaskManager()
    return _default_manager
