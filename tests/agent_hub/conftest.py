# Copyright (c) Alibaba, Inc. and its affiliates.
"""Pytest configuration for agent_hub tests.

Mirrors modelscope-hub's remote-skip mechanism: integration tests marked
``@pytest.mark.remote`` hit the real ModelScope API and are skipped unless
valid credentials are supplied via the ``TOKEN`` environment variable (or
``MODELSCOPE_RUN_REMOTE_TESTS=true``). This keeps the default ``pytest`` run
fast and offline instead of hanging on network calls.

Also turns on ``TRY_EXP_FRAMEWORKS`` for the whole suite: only ms-agent and
qwenpaw are exposed by default, but the gated frameworks are still fully
implemented and maintained, so their layout/conversion regressions must keep
running here. The gate itself (off by default, on via the env var) is covered
explicitly in ``test_cli.py``.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("TRY_EXP_FRAMEWORKS", "True")


def is_remote_enabled() -> bool:
    """Return True only when remote (real API) tests should run.

    - ``MODELSCOPE_RUN_REMOTE_TESTS=false`` -> never run remote tests.
    - ``MODELSCOPE_RUN_REMOTE_TESTS`` in (true/1/yes) -> require a valid TOKEN.
    - unset -> auto-detect: run remote tests only when a valid TOKEN exists.
    """
    flag = os.environ.get("MODELSCOPE_RUN_REMOTE_TESTS", "").lower()
    if flag == "false":
        return False
    token = os.environ.get("TOKEN", "")
    valid = bool(token and token != "your_token_here")
    if flag in ("true", "1", "yes"):
        return valid
    return valid


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "remote: tests requiring remote API access")
    config.addinivalue_line(
        "markers",
        "mock_only: tests using mock API (only run when remote is disabled)")


def pytest_collection_modifyitems(config, items):
    """Skip remote tests when credentials are absent (and vice versa)."""
    if is_remote_enabled():
        skip_mock = pytest.mark.skip(
            reason="Mock-only tests skipped (remote mode active)")
        for item in items:
            if "mock_only" in item.keywords:
                item.add_marker(skip_mock)
    else:
        skip_remote = pytest.mark.skip(
            reason="Remote tests disabled (set TOKEN with valid credentials "
            "or MODELSCOPE_RUN_REMOTE_TESTS=true)")
        for item in items:
            if "remote" in item.keywords:
                item.add_marker(skip_remote)
