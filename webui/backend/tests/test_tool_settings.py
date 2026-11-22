"""Persist defaults after deployment writes, without rewriting user choices."""
import json
import stat

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backends.errors import BadRequest
from app.backends.ms_agent import tool_settings
from app.backends.ms_agent.defaults import DEFAULT_TOOLS


def write_settings(tmp_path, data):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data))
    return path


def test_missing_defaults_persist_without_session_or_credential_changes(tmp_path):
    original = {
        "llm": {"provider": "local", "model": "chat", "api_key": "local-test-key"},
        "theme": "dark",
        "tools": {
            "todo_list": {"enabled": False, "auto_render_md": False},
            "file_system": {"include": ["read_file"]},
            "web_search": {"engine": "exa", "exa_api_key": "search-test-key"},
            "custom_mcp": {"mcp": True, "command": "test-server", "enabled": False},
        },
    }
    path = write_settings(tmp_path, original)
    actual = tool_settings.ensure_tool_settings(tmp_path)
    assert actual["llm"] == original["llm"]
    assert actual["theme"] == "dark"
    assert actual["tools"]["todo_list"] == {
        "enabled": False, "mcp": False, "auto_render_md": False}
    assert actual["tools"]["file_system"]["include"] == ["read_file"]
    assert actual["tools"]["custom_mcp"] == original["tools"]["custom_mcp"]
    assert actual["tools"]["web_search"]["exa_api_key"] == "search-test-key"
    assert actual["tools"]["web_search"]["engine"] == "exa"
    assert json.loads(path.read_text()) == actual
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    before, stamp = path.read_bytes(), path.stat().st_mtime_ns
    assert tool_settings.ensure_tool_settings(tmp_path) == actual
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == stamp


@pytest.mark.parametrize("raw", [
    "{broken", "[]", '{"tools":null}', '{"tools":{"todo_list":null}}',
    '{"tools":{"code_executor":{"enabled":"false"}}}',
    '{"tools":{"todo_list":{"mcp":true}}}',
])
def test_invalid_external_file_is_reported_and_left_untouched(tmp_path, raw):
    path = tmp_path / "settings.json"
    path.write_text(raw)
    with pytest.raises(BadRequest) as caught:
        tool_settings.ensure_tool_settings(tmp_path)
    assert caught.value.status_code == 400
    assert "settings" in caught.value.detail
    assert path.read_text() == raw
    assert not list(tmp_path.glob(".settings-*"))


def test_external_replacement_does_not_restore_old_model_or_credentials(tmp_path):
    path = write_settings(tmp_path, {"llm": {"api_key": "old-test-key"},
                                    "tools": {"todo_list": {"enabled": False}}})
    tool_settings.ensure_tool_settings(tmp_path)
    path.write_text('{"llm":{"provider":"new","model":"new-model"}}')
    actual = tool_settings.ensure_tool_settings(tmp_path)
    assert actual["llm"] == {"provider": "new", "model": "new-model"}
    # The external writer deleted the previous switch; absence follows defaults.
    assert actual["tools"] == DEFAULT_TOOLS
    assert "old-test-key" not in path.read_text()


def test_recheck_preserves_an_external_edit_during_normalization(tmp_path, monkeypatch):
    path = write_settings(tmp_path, {"theme": "before"})
    original_read = tool_settings._read
    calls = 0

    def concurrent_read(target):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_text('{"theme":"after","tools":{"todo_list":{"enabled":false}}}')
        return original_read(target)

    monkeypatch.setattr(tool_settings, "_read", concurrent_read)
    actual = tool_settings.ensure_tool_settings(tmp_path)
    assert actual["theme"] == "after"
    assert actual["tools"]["todo_list"]["enabled"] is False
    assert json.loads(path.read_text()) == actual
    assert not list(tmp_path.glob(".settings-*"))


@pytest.mark.parametrize("route", ["/api/agent-settings", "/api/search-settings"])
def test_settings_api_reconciles_external_import_without_restart(tmp_path, monkeypatch, route):
    from app.api import agent_settings, search
    from app.core.envelope import register_exception_handlers

    monkeypatch.setenv("MS_AGENT_HOME", str(tmp_path))
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(agent_settings.router)
    app.include_router(search.router)
    client = TestClient(app)
    path = write_settings(tmp_path, {"tools": {"web_search": {"enabled": False}}})
    first = client.get(route)
    assert first.status_code == 200
    assert json.loads(path.read_text())["tools"]["web_search"]["enabled"] is False
    # No SDK import hook or service restart: the next read completes this file.
    path.write_text('{"llm":{"provider":"openai","model":"imported"}}')
    second = client.get(route)
    assert second.status_code == 200
    assert json.loads(path.read_text())["tools"] == DEFAULT_TOOLS
    path.write_text('{"tools":{"todo_list":null}}')
    rejected = client.get(route)
    assert rejected.status_code == 400
    assert "enabled: false" in rejected.json()["message"]
    assert json.loads(path.read_text())["tools"]["todo_list"] is None
