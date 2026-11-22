"""Session plans remain local tools when settings omit the MCP flag."""
import asyncio
import json
from pathlib import Path

import pytest

from app.backends.ms_agent.bootstrap import _seed_tools_settings
from app.backends.ms_agent.config import build_agent
from ms_agent.config import Config
from ms_agent.project import ProjectManager, SessionManager
from ms_agent.tools.mcp_client import MCPClient
from ms_agent.tools.tool_manager import ToolManager
from ms_agent.ui.events import RecordingSink
from omegaconf import OmegaConf


@pytest.mark.parametrize("todo,import_after_start", [
    (None, False), ({}, False),
    ({"auto_render_md": False}, False),
    ({"mcp": False}, False), ({"enabled": False}, False),
    pytest.param(None, True, id="external-import-after-startup"),
])
def test_session_todo_stays_builtin(
    tmp_path, monkeypatch, todo, import_after_start,
):
    monkeypatch.setenv("MS_AGENT_HOME", str(tmp_path))
    settings = {"llm": {"provider": "openai", "model": "unused", "api_key": "unused"}}
    if todo is not None:
        settings["tools"] = {"todo_list": todo}
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(settings))
    _seed_tools_settings(str(tmp_path))
    if import_after_start:
        # Deployment imports replace the file without going through the SDK.
        monkeypatch.setenv("OPENAI_API_KEY", "unused")
        settings_path.write_text(json.dumps(settings))
        assert "tools" not in json.loads(settings_path.read_text())

    project = ProjectManager(base_dir=str(tmp_path)).create(
        name="Session plans", memory_enabled=False,
    )
    sessions = SessionManager(project)
    agents = [
        build_agent(project, sessions.create(), event_sink=RecordingSink(),
                    input_source=None, mcp_config={})
        for _ in range(2)
    ]

    async def check():
        for index, agent in enumerate(agents):
            cfg = agent.config
            assert cfg.tools.todo_list.mcp is False
            for key, value in (todo or {}).items():
                assert cfg.tools.todo_list[key] == value
            assert "todo_list" not in Config.convert_mcp_servers_to_json(cfg)["mcpServers"]
            # Exercise the real connection path that used to raise ValueError.
            client = MCPClient(config=cfg, mcp_config=agent.mcp_config)
            try:
                await client.connect()
                assert "todo_list" not in client.sessions
            finally:
                await client.cleanup()

            # Only load the tool under test; unrelated default tools can need
            # optional dependencies or credentials.
            tool_config = OmegaConf.create({
                "output_dir": project.path,
                "tools": {"todo_list": OmegaConf.to_container(cfg.tools.todo_list)},
            })
            manager = ToolManager(tool_config)
            try:
                await manager.connect()
                tools = await manager.get_tools()
                server_names = {entry["server_name"] for entry in tools}
                if (todo or {}).get("enabled") is False:
                    assert "todo_list" not in server_names
                    continue
                assert "todo_list" in server_names
                tool = next(t for t in manager.extra_tools if t.SERVER_NAME == "todo_list")
                result = json.loads(await tool.todo_write(todos=[{
                    "id": "one", "content": f"session-{index}", "status": "pending",
                }]))
                assert result["status"] == "ok"
                plan = json.loads(Path(cfg.tools.todo_list.plan_filename).read_text())
                assert plan["todos"][0]["content"] == f"session-{index}"
            finally:
                await manager.cleanup()

    asyncio.run(check())
    paths = [Path(agent.config.tools.todo_list.plan_filename) for agent in agents]
    assert paths[0] != paths[1]
    if (todo or {}).get("enabled") is not False:
        assert json.loads(paths[0].read_text())["todos"][0]["content"] == "session-0"
    persisted = json.loads(settings_path.read_text())["tools"]["todo_list"]
    assert persisted["mcp"] is False
    assert persisted["enabled"] is ((todo or {}).get("enabled") is not False)
    assert "plan_filename" not in persisted  # session paths never become global
    assert "plan_md_filename" not in persisted
