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
