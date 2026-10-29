# Copyright (c) ModelScope Contributors. All rights reserved.
"""Entry-point tests: unknown arguments are rejected for `agent` subcommands.

Regression test for the bug where `ms-agent agent upload <dir> ...` silently
dropped the positional path (parse_known_args) and uploaded the framework
default workspace (~/.ms_agent) instead.
"""
import sys

import pytest

from ms_agent.cli.agent import AgentCMD
from ms_agent.cli.cli import run_cmd
from ms_agent.cli.tui import TuiCMD
from ms_agent.cli.ui import UICMD


def test_agent_upload_positional_path_is_rejected(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, 'argv', [
            'ms-agent', 'agent', 'upload', '/tmp/leak_demo', '-f', 'ms-agent',
            '-r', 'user/test-leak'
        ])

    def _fail_execute(self):
        raise AssertionError('execute() must not run for rejected arguments')

    monkeypatch.setattr(AgentCMD, 'execute', _fail_execute)

    with pytest.raises(SystemExit) as exc_info:
        run_cmd()
    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert 'unrecognized arguments: /tmp/leak_demo' in stderr
    assert '--local-dir' in stderr


def test_agent_unknown_option_is_rejected(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, 'argv',
        ['ms-agent', 'agent', 'upload', '-f', 'ms-agent', '-r', 'user/x',
         '--dry-runn'])

    def _fail_execute(self):
        raise AssertionError('execute() must not run for rejected arguments')

    monkeypatch.setattr(AgentCMD, 'execute', _fail_execute)

    with pytest.raises(SystemExit) as exc_info:
        run_cmd()
    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert 'unrecognized arguments: --dry-runn' in stderr
    # A misspelled option must not get the positional-argument hint.
    assert '--local-dir' not in stderr
    assert 'no positional arguments' not in stderr


def test_valid_agent_command_still_dispatches(monkeypatch):
    monkeypatch.setattr(
        sys, 'argv', ['ms-agent', 'agent', 'status', '-f', 'ms-agent'])

    dispatched = {}
    monkeypatch.setattr(
        AgentCMD, 'execute', lambda self: dispatched.setdefault('ok', True))

    run_cmd()
    assert dispatched.get('ok')


def test_non_agent_command_keeps_unknown_args(monkeypatch):
    # `run` consumes ad-hoc `--key value` overrides via Config.parse_args,
    # so unknown arguments must keep passing through for non-agent commands.
    from ms_agent.cli.run import RunCMD
    monkeypatch.setattr(
        sys, 'argv',
        ['ms-agent', 'run', '--config', 'cfg', '--temperature', '0.5'])

    dispatched = {}
    monkeypatch.setattr(
        RunCMD, 'execute', lambda self: dispatched.setdefault('ok', True))

    run_cmd()
    assert dispatched.get('ok')


def test_bare_ms_agent_starts_tui(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['ms-agent'])
    dispatched = {}
    monkeypatch.setattr(
        TuiCMD, 'execute', lambda self: dispatched.setdefault('ok', True))

    run_cmd()
    assert dispatched.get('ok')


def test_bare_options_are_tui_options(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['ms-agent', '--work-dir', '/tmp/work'])
    seen = {}

    def _execute(self):
        seen['work_dir'] = self.args.work_dir

    monkeypatch.setattr(TuiCMD, 'execute', _execute)
    run_cmd()
    assert seen['work_dir'] == '/tmp/work'


def test_explicit_ui_is_not_rewritten_to_tui(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['ms-agent', 'ui'])
    dispatched = {}
    monkeypatch.setattr(
        UICMD, 'execute', lambda self: dispatched.setdefault('ui', True))
    monkeypatch.setattr(
        TuiCMD, 'execute', lambda self: dispatched.setdefault('tui', True))

    run_cmd()
    assert dispatched == {'ui': True}


def test_unknown_word_still_prints_help(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['ms-agent', 'not-a-command'])
    monkeypatch.setattr(
        TuiCMD, 'execute',
        lambda self: (_ for _ in ()).throw(
            AssertionError('tui must not start')))

    with pytest.raises(SystemExit) as exc_info:
        run_cmd()
    assert exc_info.value.code == 2
