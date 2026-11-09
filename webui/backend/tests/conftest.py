"""Isolate the SDK home so tests never touch the real ~/.ms_agent."""
import os
import tempfile
from pathlib import Path

os.environ["MS_AGENT_HOME"] = tempfile.mkdtemp(prefix="ms_agent_test_home_")
os.environ.setdefault("LOG_LEVEL", "ERROR")
os.environ["MS_AGENT_MODEL_CATALOG"] = "local"

import pytest

from app.backends.ms_agent import titler


@pytest.fixture(scope="session", autouse=True)
def _stop_skill_watchers():
    """Tests call adapters without an ASGI lifespan; close their shared state."""
    yield
    from app.backends.ms_agent.skill_index import skill_index

    skill_index.stop()


@pytest.fixture(autouse=True)
def _stub_titler(monkeypatch):
    """Keep the offline suite network-free: never let chat.stream fire the real
    title/category LLM call. Tests that want a title override this per-test."""

    async def _none(_text: str):
        return None

    monkeypatch.setattr(titler, "generate_title_and_category", _none)

    # The developer machine may contain a large real ~/.agents/skills tree.
    # Offline tests must exercise only fixtures they create explicitly.
    empty_standard = Path(os.environ["MS_AGENT_HOME"]) / "test-user" / ".agents" / "skills"
    monkeypatch.setattr(
        "ms_agent.config.skills_manager.global_standard_skills_tree",
        lambda: empty_standard,
    )
    monkeypatch.setattr(
        "ms_agent.skill.catalog.global_standard_skills_tree",
        lambda: empty_standard,
    )
