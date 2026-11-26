# Copyright (c) ModelScope Contributors. All rights reserved.
"""Exercise Cron's saved output through service and CLI entry points."""
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ms_agent.cli.cli import run_cmd
from ms_agent.cron import executor
from ms_agent.cron.service import CronService


@pytest.mark.asyncio
async def test_same_second_runs_keep_distinct_output(tmp_path, monkeypatch,
                                                     capsys):
    monkeypatch.setenv('MS_AGENT_CRON_WORKSPACE', str(tmp_path))
    service = CronService(workspace=tmp_path)
    job = service.create_job(schedule_str='every 60s', prompt='save output')
    model = SimpleNamespace(
        run=AsyncMock(side_effect=['first answer', 'second answer']),
        cleanup_tools=AsyncMock())
    monkeypatch.setattr(service, '_build_config', lambda _: None)
    monkeypatch.setattr(service._executor, '_build_engine', lambda *_: model)
    monkeypatch.setattr(
        executor, 'time',
        SimpleNamespace(
            time=executor.time.time, strftime=lambda _: '2026-11-26_10-01-02'))

    assert (await service.run_job_now(job.id)).success
    assert (await service.run_job_now(job.id)).success
    assert len(service.get_history(job.id)) == 2

    # Read using a fresh service, with no in-memory results to fall back on.
    reopened = CronService(workspace=tmp_path)
    assert reopened.get_output(job.id, run_index=0) == 'first answer'
    assert reopened.get_output(job.id, run_index=1) == 'second answer'

    monkeypatch.setattr(sys, 'argv',
                        ['ms-agent', 'cron', 'output', job.id, '--last'])
    run_cmd()
    assert capsys.readouterr().out.strip() == 'second answer'
