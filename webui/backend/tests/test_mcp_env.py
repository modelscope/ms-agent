"""MCP ${VAR} placeholder support: .env injection into os.environ and the
probe's runtime view (placeholders resolved before any handshake)."""
import os

from app.backends.ms_agent import mcp_health


def test_env_files_published_to_environ():
    """settings.py publishes backend/.env + repo-root .env into os.environ
    (key presence only — values are never asserted or printed)."""
    # AGENT_BACKEND lives in backend/.env; its being loadable proves the
    # injection ran at import time (conftest imports app.core.settings).
    from app.core.settings import settings

    assert settings.agent_backend  # settings side intact
    assert "AGENT_BACKEND" in os.environ or "agent_backend" in os.environ


def test_probe_runtime_view_expands_placeholders(monkeypatch):
    monkeypatch.setenv("PROBE_TOKEN", "tok-123")
    entry = {
        "url": "https://gw/sse",
        "transport": "sse",
        "headers": {"Authorization": "Bearer ${PROBE_TOKEN}"},
    }
    view = mcp_health._runtime_view(entry)
    assert view["headers"]["Authorization"] == "Bearer tok-123"
    # Original entry untouched (management surfaces keep the placeholder).
    assert entry["headers"]["Authorization"] == "Bearer ${PROBE_TOKEN}"
    # Idempotent on already-expanded entries.
    assert mcp_health._runtime_view(view) == view


def test_probe_stdio_uses_expanded_command(monkeypatch):
    monkeypatch.setenv("MY_BIN", "python3")
    entry = {"command": "${MY_BIN}", "args": ["-V"]}
    import asyncio

    ok, err = asyncio.run(mcp_health.check_server(entry))
    assert ok, err  # python3 resolves on PATH once expanded
