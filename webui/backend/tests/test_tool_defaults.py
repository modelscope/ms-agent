"""External settings replacements retain a valid, visible WebUI tool scope."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from omegaconf import OmegaConf

from app.backends.ms_agent.bootstrap import _seed_tools_settings
from app.backends.ms_agent.config import build_agent
from app.backends.ms_agent.defaults import DEFAULT_TOOLS
from app.backends.ms_agent.tool_settings import ensure_tool_settings
from ms_agent.config import Config
from ms_agent.project import ProjectManager, SessionManager
from ms_agent.tools.tool_manager import ToolManager
from ms_agent.ui.events import RecordingSink


def prepare(tmp_path, monkeypatch, tools=None):
    monkeypatch.setenv("MS_AGENT_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "unused")
    settings = {"llm": {"provider": "openai", "model": "unused", "api_key": "unused"}}
    if tools is not None:
        settings["tools"] = tools
    (tmp_path / "settings.json").write_text(json.dumps(settings))
    project = ProjectManager(base_dir=str(tmp_path)).create(name="Import", memory_enabled=False)
    return project, SessionManager(project).create(model="unused", model_provider="openai")


def build(project, session):
    return build_agent(project, session, event_sink=RecordingSink(), input_source=None, mcp_config={})


def replace_settings(tmp_path, **fields):
    """Simulate the deployment service, including its whole-file replacement."""
    data = {"llm": {"provider": "openai", "model": "unused", "api_key": "unused"}, **fields}
    path = tmp_path / "settings.json"
    incoming = tmp_path / "external.json"
    incoming.write_text(json.dumps(data))
    incoming.replace(path)
    return path


@pytest.mark.parametrize("seed,import_template", [(False, False), (True, True), (False, True)])
def test_default_tool_scope_without_persisted_defaults(tmp_path, monkeypatch, seed, import_template):
    project, session = prepare(tmp_path, monkeypatch)
    if seed:
        _seed_tools_settings(str(tmp_path))
        # Also cover external deployment services that still replace this file.
        (tmp_path / "settings.json").write_text(json.dumps({
            "llm": {"provider": "openai", "model": "unused"}}))
    if import_template:
        replace_settings(tmp_path, tools={})
    cfg = build(project, session).config
    for name, params in DEFAULT_TOOLS.items():
        for key, value in params.items():
            assert cfg.tools[name][key] == value
    assert not Config.convert_mcp_servers_to_json(cfg)["mcpServers"]
    assert list(cfg.tools.code_executor.include) == ["shell_executor"]
    assert "task_control" not in cfg.tools
    persisted = json.loads((tmp_path / "settings.json").read_text())["tools"]
    assert persisted == DEFAULT_TOOLS
    assert all(tool["enabled"] is True for tool in persisted.values())


def test_partial_and_repeated_import_respects_all_four_switches(tmp_path, monkeypatch):
    project, session = prepare(tmp_path, monkeypatch, {
        name: {"enabled": False} for name in DEFAULT_TOOLS})
    _seed_tools_settings(str(tmp_path))
    tools = {name: {"enabled": False} for name in DEFAULT_TOOLS}
    tools["todo_list"]["auto_render_md"] = False
    tools["file_system"]["exclude"] = ["write_file"]
    replace_settings(tmp_path, tools=tools)
    ensure_tool_settings(tmp_path)
    before = (tmp_path / "settings.json").read_bytes()
    replace_settings(tmp_path, tools=tools)
    ensure_tool_settings(tmp_path)
    assert (tmp_path / "settings.json").read_bytes() == before
    cfg = build(project, session).config
    assert all(cfg.tools[name].enabled is False for name in DEFAULT_TOOLS)
    assert cfg.tools.todo_list.auto_render_md is False
    assert "include" not in cfg.tools.file_system
    assert list(cfg.tools.file_system.exclude) == ["write_file"]
    manager = ToolManager(cfg)
    assert not {t.SERVER_NAME for t in manager.extra_tools} & set(DEFAULT_TOOLS)
    _seed_tools_settings(str(tmp_path))  # restart must not re-enable anything
    assert (tmp_path / "settings.json").read_bytes() == before


def test_project_tool_settings_override_imported_template(tmp_path, monkeypatch):
    project, session = prepare(tmp_path, monkeypatch)
    replace_settings(tmp_path, tools={"todo_list": {"enabled": True},
                                     "file_system": {"include": ["read_file"]}})
    patch = Path(project.path) / ".ms_agent" / "config.yaml"
    patch.parent.mkdir(exist_ok=True)
    patch.write_text("tools:\n  todo_list:\n    enabled: false\n  file_system:\n    exclude: [write_file]\n")
    cfg = build(project, session).config
    assert cfg.tools.todo_list.enabled is False
    assert cfg.tools.todo_list.mcp is False
    assert "include" not in cfg.tools.file_system
    assert list(cfg.tools.file_system.exclude) == ["write_file"]
    persisted = json.loads((tmp_path / "settings.json").read_text())["tools"]
    assert persisted["todo_list"]["enabled"] is True
    assert persisted["file_system"]["include"] == ["read_file"]
    assert "exclude" not in persisted["file_system"]


def test_null_project_tool_is_reported_before_mcp_connection(tmp_path, monkeypatch):
    project, session = prepare(tmp_path, monkeypatch)
    path = Path(project.path) / ".ms_agent" / "config.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text("tools:\n  todo_list: null\n")
    with pytest.raises(ValueError, match=r"tools.todo_list.*enabled: false"):
        build(project, session)


def test_runtime_reloads_import_on_next_idle_turn(tmp_path, monkeypatch):
    from app.backends.ms_agent import runtime
    project, session = prepare(tmp_path, monkeypatch)

    class Runtime:
        def __init__(self, project, session, mcp, model_snapshot=None):
            self.turn_lock = asyncio.Lock()
            self.run_task = SimpleNamespace(done=lambda: False)
            self.model_key = model_snapshot.key
            self.mcp_fingerprint = runtime._mcp_fingerprint(project)
            self.settings_fingerprint = runtime._settings_fingerprint(project, model_snapshot)
            self.needs_rebuild = False
            self.closed = False
        def touch(self):
            pass
        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(runtime, "SessionRuntime", Runtime)
    registry = runtime.RuntimeRegistry()
    monkeypatch.setattr(registry, "_ensure_sweeper", lambda: None)
    async def no_mcp(_project):
        return {}
    monkeypatch.setattr(registry, "_resolve_mcp", no_mcp)

    async def check():
        first = await registry.get(project, session)
        await first.turn_lock.acquire()
        replace_settings(tmp_path, tools={"todo_list": {"enabled": False}})
        assert await registry.get(project, session) is first
        assert not first.closed
        assert json.loads((tmp_path / "settings.json").read_text())["tools"]["todo_list"] == {
            "enabled": False, "mcp": False}
        first.turn_lock.release()
        second = await registry.get(project, session)
        assert second is not first and first.closed
        assert await registry.get(project, session) is second
    asyncio.run(check())
