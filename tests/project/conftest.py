# Copyright (c) ModelScope Contributors. All rights reserved.
"""Isolate the global ms-agent home for project tests.

SessionManager (and the runtime SessionLog) place sessions under the global
``~/.ms_agent/projects/<...>`` root (paths.py). Redirect ``MS_AGENT_HOME`` to a
per-test temp dir so tests never read or pollute the real user home.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_ms_agent_home(tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path / '_ms_home'))
    yield
