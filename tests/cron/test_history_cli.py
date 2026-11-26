# Copyright (c) ModelScope Contributors. All rights reserved.
"""Run history limits through the public CLI and service."""
import sys

import pytest

from ms_agent.cli.cli import run_cmd
from ms_agent.cron.service import CronService
from ms_agent.cron.types import ExecutionResult


@pytest.fixture
def history(tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_CRON_WORKSPACE', str(tmp_path))
    service = CronService(workspace=tmp_path)
    job = service.create_job(schedule_str='every 60s', prompt='history limit')
    for error in ('older failure', 'latest failure'):
        service.manager.record_result(
            job, ExecutionResult(success=False, error=error))
    return service, job.id


def invoke_history(monkeypatch, job_id, limit):
    monkeypatch.setattr(
        sys, 'argv',
        ['ms-agent', 'cron', 'history', job_id, '--limit',
         str(limit)])
    run_cmd()


def test_zero_history_limit_does_not_show_records(history, monkeypatch,
                                                  capsys):
    service, job_id = history
    invoke_history(monkeypatch, job_id, 0)
    assert 'No history found.' in capsys.readouterr().out
    assert service.get_history(job_id, limit=0) == []
    assert len(service.get_history(job_id)) == 2


def test_negative_history_limit_is_rejected(history, monkeypatch, capsys):
    service, job_id = history
    with pytest.raises(SystemExit) as error:
        invoke_history(monkeypatch, job_id, -1)
    assert error.value.code == 2
    assert 'must be non-negative' in capsys.readouterr().err
    with pytest.raises(ValueError, match='must be non-negative'):
        service.get_history(job_id, limit=-1)


def test_positive_history_limit_keeps_latest_records(history, monkeypatch,
                                                     capsys):
    _, job_id = history
    invoke_history(monkeypatch, job_id, 1)
    output = capsys.readouterr().out
    assert 'latest failure' in output
    assert 'older failure' not in output
