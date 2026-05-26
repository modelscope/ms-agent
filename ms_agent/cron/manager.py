"""Job manager: CRUD operations, state machine, and scheduling logic."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ms_agent.cron.parser import advance_next_run, compute_next_run, parse_schedule
from ms_agent.cron.repository import JsonJobRepository
from ms_agent.cron.types import (
    CronJobSpec,
    CronJobState,
    CronSchedule,
    ExecutionResult,
    RunRecord,
)


class JobManager:
    """Manages cron job lifecycle: CRUD, state transitions, and schedule advancement."""

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._repo = JsonJobRepository(workspace)

    @property
    def repo(self) -> JsonJobRepository:
        return self._repo

    def create_job(
        self,
        schedule_str: str,
        prompt: Optional[str] = None,
        name: str = '',
        project: Optional[str] = None,
        workflow: Optional[str] = None,
        timeout: Optional[int] = None,
        overrides: Optional[Dict[str, Any]] = None,
        trust_remote_code: bool = False,
        session_mode: str = 'isolated',
    ) -> CronJobSpec:
        """Create a new job from a schedule string and prompt."""
        schedule = parse_schedule(schedule_str)
        job = CronJobSpec(
            name=name or (prompt[:30] + '...' if prompt and len(prompt) > 30 else (prompt or '')),
            schedule=schedule,
            prompt=prompt,
            project=project,
            workflow=workflow,
            timeout=timeout,
            overrides=overrides,
            trust_remote_code=trust_remote_code,
            session_mode=session_mode,
        )

        state = CronJobState(status='scheduled')
        next_run = compute_next_run(schedule)
        state.next_run_at = next_run

        self._repo.save_job_and_state(job, state)
        return job

    def create_job_from_spec(self, job: CronJobSpec) -> CronJobSpec:
        """Register a pre-built CronJobSpec."""
        state = CronJobState(status='scheduled')
        state.next_run_at = compute_next_run(job.schedule)
        self._repo.save_job_and_state(job, state)
        return job

    def list_jobs(self, include_disabled: bool = False) -> List[Tuple[CronJobSpec, CronJobState]]:
        result = self._repo.load_all_with_state()
        if not include_disabled:
            result = [(j, s) for j, s in result if j.enabled]
        return result

    def get_job(self, job_id: str) -> Optional[Tuple[CronJobSpec, CronJobState]]:
        return self._repo.get_job_with_state(job_id)

    def delete_job(self, job_id: str) -> bool:
        return self._repo.delete_job(job_id)

    def pause_job(self, job_id: str) -> bool:
        pair = self._repo.get_job_with_state(job_id)
        if pair is None:
            return False
        job, state = pair
        if state.status in ('paused', 'completed'):
            return False
        state.status = 'paused'
        self._repo.save_state(job_id, state)
        return True

    def resume_job(self, job_id: str) -> bool:
        pair = self._repo.get_job_with_state(job_id)
        if pair is None:
            return False
        job, state = pair
        if state.status != 'paused':
            return False
        state.status = 'scheduled'
        if not state.next_run_at:
            state.next_run_at = compute_next_run(job.schedule)
        self._repo.save_state(job_id, state)
        return True

    def trigger_job(self, job_id: str) -> bool:
        """Set next_run_at to now so the job runs on the next tick."""
        pair = self._repo.get_job_with_state(job_id)
        if pair is None:
            return False
        job, state = pair
        state.status = 'scheduled'
        state.next_run_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        self._repo.save_state(job_id, state)
        return True

    def mark_running(self, job_id: str) -> None:
        pair = self._repo.get_job_with_state(job_id)
        if pair is None:
            return
        _, state = pair
        state.status = 'running'
        self._repo.save_state(job_id, state)

    def record_result(self, job: CronJobSpec, result: ExecutionResult) -> None:
        """Record execution result and advance the schedule."""
        pair = self._repo.get_job_with_state(job.id)
        if pair is None:
            return
        _, state = pair

        record = RunRecord(
            run_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
            duration_ms=result.duration_ms,
            status='ok' if result.success else 'error',
            error=result.error,
        )
        state.record_run(record)

        if job.repeat:
            job.repeat.completed += 1
            if job.repeat.is_exhausted():
                state.status = 'completed'
                state.next_run_at = None
                self._repo.save_job_and_state(job, state)
                return

        if job.schedule.kind == 'once':
            state.status = 'completed'
            state.next_run_at = None
        else:
            next_run = advance_next_run(job.schedule, state.next_run_at or '')
            state.next_run_at = next_run
            state.status = 'scheduled' if next_run else 'completed'

        self._repo.save_job_and_state(job, state)

    def get_history(self, job_id: str, limit: int = 10) -> List[RunRecord]:
        pair = self._repo.get_job_with_state(job_id)
        if pair is None:
            return []
        _, state = pair
        return state.run_history[-limit:]

    def get_output(self, job_id: str, run_index: int = -1) -> Optional[str]:
        """Read an output file for a given job."""
        output_dir = self._workspace / 'output' / job_id
        if not output_dir.exists():
            return None
        files = sorted(output_dir.glob('*.md'))
        if not files:
            return None
        try:
            target = files[run_index]
        except IndexError:
            return None
        return target.read_text(encoding='utf-8')
