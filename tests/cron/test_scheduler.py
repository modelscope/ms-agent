"""Tests for ms_agent.cron.scheduler."""
import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple

import pytest

from ms_agent.cron.repository import JsonJobRepository
from ms_agent.cron.scheduler import AsyncScheduler, _iso_to_ms, _now_ms
from ms_agent.cron.types import CronJobSpec, CronJobState, CronSchedule


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


@pytest.fixture
def repo(workspace):
    return JsonJobRepository(workspace)


class TestIsoToMs:
    def test_valid_iso(self):
        ms = _iso_to_ms('2025-01-01T00:00:00+00:00')
        assert ms is not None
        assert ms > 0

    def test_none_returns_none(self):
        assert _iso_to_ms(None) is None

    def test_empty_returns_none(self):
        assert _iso_to_ms('') is None

    def test_invalid_returns_none(self):
        assert _iso_to_ms('not a date') is None


class TestAsyncScheduler:
    @pytest.mark.asyncio
    async def test_start_stop(self, repo):
        due_list = []

        async def on_due(jobs):
            due_list.extend(jobs)

        scheduler = AsyncScheduler(repo, on_due=on_due, tick_interval=1)
        await scheduler.start()
        assert scheduler.running
        scheduler.stop()
        assert not scheduler.running

    @pytest.mark.asyncio
    async def test_due_job_detected(self, repo):
        past = (datetime.now(timezone.utc) - timedelta(seconds=10)).strftime(
            '%Y-%m-%dT%H:%M:%S+00:00'
        )
        job = CronJobSpec(id='due1', name='Due Job', prompt='test')
        state = CronJobState(status='scheduled', next_run_at=past)
        repo.save_job_and_state(job, state)

        due_list: List[Tuple] = []

        async def on_due(jobs):
            due_list.extend(jobs)

        scheduler = AsyncScheduler(repo, on_due=on_due, tick_interval=60)
        count = await scheduler.manual_tick()
        assert count == 1
        assert len(due_list) == 1
        assert due_list[0][0].id == 'due1'

    @pytest.mark.asyncio
    async def test_future_job_not_due(self, repo):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime(
            '%Y-%m-%dT%H:%M:%S+00:00'
        )
        job = CronJobSpec(id='future1', name='Future Job', prompt='test')
        state = CronJobState(status='scheduled', next_run_at=future)
        repo.save_job_and_state(job, state)

        due_list = []

        async def on_due(jobs):
            due_list.extend(jobs)

        scheduler = AsyncScheduler(repo, on_due=on_due, tick_interval=60)
        count = await scheduler.manual_tick()
        assert count == 0

    @pytest.mark.asyncio
    async def test_paused_job_skipped(self, repo):
        past = (datetime.now(timezone.utc) - timedelta(seconds=10)).strftime(
            '%Y-%m-%dT%H:%M:%S+00:00'
        )
        job = CronJobSpec(id='paused1', name='Paused Job', prompt='test')
        state = CronJobState(status='paused', next_run_at=past)
        repo.save_job_and_state(job, state)

        due_list = []

        async def on_due(jobs):
            due_list.extend(jobs)

        scheduler = AsyncScheduler(repo, on_due=on_due, tick_interval=60)
        count = await scheduler.manual_tick()
        assert count == 0

    @pytest.mark.asyncio
    async def test_running_job_skipped_by_manual_tick(self, repo):
        # A running job keeps its (past) next_run_at until it finishes, so it
        # still looks "due". manual_tick must NOT re-dispatch it, otherwise the
        # same job runs twice concurrently. Regression for the manual_tick /
        # _on_tick status-filter divergence.
        past = (datetime.now(timezone.utc) - timedelta(seconds=10)).strftime(
            '%Y-%m-%dT%H:%M:%S+00:00'
        )
        job = CronJobSpec(id='run1', name='Running Job', prompt='test')
        state = CronJobState(status='running', next_run_at=past)
        repo.save_job_and_state(job, state)

        due_list = []

        async def on_due(jobs):
            due_list.extend(jobs)

        scheduler = AsyncScheduler(repo, on_due=on_due, tick_interval=60)
        count = await scheduler.manual_tick()
        assert count == 0
        assert due_list == []

    @pytest.mark.asyncio
    async def test_completed_job_skipped_by_manual_tick(self, repo):
        # Force a past next_run_at so the status filter is what skips it, not
        # the incidental next_run_at=None that completed jobs normally carry.
        past = (datetime.now(timezone.utc) - timedelta(seconds=10)).strftime(
            '%Y-%m-%dT%H:%M:%S+00:00'
        )
        job = CronJobSpec(id='done1', name='Completed Job', prompt='test')
        state = CronJobState(status='completed', next_run_at=past)
        repo.save_job_and_state(job, state)

        due_list = []

        async def on_due(jobs):
            due_list.extend(jobs)

        scheduler = AsyncScheduler(repo, on_due=on_due, tick_interval=60)
        count = await scheduler.manual_tick()
        assert count == 0
        assert due_list == []

    @pytest.mark.asyncio
    async def test_disabled_job_skipped(self, repo):
        past = (datetime.now(timezone.utc) - timedelta(seconds=10)).strftime(
            '%Y-%m-%dT%H:%M:%S+00:00'
        )
        job = CronJobSpec(id='dis1', name='Disabled', enabled=False, prompt='test')
        state = CronJobState(status='scheduled', next_run_at=past)
        repo.save_job_and_state(job, state)

        due_list = []

        async def on_due(jobs):
            due_list.extend(jobs)

        scheduler = AsyncScheduler(repo, on_due=on_due, tick_interval=60)
        count = await scheduler.manual_tick()
        assert count == 0

    @pytest.mark.parametrize('status', ['paused', 'running', 'completed'])
    def test_non_dispatchable_job_does_not_control_next_wake(self, repo, status):
        past = '2025-01-01T00:00:00+00:00'
        future = '2099-01-01T00:00:00+00:00'
        repo.save_job_and_state(
            CronJobSpec(id='inactive', prompt='test'),
            CronJobState(status=status, next_run_at=past),
        )
        scheduler = AsyncScheduler(repo, on_due=None, tick_interval=60)
        assert scheduler._get_earliest_due_ms() is None

        repo.save_job_and_state(
            CronJobSpec(id='future', prompt='test'),
            CronJobState(status='scheduled', next_run_at=future),
        )
        assert scheduler._get_earliest_due_ms() == _iso_to_ms(future)

    @pytest.mark.parametrize('status', ['scheduled', 'error'])
    def test_dispatchable_job_controls_next_wake(self, repo, status):
        past = '2025-01-01T00:00:00+00:00'
        repo.save_job_and_state(
            CronJobSpec(id='dispatchable', prompt='test'),
            CronJobState(status=status, next_run_at=past),
        )
        scheduler = AsyncScheduler(repo, on_due=None, tick_interval=60)
        assert scheduler._get_earliest_due_ms() == _iso_to_ms(past)

    @pytest.mark.asyncio
    @pytest.mark.parametrize('status', ['running', 'completed'])
    async def test_non_dispatchable_job_keeps_normal_poll_interval(
            self, repo, monkeypatch, status):
        repo.save_job_and_state(
            CronJobSpec(id='inactive', prompt='test'),
            CronJobState(status=status,
                         next_run_at='2025-01-01T00:00:00+00:00'),
        )
        scheduler = AsyncScheduler(repo, on_due=None, tick_interval=60)
        delays = []

        async def record_delay(delay):
            delays.append(delay)

        monkeypatch.setattr(scheduler, '_sleep_and_tick', record_delay)
        await scheduler.start()
        try:
            await scheduler._timer_task
        finally:
            scheduler.stop()
        assert delays == [60]

    @pytest.mark.parametrize('status', ['scheduled', 'error'])
    def test_recovered_job_is_visible_on_next_reload(self, repo, status):
        job = CronJobSpec(id='recovered', prompt='test')
        state = CronJobState(status='running',
                             next_run_at='2025-01-01T00:00:00+00:00')
        repo.save_job_and_state(job, state)
        scheduler = AsyncScheduler(repo, on_due=None)
        assert scheduler._get_earliest_due_ms() is None
        state.status = status
        repo.save_state(job.id, state)
        assert scheduler._get_earliest_due_ms() == _iso_to_ms(state.next_run_at)
        assert [j.id for j, _ in scheduler._collect_due_jobs()] == [job.id]
