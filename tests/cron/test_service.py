"""Tests for ms_agent.cron.service."""
import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ms_agent.cron.service import CronService, PidManager
from ms_agent.cron.types import CronJobSpec, ExecutionResult


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


class TestPidManager:
    def test_no_pid_file(self, workspace):
        pm = PidManager(workspace)
        assert pm.is_running() is False
        assert pm.read_pid() is None

    def test_write_and_read_pid(self, workspace):
        pm = PidManager(workspace)
        pm.write_pid()
        pid = pm.read_pid()
        assert pid == os.getpid()

    def test_is_running_current_process(self, workspace):
        pm = PidManager(workspace)
        pm.write_pid()
        assert pm.is_running() is True

    def test_stale_pid_cleaned(self, workspace):
        pm = PidManager(workspace)
        (workspace / 'cron.pid').write_text('999999999')
        assert pm.is_running() is False
        assert not (workspace / 'cron.pid').exists()

    def test_remove_pid(self, workspace):
        pm = PidManager(workspace)
        pm.write_pid()
        pm.remove_pid()
        assert pm.read_pid() is None


class TestCronServiceLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop(self, workspace):
        service = CronService(workspace=workspace)
        await service.start()
        assert service.is_running()
        assert (workspace / 'cron.pid').exists()

        await service.stop()
        assert not service.is_running()
        assert not (workspace / 'cron.pid').exists()


class TestCronServiceCRUD:
    def test_create_job(self, workspace):
        service = CronService(workspace=workspace)
        job = service.create_job(schedule_str='every 60s', prompt='test')
        assert job.id
        assert job.prompt == 'test'

    def test_list_jobs(self, workspace):
        service = CronService(workspace=workspace)
        service.create_job(schedule_str='every 60s', prompt='a')
        service.create_job(schedule_str='every 120s', prompt='b')
        jobs = service.list_jobs()
        assert len(jobs) == 2

    def test_pause_resume(self, workspace):
        service = CronService(workspace=workspace)
        job = service.create_job(schedule_str='every 60s', prompt='pr')
        assert service.pause_job(job.id)
        pair = service.get_job(job.id)
        assert pair[1].status == 'paused'
        assert service.resume_job(job.id)
        pair = service.get_job(job.id)
        assert pair[1].status == 'scheduled'

    def test_delete_job(self, workspace):
        service = CronService(workspace=workspace)
        job = service.create_job(schedule_str='every 60s', prompt='del')
        assert service.delete_job(job.id)
        assert service.get_job(job.id) is None

    def test_trigger_job(self, workspace):
        service = CronService(workspace=workspace)
        job = service.create_job(schedule_str='every 3600s', prompt='trigger')
        assert service.trigger_job(job.id)

    def test_status(self, workspace):
        service = CronService(workspace=workspace)
        service.create_job(schedule_str='every 60s', prompt='s')
        info = service.status()
        assert info['job_count'] == 1
        assert info['workspace'] == str(workspace)


class TestCronServiceHistory:
    def test_get_history_empty(self, workspace):
        service = CronService(workspace=workspace)
        job = service.create_job(schedule_str='every 60s', prompt='h')
        assert service.get_history(job.id) == []

    def test_get_output_empty(self, workspace):
        service = CronService(workspace=workspace)
        assert service.get_output('nonexistent') is None


class TestCronServiceCallbacks:
    @pytest.mark.asyncio
    async def test_on_job_start_callback(self, workspace):
        service = CronService(workspace=workspace)
        started = []
        service.on_job_start.append(AsyncMock(side_effect=lambda j: started.append(j.id)))

        job = service.create_job(schedule_str='every 60s', prompt='cb')

        with patch.object(service._executor, 'execute', new_callable=AsyncMock,
                          return_value=ExecutionResult(success=True, output='ok', duration_ms=10)):
            await service.run_job_now(job.id)

        assert job.id in started

    @pytest.mark.asyncio
    async def test_on_job_complete_callback(self, workspace):
        service = CronService(workspace=workspace)
        completed = []

        async def on_complete(j, r):
            completed.append((j.id, r.success))

        service.on_job_complete.append(on_complete)

        job = service.create_job(schedule_str='every 60s', prompt='cb')

        with patch.object(service._executor, 'execute', new_callable=AsyncMock,
                          return_value=ExecutionResult(success=True, output='ok', duration_ms=10)):
            await service.run_job_now(job.id)

        assert len(completed) == 1
        assert completed[0] == (job.id, True)


class TestCronServiceSchedulerWake:
    @pytest.mark.asyncio
    @pytest.mark.parametrize('manual', [False, True])
    async def test_recurring_completion_rearms_before_poll_deadline(
            self, workspace, monkeypatch, manual):
        from datetime import datetime, timezone
        from ms_agent.cron import parser, scheduler

        now = datetime(2099, 1, 1, tzinfo=timezone.utc)

        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz)

        monkeypatch.setattr(parser, 'datetime', FrozenDatetime)
        monkeypatch.setattr(scheduler, '_now_ms',
                            lambda: int(now.timestamp() * 1000))
        service = CronService(workspace=workspace)
        job = service.create_job(schedule_str='every 2s', prompt='test')
        state = service.manager.repo.load_state(job.id)
        state.next_run_at = '2098-12-31T23:59:59+00:00'
        state.status = 'running'
        service.manager.repo.save_state(job.id, state)
        other = service.create_job(schedule_str='every 2s', prompt='still running')
        other_state = service.manager.repo.load_state(other.id)
        other_state.status = 'running'
        other_state.next_run_at = state.next_run_at
        service.manager.repo.save_state(other.id, other_state)
        delays = []

        async def record_delay(delay):
            delays.append(delay)
            await asyncio.Event().wait()

        monkeypatch.setattr(service._scheduler, '_sleep_and_tick', record_delay)
        monkeypatch.setattr(service._executor, 'execute',
                            AsyncMock(return_value=ExecutionResult(success=True)))
        await service.start()
        try:
            await asyncio.sleep(0)
            assert delays == [60]
            if manual:
                await service.run_job_now(job.id)
            else:
                await service._execute_job(job, state)
            await asyncio.sleep(0)
            assert service.manager.repo.load_state(job.id).status == 'scheduled'
            assert delays == [60, 1]
            assert service.manager.repo.load_state(other.id).status == 'running'
        finally:
            await service.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize('manual', [False, True])
    async def test_completion_does_not_restart_stopped_scheduler(
            self, workspace, monkeypatch, manual):
        service = CronService(workspace=workspace)
        job = service.create_job(schedule_str='every 2s', prompt='test')
        monkeypatch.setattr(service._executor, 'execute',
                            AsyncMock(return_value=ExecutionResult(success=True)))
        await service.start()
        await service.stop()
        state = service.manager.repo.load_state(job.id)
        if manual:
            await service.run_job_now(job.id)
        else:
            await service._execute_job(job, state)
        assert not service._scheduler.running
        assert service._scheduler._timer_task is None
