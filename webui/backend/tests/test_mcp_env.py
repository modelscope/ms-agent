"""MCP ${VAR} placeholder support: .env injection into os.environ and the
probe's runtime view (placeholders resolved before any handshake)."""
import os

from app.backends.ms_agent import mcp_health


def test_env_files_published_to_environ():
    """settings.py publishes backend/.env + repo-root .env into os.environ
    (key presence only — values are never asserted or printed)."""
    from dotenv import dotenv_values

    from app.core.settings import _ENV_FILES, settings

    # Compare against whatever the dotenv chain actually declares rather than one
    # hard-coded key: this asserts the injection ran (conftest imports
    # app.core.settings) without breaking the next time a key is renamed.
    declared = {
        key
        for env_file in _ENV_FILES
        if env_file.exists()
        for key, value in dotenv_values(env_file).items()
        if value is not None
    }
    if not declared:
        import pytest

        pytest.skip("no .env present (copy backend/.env.example to run this)")

    assert declared <= set(os.environ)
    assert settings.cors_origin_list  # settings side intact


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
    assert ok is None and err is None  # command resolves; handshake is unverified


def test_startup_budget_roundtrips_management_and_resolver():
    from app.schemas.mcp import McpCreate, McpUpdate
    from app.backends.ms_agent import mcps, common
    from ms_agent.tui.managed_config import resolve_mcp_config
    row = mcps.create_mcp(McpCreate(name='budget-roundtrip', scope='global',
                                   endpoint='python3', startup_timeout=2.5))
    try:
        assert row.startup_timeout == 2.5
        assert resolve_mcp_config(common.home(), None)['mcpServers'][row.name]['startup_timeout'] == 2.5
        row = mcps.update_mcp(row.id, McpUpdate(startup_timeout=3.5))
        assert row.startup_timeout == 3.5
        row = mcps.update_mcp(row.id, McpUpdate(startup_timeout=None))
        assert row.startup_timeout is None
        from ms_agent.tools.mcp_client import MCPClient
        cfg = resolve_mcp_config(common.home(), None)['mcpServers'][row.name]
        assert 'startup_timeout' not in MCPClient()._plan_server(row.name, cfg, 120)
    finally:
        mcps.delete_mcp(row.id)
