# Copyright (c) ModelScope Contributors. All rights reserved.
"""Check how cron commands select a local scheduler workspace."""
import json
import sys

from ms_agent.cli.cli import run_cmd


def test_cron_workspace_overrides_env_for_create_list_and_status(
        monkeypatch, capsys, tmp_path):
    env_workspace = tmp_path / 'environment'
    other_workspace = tmp_path / 'explicit'
    monkeypatch.setenv('MS_AGENT_CRON_WORKSPACE', str(env_workspace))

    def cli(*args):
        monkeypatch.setattr(sys, 'argv', ['ms-agent', 'cron', *args])
        run_cmd()
        return capsys.readouterr().out

    cli('create', 'every 30m', 'first test prompt', '--name', 'env-job')
    cli('create', 'every 30m', 'second test prompt', '--name', 'explicit-job',
        '--workspace', str(other_workspace))

    default_jobs = json.loads(cli('list', '--json'))
    selected_jobs = json.loads(
        cli('list', '--json', '--workspace', str(other_workspace)))
    assert [job['name'] for job in default_jobs] == ['env-job']
    assert [job['name'] for job in selected_jobs] == ['explicit-job']
    assert f'Workspace: {env_workspace}' in cli('status')
    assert f'Workspace: {other_workspace}' in cli('status', '--workspace',
                                                  str(other_workspace))
    assert 'explicit-job' not in cli('list')
