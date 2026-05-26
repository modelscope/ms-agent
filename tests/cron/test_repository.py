"""Tests for ms_agent.cron.repository."""
import json
import tempfile
from pathlib import Path

import pytest

from ms_agent.cron.repository import JsonJobRepository
from ms_agent.cron.types import CronJobSpec, CronJobState, CronSchedule, RunRecord


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


@pytest.fixture
def repo(workspace):
    return JsonJobRepository(workspace)


class TestJsonJobRepository:
    def test_empty_repo(self, repo):
        assert repo.load_all() == []

    def test_save_and_load_job(self, repo):
        job = CronJobSpec(id='test1', name='Test Job', prompt='hello')
        repo.save_job(job)
        jobs = repo.load_all()
        assert len(jobs) == 1
        assert jobs[0].id == 'test1'
        assert jobs[0].name == 'Test Job'

    def test_save_and_load_state(self, repo):
        state = CronJobState(status='running', run_count=5)
        repo.save_state('job1', state)
        loaded = repo.load_state('job1')
        assert loaded.status == 'running'
        assert loaded.run_count == 5

    def test_save_job_and_state(self, repo):
        job = CronJobSpec(id='j1', name='Job 1')
        state = CronJobState(status='scheduled', next_run_at='2025-01-01T00:00:00')
        repo.save_job_and_state(job, state)

        pair = repo.get_job_with_state('j1')
        assert pair is not None
        loaded_job, loaded_state = pair
        assert loaded_job.id == 'j1'
        assert loaded_state.next_run_at == '2025-01-01T00:00:00'

    def test_delete_job(self, repo):
        job = CronJobSpec(id='del1', name='To Delete')
        repo.save_job(job)
        assert repo.delete_job('del1') is True
        assert repo.get_job('del1') is None

    def test_delete_nonexistent(self, repo):
        assert repo.delete_job('nonexistent') is False

    def test_update_existing_job(self, repo):
        job = CronJobSpec(id='upd1', name='Original')
        repo.save_job(job)
        job.name = 'Updated'
        repo.save_job(job)
        loaded = repo.get_job('upd1')
        assert loaded.name == 'Updated'

    def test_load_all_with_state(self, repo):
        job = CronJobSpec(id='ws1', name='WithState')
        state = CronJobState(status='paused')
        repo.save_job_and_state(job, state)
        results = repo.load_all_with_state()
        assert len(results) == 1
        assert results[0][0].id == 'ws1'
        assert results[0][1].status == 'paused'

    def test_state_for_missing_job(self, repo):
        state = repo.load_state('missing')
        assert state.status == 'scheduled'

    def test_atomic_write_creates_valid_json(self, repo, workspace):
        job = CronJobSpec(id='atomic1', name='Atomic Test')
        repo.save_job(job)
        data = json.loads((workspace / 'jobs.json').read_text('utf-8'))
        assert data['version'] == 1
        assert len(data['jobs']) == 1

    def test_mtime_cache_detects_external_edit(self, repo, workspace):
        job = CronJobSpec(id='ext1', name='External')
        repo.save_job(job)

        path = workspace / 'jobs.json'
        data = json.loads(path.read_text('utf-8'))
        data['jobs'].append({'id': 'ext2', 'name': 'Injected'})
        path.write_text(json.dumps(data), encoding='utf-8')

        jobs = repo.load_all()
        ids = {j.id for j in jobs}
        assert 'ext2' in ids

    def test_corrupted_json_recovery(self, repo, workspace):
        (workspace / 'jobs.json').write_text('not valid json')
        jobs = repo.load_all()
        assert jobs == []

    def test_multiple_jobs(self, repo):
        for i in range(5):
            repo.save_job(CronJobSpec(id=f'multi{i}', name=f'Job {i}'))
        assert len(repo.load_all()) == 5


class TestRunRecordInState:
    def test_record_run(self):
        state = CronJobState()
        record = RunRecord(run_at='2025-01-01T00:00:00', duration_ms=100, status='ok')
        state.record_run(record)
        assert state.run_count == 1
        assert state.last_status == 'ok'

    def test_max_history(self):
        state = CronJobState(MAX_HISTORY=3)
        for i in range(5):
            state.record_run(RunRecord(run_at=f'2025-01-0{i+1}T00:00:00', duration_ms=100, status='ok'))
        assert len(state.run_history) == 3
        assert state.run_count == 5

    def test_error_counting(self):
        state = CronJobState()
        state.record_run(RunRecord(run_at='t1', duration_ms=100, status='ok'))
        state.record_run(RunRecord(run_at='t2', duration_ms=100, status='error', error='fail'))
        assert state.error_count == 1
        assert state.run_count == 2
