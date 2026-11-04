"""Pause persistence across completion of an in-flight cron execution."""
import asyncio
from datetime import datetime
from unittest.mock import patch

import pytest

from ms_agent.cron.service import CronService
from ms_agent.cron.types import ExecutionResult, RepeatSpec


@pytest.mark.asyncio
@pytest.mark.parametrize('success', [True, False])
@pytest.mark.parametrize('schedule', ['every 60s', '* * * * *'])
async def test_pause_inflight_survives_completion_until_resume(tmp_path, success, schedule):
    service = CronService(tmp_path)
    job = service.create_job(schedule_str=schedule, prompt='offline test')
    service.trigger_job(job.id)
    started, release = asyncio.Event(), asyncio.Event()
    executions = []

    async def executor(job, config):
        executions.append(job.id)
        started.set()
        await release.wait()
        return ExecutionResult(success=success, duration_ms=1,
                               error=None if success else 'offline failure')

    with patch.object(service, '_build_config', return_value={}), \
            patch.object(service._executor, 'execute', side_effect=executor):
        assert await service._scheduler.manual_tick() == 1
        await asyncio.wait_for(started.wait(), 2)
        assert service.get_job(job.id)[1].status == 'running'
        assert service.pause_job(job.id) is True
        assert service.get_job(job.id)[1].status == 'paused'
        original_next = service.get_job(job.id)[1].next_run_at
        release.set()
        await asyncio.gather(*list(service._background_tasks))
        # A new service verifies persisted state, not merely an in-memory object.
        restored = CronService(tmp_path)
        state = restored.get_job(job.id)[1]
        assert state.status == 'paused'
        assert state.run_count == 1
        assert state.error_count == (0 if success else 1)
        assert state.last_status == ('ok' if success else 'error')
        assert state.last_error == (None if success else 'offline failure')
        assert len(state.run_history) == 1
        assert state.next_run_at != original_next
        due_ms = int(datetime.fromisoformat(state.next_run_at).timestamp() * 1000) + 1
        # Only advance scheduler time; do not rewrite the stored schedule/state.
        with patch('ms_agent.cron.scheduler._now_ms', return_value=due_ms):
            assert await service._scheduler.manual_tick() == 0
            assert len(executions) == 1
            assert service.resume_job(job.id) is True
            assert await service._scheduler.manual_tick() == 1
        await asyncio.gather(*list(service._background_tasks))
        assert len(executions) == 2
        assert service.get_job(job.id)[1].run_count == 2


@pytest.mark.parametrize('success', [True, False])
@pytest.mark.parametrize('terminal', ['once', 'repeat_exhausted'])
def test_paused_terminal_job_still_completes(tmp_path, terminal, success):
    service = CronService(tmp_path)
    schedule = '2099-01-01T00:00:00' if terminal == 'once' else 'every 60s'
    job = service.create_job(schedule_str=schedule, prompt='offline test')
    if terminal == 'repeat_exhausted':
        job.repeat = RepeatSpec(times=1)
        service.manager.repo.save_job(job)
    service.manager.mark_running(job.id)
    assert service.pause_job(job.id)
    service.manager.record_result(job, ExecutionResult(success=success, duration_ms=1))
    state = service.get_job(job.id)[1]
    assert state.status == 'completed'
    assert state.next_run_at is None
    assert state.run_count == 1
    assert state.error_count == (0 if success else 1)
    if terminal == 'repeat_exhausted':
        assert service.get_job(job.id)[0].repeat.completed == 1
    assert service._scheduler._collect_due_jobs() == []


def test_paused_nonterminal_repeat_records_progress(tmp_path):
    service = CronService(tmp_path)
    job = service.create_job(schedule_str='every 60s', prompt='offline test')
    job.repeat = RepeatSpec(times=2)
    service.manager.repo.save_job(job)
    service.manager.mark_running(job.id)
    assert service.pause_job(job.id)
    service.manager.record_result(job, ExecutionResult(success=True, duration_ms=1))
    stored_job, state = service.get_job(job.id)
    assert state.status == 'paused'
    assert state.run_count == 1
    assert stored_job.repeat.completed == 1
    assert state.next_run_at is not None
