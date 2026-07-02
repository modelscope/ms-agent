"""JSON-backed job repository with atomic writes and mtime caching."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ms_agent.cron.types import CronJobSpec, CronJobState


class JsonJobRepository:
    """Persistent storage for cron jobs using atomic JSON writes.

    Thread-safe within a single process. Uses mtime comparison to detect
    external modifications (e.g. manual edits, other processes).
    """

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._path = workspace / 'jobs.json'
        self._lock = threading.Lock()
        self._last_mtime: float = 0.0
        self._cache: Optional[Dict[str, Any]] = None

        workspace.mkdir(parents=True, exist_ok=True)

    def _atomic_write(self, data: Dict[str, Any]) -> None:
        """Write data atomically: tmpfile -> fsync -> os.replace.
        Caller MUST hold self._lock.
        """
        content = json.dumps(data, ensure_ascii=False, indent=2)
        dir_path = str(self._path.parent)
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix='.tmp')
        try:
            os.write(fd, content.encode('utf-8'))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp_path, str(self._path))
        self._last_mtime = self._path.stat().st_mtime
        self._cache = data

    def _load_unlocked(self) -> Dict[str, Any]:
        """Load with mtime caching. Caller MUST hold self._lock."""
        if self._path.exists():
            current_mtime = self._path.stat().st_mtime
            if self._cache is None or current_mtime != self._last_mtime:
                try:
                    self._cache = json.loads(self._path.read_text('utf-8'))
                except (json.JSONDecodeError, OSError):
                    self._cache = {'version': 1, 'jobs': [], 'states': {}}
                self._last_mtime = current_mtime
        else:
            self._cache = {'version': 1, 'jobs': [], 'states': {}}
        return self._cache

    def load_all(self) -> List[CronJobSpec]:
        with self._lock:
            data = self._load_unlocked()
        jobs = []
        for j in data.get('jobs', []):
            try:
                jobs.append(CronJobSpec.from_dict(j))
            except Exception:
                continue
        return jobs

    def load_state(self, job_id: str) -> CronJobState:
        with self._lock:
            data = self._load_unlocked()
        states = data.get('states', {})
        if job_id in states:
            return CronJobState.from_dict(states[job_id])
        return CronJobState()

    def load_all_with_state(self) -> List[Tuple[CronJobSpec, CronJobState]]:
        with self._lock:
            data = self._load_unlocked()
        states = data.get('states', {})
        result = []
        for j in data.get('jobs', []):
            try:
                spec = CronJobSpec.from_dict(j)
                state = CronJobState.from_dict(states[spec.id]) if spec.id in states else CronJobState()
                result.append((spec, state))
            except Exception:
                continue
        return result

    def save_job(self, job: CronJobSpec) -> None:
        with self._lock:
            data = self._load_unlocked()
            jobs = data.get('jobs', [])
            found = False
            for i, j in enumerate(jobs):
                if j.get('id') == job.id:
                    jobs[i] = job.to_dict()
                    found = True
                    break
            if not found:
                jobs.append(job.to_dict())
            data['jobs'] = jobs
            self._atomic_write(data)

    def save_state(self, job_id: str, state: CronJobState) -> None:
        with self._lock:
            data = self._load_unlocked()
            states = data.setdefault('states', {})
            states[job_id] = state.to_dict()
            self._atomic_write(data)

    def save_job_and_state(self, job: CronJobSpec, state: CronJobState) -> None:
        with self._lock:
            data = self._load_unlocked()
            jobs = data.get('jobs', [])
            found = False
            for i, j in enumerate(jobs):
                if j.get('id') == job.id:
                    jobs[i] = job.to_dict()
                    found = True
                    break
            if not found:
                jobs.append(job.to_dict())
            data['jobs'] = jobs
            states = data.setdefault('states', {})
            states[job.id] = state.to_dict()
            self._atomic_write(data)

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            data = self._load_unlocked()
            jobs = data.get('jobs', [])
            original_len = len(jobs)
            data['jobs'] = [j for j in jobs if j.get('id') != job_id]
            states = data.get('states', {})
            states.pop(job_id, None)
            if len(data['jobs']) == original_len:
                return False
            self._atomic_write(data)
            return True

    def get_job(self, job_id: str) -> Optional[CronJobSpec]:
        with self._lock:
            data = self._load_unlocked()
        for j in data.get('jobs', []):
            if j.get('id') == job_id:
                return CronJobSpec.from_dict(j)
        return None

    def get_job_with_state(self, job_id: str) -> Optional[Tuple[CronJobSpec, CronJobState]]:
        with self._lock:
            data = self._load_unlocked()
        for j in data.get('jobs', []):
            if j.get('id') == job_id:
                spec = CronJobSpec.from_dict(j)
                states = data.get('states', {})
                state = CronJobState.from_dict(states[job_id]) if job_id in states else CronJobState()
                return (spec, state)
        return None

    def load_declarative_jobs(self) -> List[CronJobSpec]:
        """Load jobs from jobs.d/*.yaml (Phase 2: declarative job definitions)."""
        jobs_dir = self._workspace / 'jobs.d'
        if not jobs_dir.exists():
            return []

        loaded = []
        for yaml_file in sorted(jobs_dir.glob('*.yaml')):
            try:
                import yaml
                data = yaml.safe_load(yaml_file.read_text('utf-8'))
                if not isinstance(data, dict):
                    continue
                from ms_agent.cron.parser import parse_schedule
                schedule = parse_schedule(data.get('schedule', 'once'))
                spec = CronJobSpec(
                    id=data.get('id', yaml_file.stem),
                    name=data.get('name', yaml_file.stem),
                    schedule=schedule,
                    prompt=data.get('prompt'),
                    project=data.get('project'),
                    workflow=data.get('workflow'),
                    timeout=data.get('timeout'),
                    trust_remote_code=data.get('trust_remote_code', False),
                    session_mode=data.get('session_mode', 'isolated'),
                    source='declarative',
                )
                loaded.append(spec)
            except Exception:
                continue
        return loaded

    def import_declarative(self) -> int:
        """Import all jobs.d/*.yaml into the runtime registry. Returns count imported."""
        declarative = self.load_declarative_jobs()
        count = 0
        for spec in declarative:
            existing = self.get_job(spec.id)
            if existing is None:
                from ms_agent.cron.types import CronJobState
                from ms_agent.cron.parser import compute_next_run
                state = CronJobState(status='scheduled')
                state.next_run_at = compute_next_run(spec.schedule)
                self.save_job_and_state(spec, state)
                count += 1
        return count

    @property
    def workspace(self) -> Path:
        return self._workspace
