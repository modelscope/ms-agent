"""Heartbeat service (Phase 3 placeholder).

A heartbeat job is a special cron job that:
  1. Writes a HEARTBEAT.md status file on each tick
  2. Optionally asks the LLM whether to skip or run, based on recent context

This module provides the data structures and helpers; the actual LLM decision
logic is deferred to a future implementation.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class HeartbeatStatus:
    """Current heartbeat state written to HEARTBEAT.md."""
    timestamp: str = field(default_factory=lambda: time.strftime('%Y-%m-%dT%H:%M:%S'))
    jobs_total: int = 0
    jobs_running: int = 0
    jobs_paused: int = 0
    jobs_error: int = 0
    last_run_job: Optional[str] = None
    last_run_status: Optional[str] = None
    uptime_seconds: int = 0

    def to_markdown(self) -> str:
        lines = [
            '# Cron Heartbeat',
            '',
            f'**Timestamp**: {self.timestamp}',
            f'**Uptime**: {self.uptime_seconds}s',
            '',
            '## Job Summary',
            '',
            f'| Metric | Value |',
            f'|--------|-------|',
            f'| Total | {self.jobs_total} |',
            f'| Running | {self.jobs_running} |',
            f'| Paused | {self.jobs_paused} |',
            f'| Errors | {self.jobs_error} |',
            '',
        ]
        if self.last_run_job:
            lines.append(f'**Last Run**: {self.last_run_job} ({self.last_run_status})')
        return '\n'.join(lines)


class HeartbeatService:
    """Writes periodic heartbeat status to the cron workspace.

    Phase 3 will add LLM-based skip/run decision making:
      - Before each job tick, ask the LLM if conditions warrant running
      - Useful for "run only if interesting news" or "skip on weekends"
    """

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._heartbeat_path = workspace / 'HEARTBEAT.md'
        self._start_time = time.time()

    def write_heartbeat(self, status: HeartbeatStatus) -> None:
        status.uptime_seconds = int(time.time() - self._start_time)
        self._heartbeat_path.write_text(status.to_markdown(), encoding='utf-8')

    def read_heartbeat(self) -> Optional[str]:
        if self._heartbeat_path.exists():
            return self._heartbeat_path.read_text(encoding='utf-8')
        return None

    async def should_run(self, job_id: str, context: str = '') -> bool:
        """Phase 3: LLM-based skip/run decision.

        Placeholder — always returns True (run the job).
        Future implementation will:
          1. Gather recent context (weather, news, calendar, etc.)
          2. Ask the LLM: "Given this context, should job X run now?"
          3. Return the LLM's boolean decision
        """
        return True
