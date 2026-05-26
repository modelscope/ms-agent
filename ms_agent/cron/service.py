"""CronService: top-level orchestrator with PID management and lifecycle."""
from __future__ import annotations

import asyncio
import os
import signal
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

from ms_agent.cron.executor import JobExecutor
from ms_agent.cron.manager import JobManager
from ms_agent.cron.parser import compute_next_run
from ms_agent.cron.repository import JsonJobRepository
from ms_agent.cron.scheduler import AsyncScheduler
from ms_agent.cron.notify import build_hooks_from_spec
from ms_agent.cron.types import CronJobSpec, CronJobState, ExecutionResult, RunRecord

DEFAULT_WORKSPACE = os.path.expanduser('~/.ms_agent/cron')
DEFAULT_TICK_INTERVAL = 60
DEFAULT_TIMEOUT = 300
DEFAULT_MAX_CONCURRENT = 5


class PidManager:
    """Manage cron daemon PID file."""

    def __init__(self, workspace: Path):
        self._pid_path = workspace / 'cron.pid'

    def is_running(self) -> bool:
        if not self._pid_path.exists():
            return False
        try:
            pid = int(self._pid_path.read_text().strip())
            os.kill(pid, 0)
            return True
        except (ValueError, ProcessLookupError, PermissionError):
            self._pid_path.unlink(missing_ok=True)
            return False

    def write_pid(self) -> None:
        self._pid_path.parent.mkdir(parents=True, exist_ok=True)
        self._pid_path.write_text(str(os.getpid()))

    def read_pid(self) -> Optional[int]:
        if self._pid_path.exists():
            try:
                return int(self._pid_path.read_text().strip())
            except ValueError:
                return None
        return None

    def remove_pid(self) -> None:
        self._pid_path.unlink(missing_ok=True)

    def stop_daemon(self) -> bool:
        pid = self.read_pid()
        if pid is None:
            return False
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except ProcessLookupError:
            self.remove_pid()
            return False


class CronService:
    """Cron task service — pure asyncio, no web framework dependency.

    Host modes:
      1. ms-agent cron start [--foreground] — standalone daemon
      2. ms-agent cron tick — manual single tick
      3. Any asyncio app via start()/stop() embedding
    """

    def __init__(self, workspace: Union[str, Path, None] = None):
        from ms_agent.config.env import Env
        Env.load_dotenv_into_environ()

        ws_path = Path(
            workspace or os.environ.get('MS_AGENT_CRON_WORKSPACE', DEFAULT_WORKSPACE)
        )
        ws_path.mkdir(parents=True, exist_ok=True)

        self._workspace = ws_path
        self._manager = JobManager(ws_path)
        self._pid_manager = PidManager(ws_path)

        (ws_path / 'output').mkdir(exist_ok=True)
        (ws_path / 'sessions').mkdir(exist_ok=True)

        self._executor = JobExecutor(
            default_timeout=DEFAULT_TIMEOUT,
            semaphore=asyncio.Semaphore(DEFAULT_MAX_CONCURRENT),
            output_dir=ws_path / 'output',
            session_dir=ws_path / 'sessions',
        )
        self._scheduler = AsyncScheduler(
            repo=self._manager.repo,
            on_due=self._on_due_jobs,
            tick_interval=DEFAULT_TICK_INTERVAL,
        )
        self._running = False
        self._background_tasks: set[asyncio.Task] = set()

        self.on_job_complete: List[Callable[[CronJobSpec, ExecutionResult], Awaitable[None]]] = []
        self.on_job_start: List[Callable[[CronJobSpec], Awaitable[None]]] = []

    @property
    def workspace(self) -> Path:
        return self._workspace

    @property
    def manager(self) -> JobManager:
        return self._manager

    # === Lifecycle ===

    async def start(self) -> None:
        self._running = True
        self._manager.repo.import_declarative()
        self._pid_manager.write_pid()
        await self._scheduler.start()

    async def stop(self, force: bool = False, timeout: float = 30) -> None:
        """Stop the cron service.

        Args:
            force: If True, cancel all in-flight jobs immediately.
                   If False, wait up to `timeout` seconds for them to finish,
                   then cancel any that remain.
            timeout: Seconds to wait for graceful drain (ignored if force=True).
        """
        self._running = False
        self._scheduler.stop()

        if self._background_tasks:
            if force:
                for t in self._background_tasks:
                    t.cancel()
            done, pending = await asyncio.wait(
                self._background_tasks,
                timeout=0 if force else timeout,
            )
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        self._pid_manager.remove_pid()

    def is_running(self) -> bool:
        return self._running

    async def run_forever(self) -> None:
        """Run the scheduler loop until interrupted.

        SIGTERM → graceful stop (wait up to 30s for in-flight jobs).
        SIGINT  → force stop (cancel all immediately).
        """
        await self.start()
        stop_event = asyncio.Event()
        self._force_stop = False

        def _graceful():
            stop_event.set()

        def _force():
            self._force_stop = True
            stop_event.set()

        loop = asyncio.get_event_loop()
        try:
            loop.add_signal_handler(signal.SIGTERM, _graceful)
        except (NotImplementedError, RuntimeError):
            pass
        try:
            loop.add_signal_handler(signal.SIGINT, _force)
        except (NotImplementedError, RuntimeError):
            pass

        await stop_event.wait()
        await self.stop(force=self._force_stop)

    # === Job CRUD (delegates to manager) ===

    def create_job(self, **kwargs: Any) -> CronJobSpec:
        return self._manager.create_job(**kwargs)

    def create_job_from_spec(self, spec: CronJobSpec) -> CronJobSpec:
        return self._manager.create_job_from_spec(spec)

    def update_job(self, job_id: str, updates: Dict[str, Any]) -> Optional[CronJobSpec]:
        pair = self._manager.get_job(job_id)
        if pair is None:
            return None
        job, state = pair
        for k, v in updates.items():
            if hasattr(job, k):
                setattr(job, k, v)
        self._manager.repo.save_job(job)
        return job

    def delete_job(self, job_id: str) -> bool:
        return self._manager.delete_job(job_id)

    def pause_job(self, job_id: str) -> bool:
        return self._manager.pause_job(job_id)

    def resume_job(self, job_id: str) -> bool:
        return self._manager.resume_job(job_id)

    def trigger_job(self, job_id: str) -> bool:
        return self._manager.trigger_job(job_id)

    def list_jobs(self, include_disabled: bool = False) -> List[Tuple[CronJobSpec, CronJobState]]:
        return self._manager.list_jobs(include_disabled=include_disabled)

    def get_job(self, job_id: str) -> Optional[Tuple[CronJobSpec, CronJobState]]:
        return self._manager.get_job(job_id)

    # === Output ===

    def get_history(self, job_id: str, limit: int = 10) -> List[RunRecord]:
        return self._manager.get_history(job_id, limit=limit)

    def get_output(self, job_id: str, run_index: int = -1) -> Optional[str]:
        return self._manager.get_output(job_id, run_index=run_index)

    # === Status ===

    def status(self) -> Dict[str, Any]:
        jobs = self._manager.list_jobs(include_disabled=True)
        return {
            'running': self._running,
            'job_count': len(jobs),
            'pid': self._pid_manager.read_pid(),
            'workspace': str(self._workspace),
        }

    def daemon_is_running(self) -> bool:
        return self._pid_manager.is_running()

    def stop_daemon(self) -> bool:
        return self._pid_manager.stop_daemon()

    # === Scheduler Callbacks ===

    async def _on_due_jobs(self, due: List[Tuple[CronJobSpec, CronJobState]]) -> None:
        """Called by scheduler when jobs are due.

        Fire-and-forget: spawn tasks but do NOT await them, so the scheduler
        tick loop can re-arm immediately and pick up newly due jobs.
        """
        for job, state in due:
            task = asyncio.create_task(
                self._execute_job(job, state),
                name=f'cron-{job.id}',
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _execute_job(self, job: CronJobSpec, state: CronJobState) -> None:
        self._manager.mark_running(job.id)

        for cb in self.on_job_start:
            try:
                await cb(job)
            except Exception:
                pass

        config = self._build_config(job)
        result = await self._executor.execute(job, config)

        retries_left = job.max_retries
        while not result.success and retries_left > 0:
            retries_left -= 1
            config = self._build_config(job)
            result = await self._executor.execute(job, config)

        self._manager.record_result(job, result)

        for cb in self.on_job_complete:
            try:
                await cb(job, result)
            except Exception:
                pass

        # Phase 2: per-job notify hooks
        notify_hooks = build_hooks_from_spec(job.notify)
        should_notify = (not result.success and (job.notify is None or job.notify.on_error)) or \
                        (result.success and job.notify is not None and job.notify.on_success)
        if should_notify:
            for hook in notify_hooks:
                try:
                    await hook.notify(job, result)
                except Exception:
                    pass

    def _build_config(self, job: CronJobSpec) -> Any:
        """Build DictConfig for agent execution.

        Config inheritance chain (later overrides earlier):
          1. Project config (from job.project via Config.from_task)
          2. Job-level overrides (from job.overrides dict)
          3. Cron-mandatory overrides (stream=False, no interactive callbacks)

        The project's max_chat_round is respected; a default of 50 is used
        only when no project config sets it.
        """
        from omegaconf import OmegaConf

        if job.project:
            from ms_agent.config import Config
            try:
                config = Config.from_task(job.project)
            except Exception:
                config = OmegaConf.create({})
        else:
            config = OmegaConf.create({})

        if job.overrides:
            config = OmegaConf.merge(config, OmegaConf.create(job.overrides))

        OmegaConf.update(config, 'generation_config.stream', False, merge=True)

        existing_cbs = getattr(config, 'callbacks', None)
        if existing_cbs:
            safe_cbs = [
                cb for cb in existing_cbs
                if cb != 'input_callback' and not str(cb).endswith('input_callback')
            ]
            OmegaConf.update(config, 'callbacks', safe_cbs, merge=False)
        else:
            OmegaConf.update(config, 'callbacks', [], merge=False)

        if getattr(config, 'max_chat_round', None) is None:
            OmegaConf.update(config, 'max_chat_round', 50, merge=True)

        OmegaConf.update(
            config, 'session_log.dir',
            str(self._workspace / 'sessions'), merge=True
        )
        OmegaConf.update(
            config, 'output_dir',
            str(self._workspace / 'output' / job.id), merge=True
        )

        if job.session_mode == 'persistent':
            OmegaConf.update(config, 'load_cache', True, merge=True)
            OmegaConf.update(config, 'save_history', True, merge=True)
            OmegaConf.update(config, 'tag', f'cron-{job.id}', merge=True)

        return config

    # === Manual Tick ===

    async def manual_tick(self) -> int:
        """Run a single tick (for CLI `cron tick`). Returns count of due jobs."""
        return await self._scheduler.manual_tick()

    async def run_job_now(self, job_id: str) -> Optional[ExecutionResult]:
        """Execute a job immediately (synchronous, for CLI `cron run`)."""
        pair = self._manager.get_job(job_id)
        if pair is None:
            return None
        job, state = pair
        self._manager.mark_running(job_id)

        for cb in self.on_job_start:
            try:
                await cb(job)
            except Exception:
                pass

        config = self._build_config(job)
        result = await self._executor.execute(job, config)

        retries_left = job.max_retries
        while not result.success and retries_left > 0:
            retries_left -= 1
            config = self._build_config(job)
            result = await self._executor.execute(job, config)

        self._manager.record_result(job, result)

        for cb in self.on_job_complete:
            try:
                await cb(job, result)
            except Exception:
                pass

        return result
