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
