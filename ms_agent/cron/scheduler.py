"""Single-timer async scheduler with mtime hot-reload."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, List, Optional, Tuple

from ms_agent.cron.repository import JsonJobRepository
from ms_agent.cron.types import CronJobSpec, CronJobState


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso_to_ms(iso_str: str) -> Optional[int]:
    """Convert ISO 8601 string to epoch milliseconds."""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, AttributeError):
        return None


DueCallback = Callable[[List[Tuple[CronJobSpec, CronJobState]]], Awaitable[None]]


class AsyncScheduler:
    """Single asyncio timer scheduler.

    On each tick:
      1. Reload jobs from repo (mtime-based hot reload).
      2. Find due jobs (next_run_at <= now).
      3. Call on_due callback with the due list.
      4. Re-arm the timer for the next earliest due time.
    """

    def __init__(
        self,
        repo: JsonJobRepository,
        on_due: DueCallback,
        tick_interval: int = 60,
    ):
        self._repo = repo
        self._on_due = on_due
        self._tick_interval = tick_interval
        self._timer_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._arm_timer()

    def stop(self) -> None:
        self._running = False
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            self._timer_task = None

    @property
    def running(self) -> bool:
        return self._running

    def _arm_timer(self) -> None:
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        if not self._running:
            return

        next_wake_ms = self._get_earliest_due_ms()
        now = _now_ms()
        if next_wake_ms is not None:
            delay_s = max(0.1, (next_wake_ms - now) / 1000)
            delay_s = min(delay_s, self._tick_interval)
        else:
            delay_s = self._tick_interval
        self._timer_task = asyncio.ensure_future(self._sleep_and_tick(delay_s))

    def _get_earliest_due_ms(self) -> Optional[int]:
        """Find the earliest next_run_at among enabled, non-paused jobs."""
        earliest = None
        for job, state in self._repo.load_all_with_state():
            if not job.enabled or state.status == 'paused':
                continue
            ms = _iso_to_ms(state.next_run_at)
            if ms is not None and (earliest is None or ms < earliest):
                earliest = ms
        return earliest

    async def _sleep_and_tick(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            if self._running:
                await self._on_tick()
        except asyncio.CancelledError:
            pass

    async def _on_tick(self) -> None:
        jobs_and_states = self._repo.load_all_with_state()
        now = _now_ms()
        due_jobs: List[Tuple[CronJobSpec, CronJobState]] = []

        for job, state in jobs_and_states:
            if not job.enabled:
                continue
            if state.status == 'paused':
                continue
            next_ms = _iso_to_ms(state.next_run_at)
            if next_ms is not None and next_ms <= now:
                due_jobs.append((job, state))

        if due_jobs:
            await self._on_due(due_jobs)

        if self._running:
            self._arm_timer()

    async def manual_tick(self) -> int:
        """Run a single tick manually (for CLI `cron tick`). Returns count of due jobs."""
        jobs_and_states = self._repo.load_all_with_state()
        now = _now_ms()
        due_jobs: List[Tuple[CronJobSpec, CronJobState]] = []

        for job, state in jobs_and_states:
            if not job.enabled:
                continue
            if state.status == 'paused':
                continue
            next_ms = _iso_to_ms(state.next_run_at)
            if next_ms is not None and next_ms <= now:
                due_jobs.append((job, state))

        if due_jobs:
            await self._on_due(due_jobs)

        return len(due_jobs)
