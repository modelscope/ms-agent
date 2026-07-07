# Copyright (c) ModelScope Contributors. All rights reserved.
"""_resolve_log_file must never crash logging setup (and thus the app) on a
filesystem error when opt-in file logging is enabled."""
from unittest.mock import MagicMock, patch

from ms_agent.utils.logger import _resolve_log_file


def test_default_console_only(monkeypatch):
    monkeypatch.delenv('MS_AGENT_LOG_FILE', raising=False)
    monkeypatch.delenv('LOG_FILE', raising=False)
    assert _resolve_log_file(None) is None


def test_explicit_arg_wins():
    assert _resolve_log_file('/tmp/custom.log') == '/tmp/custom.log'


def test_mkdir_failure_falls_back_to_console(monkeypatch):
    monkeypatch.setenv('MS_AGENT_LOG_FILE', 'true')
    fake_dir = MagicMock()
    fake_dir.mkdir.side_effect = OSError('read-only filesystem')
    with patch(
            'ms_agent.project.paths.global_logs_dir', return_value=fake_dir):
        # Must not raise; degrades to console-only (None).
        assert _resolve_log_file(None) is None
