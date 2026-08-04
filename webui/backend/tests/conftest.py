"""Isolate the SDK home so tests never touch the real ~/.ms_agent."""
import os
import tempfile

os.environ["MS_AGENT_HOME"] = tempfile.mkdtemp(prefix="ms_agent_test_home_")
os.environ.setdefault("AGENT_BACKEND", "ms_agent")
os.environ.setdefault("LOG_LEVEL", "ERROR")

import pytest

from app.backends.ms_agent import titler


@pytest.fixture(autouse=True)
def _stub_titler(monkeypatch):
    """Keep the offline suite network-free: never let chat.stream fire the real
    title/category LLM call. Tests that want a title override this per-test."""

    async def _none(_text: str):
        return None

    monkeypatch.setattr(titler, "generate_title_and_category", _none)
