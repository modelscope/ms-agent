"""Tests for ms_agent.cron.manager."""
import pytest
from pathlib import Path

from ms_agent.cron.manager import JobManager
from ms_agent.cron.types import CronJobSpec, CronSchedule, ExecutionResult, RepeatSpec


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


@pytest.fixture
def manager(workspace):
    return JobManager(workspace)


class TestJobManagerCRUD:
    def test_create_job(self, manager):
        job = manager.create_job(schedule_str='every 60s', prompt='hello', name='Test')
        assert job.id
        assert job.name == 'Test'
        assert job.prompt == 'hello'
        assert job.schedule.kind == 'interval'

    def test_create_cron_job(self, manager):
        job = manager.create_job(schedule_str='0 9 * * *', prompt='morning check')
        assert job.schedule.kind == 'cron'
        assert job.schedule.expr == '0 9 * * *'

    def test_list_jobs(self, manager):
        manager.create_job(schedule_str='every 60s', prompt='job1')
        manager.create_job(schedule_str='every 120s', prompt='job2')
        jobs = manager.list_jobs()
        assert len(jobs) == 2

    def test_get_job(self, manager):
        job = manager.create_job(schedule_str='every 60s', prompt='find me')
        pair = manager.get_job(job.id)
        assert pair is not None
        assert pair[0].prompt == 'find me'

    def test_get_missing_job(self, manager):
        assert manager.get_job('nonexistent') is None

    def test_delete_job(self, manager):
        job = manager.create_job(schedule_str='every 60s', prompt='delete me')
        assert manager.delete_job(job.id) is True
        assert manager.get_job(job.id) is None

    def test_delete_nonexistent(self, manager):
        assert manager.delete_job('nope') is False


class TestJobManagerState:
    def test_pause_and_resume(self, manager):
        job = manager.create_job(schedule_str='every 60s', prompt='pausable')
        assert manager.pause_job(job.id) is True
        pair = manager.get_job(job.id)
        assert pair[1].status == 'paused'

        assert manager.resume_job(job.id) is True
        pair = manager.get_job(job.id)
        assert pair[1].status == 'scheduled'

    def test_pause_already_paused(self, manager):
        job = manager.create_job(schedule_str='every 60s', prompt='x')
        manager.pause_job(job.id)
        assert manager.pause_job(job.id) is False

    def test_resume_not_paused(self, manager):
        job = manager.create_job(schedule_str='every 60s', prompt='x')
        assert manager.resume_job(job.id) is False

    def test_trigger_job(self, manager):
        job = manager.create_job(schedule_str='every 3600s', prompt='trigger me')
        assert manager.trigger_job(job.id) is True
        pair = manager.get_job(job.id)
        assert pair[1].next_run_at is not None

    def test_mark_running(self, manager):
        job = manager.create_job(schedule_str='every 60s', prompt='run')
        manager.mark_running(job.id)
        pair = manager.get_job(job.id)
        assert pair[1].status == 'running'


class TestJobManagerRecordResult:
    def test_record_success(self, manager):
        job = manager.create_job(schedule_str='every 60s', prompt='ok')
        result = ExecutionResult(success=True, output='done', duration_ms=500)
        manager.record_result(job, result)
        pair = manager.get_job(job.id)
        state = pair[1]
        assert state.run_count == 1
        assert state.last_status == 'ok'

    def test_record_error(self, manager):
        job = manager.create_job(schedule_str='every 60s', prompt='fail')
        result = ExecutionResult(success=False, error='boom', duration_ms=100)
        manager.record_result(job, result)
        pair = manager.get_job(job.id)
        state = pair[1]
        assert state.error_count == 1
        assert state.last_error == 'boom'

    def test_once_job_completes_after_run(self, manager):
        job = manager.create_job(schedule_str='2099-01-01T00:00:00', prompt='once')
        result = ExecutionResult(success=True, output='done', duration_ms=100)
        manager.record_result(job, result)
        pair = manager.get_job(job.id)
        assert pair[1].status == 'completed'
        assert pair[1].next_run_at is None

    def test_repeat_exhaustion(self, manager):
        job = manager.create_job(schedule_str='every 60s', prompt='repeat')
        job.repeat = RepeatSpec(times=1, completed=0)
        manager.repo.save_job(job)

        result = ExecutionResult(success=True, output='done', duration_ms=100)
        manager.record_result(job, result)
        pair = manager.get_job(job.id)
        assert pair[1].status == 'completed'

    def test_interval_advances_after_run(self, manager):
        job = manager.create_job(schedule_str='every 60s', prompt='advance')
        pair_before = manager.get_job(job.id)
        old_next = pair_before[1].next_run_at

        result = ExecutionResult(success=True, output='done', duration_ms=100)
        manager.record_result(job, result)
        pair_after = manager.get_job(job.id)
        assert pair_after[1].next_run_at != old_next


class TestJobManagerHistory:
    def test_get_history(self, manager):
        job = manager.create_job(schedule_str='every 60s', prompt='hist')
        for i in range(3):
            result = ExecutionResult(success=True, output=f'run{i}', duration_ms=100)
            manager.record_result(job, result)
        history = manager.get_history(job.id)
        assert len(history) == 3

    def test_get_history_limit(self, manager):
        job = manager.create_job(schedule_str='every 60s', prompt='limit')
        for i in range(5):
            result = ExecutionResult(success=True, duration_ms=100)
            manager.record_result(job, result)
        history = manager.get_history(job.id, limit=3)
        assert len(history) == 3

    def test_get_history_missing_job(self, manager):
        assert manager.get_history('missing') == []
