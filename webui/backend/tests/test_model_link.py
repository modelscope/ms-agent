"""Offline unit tests for the model link, MCP health probe, and session naming."""
import json
from pathlib import Path

import pytest

from app.backends.errors import BadRequest, Conflict, NotFound
from app.backends.ms_agent import (
    agent_settings,
    common,
    config,
    instructions,
    mcp_health,
    mcps,
    model_link,
    sessions,
    skills,
)
from app.backends.ms_agent.mapping import encode_model_id
from app.schemas.agent_settings import AgentSettings
from app.schemas.instruction import InstructionUpsert
from app.schemas.mcp import McpCreate, McpUpdate
from app.schemas.skill import SkillCreate, SkillUpdate


def test_active_model_parsing():
    assert model_link.active_model({"default_model": "openai/qwen-max"}) == ("openai", "qwen-max")
    # bare name -> infer provider from the catalog
    assert model_link.active_model(
        {"default_model": "m1", "providers": {"p": {"models": ["m1"]}}}
    ) == ("p", "m1")
    # bare name -> fall back to the llm block's provider
    assert model_link.active_model(
        {"default_model": "m1", "llm": {"provider": "openai"}}
    ) == ("openai", "m1")
    assert model_link.active_model({"llm": {"provider": "o", "model": "m"}}) == ("o", "m")
    assert model_link.active_model({}) == (None, None)


def test_set_active_model_registers_and_preserves_creds():
    # conftest points MS_AGENT_HOME at a temp dir, so this writes there.
    model_link._save({"llm": {"provider": "openai", "model": "old",
                              "api_key": "k", "base_url": "https://dash/compatible/v1"}})
    model_link.set_active_model("openai", "new")
    d = model_link._load()
    assert d["default_model"] == "openai/new"
    assert d["llm"]["model"] == "new"
    assert d["llm"]["base_url"] == "https://dash/compatible/v1"  # working creds preserved
    assert "new" in d["providers"]["openai"]["models"]           # registered in the catalog


def test_set_active_model_honors_explicit_key_revoke():
    model_link._save({
        "llm": {"provider": "openai", "model": "old", "api_key": "old-key"},
        "providers": {"openai": {"protocol": "openai", "api_key": "", "models": ["old"]}},
    })
    model_link.set_active_model("openai", "old")
    d = model_link._load()
    assert "api_key" not in d["llm"]


def test_agent_settings_update_preserves_global_instruction():
    model_link._save({
        "default_model": "openai/old",
        "llm": {"provider": "openai", "model": "old", "api_key": "k"},
        "providers": {"openai": {"protocol": "openai", "api_key": "k", "models": ["old", "new"]}},
    })
    instructions.upsert_instruction("global", InstructionUpsert(content="keep this"))

    agent_settings.update_settings(
        AgentSettings(
            default_model_id=encode_model_id("openai", "new"),
            default_memory_enabled=False,
            default_memory_backend="file",
            global_mcp_auto_attach=False,
            global_skill_auto_attach=True,
        )
    )

    assert model_link._load()["default_model"] == "openai/new"
    assert instructions.get_instruction("global").content == "keep this"


def test_probe_stdio():
    assert mcp_health._probe_stdio({"command": "python3"}) is True
    assert mcp_health._probe_stdio({"command": "definitely-not-a-real-cmd-xyz"}) is False
    assert mcp_health._probe_stdio({"url": "http://x"}) is True  # not a stdio server


async def test_filter_healthy_drops_missing_stdio():
    servers = {"good": {"command": "python3"}, "bad": {"command": "nope-xyz-cmd"}}
    healthy = await mcp_health.filter_healthy(servers, timeout=1.0)
    assert "good" in healthy and "bad" not in healthy


async def test_check_server_reports_reason():
    ok, err = await mcp_health.check_server({"command": "python3"})
    assert ok is True and err is None
    ok, err = await mcp_health.check_server({"command": "nope-xyz-cmd"})
    assert ok is False and "not found" in err


def test_mcp_health_adapter_probes_enabled_servers():
    good = mcps.create_mcp(
        McpCreate(name="good-tool", transport="stdio", endpoint="python3 -m x", scope="global")
    )
    bad = mcps.create_mcp(
        McpCreate(name="bad-tool", transport="stdio", endpoint="nope-xyz-cmd -m y", scope="global")
    )
    try:
        rows = {h.id: h for h in mcps.health()}
        assert rows[good.id].healthy is True and rows[good.id].error is None
        assert rows[bad.id].healthy is False and rows[bad.id].error
    finally:
        mcps.delete_mcp(good.id)
        mcps.delete_mcp(bad.id)


def test_session_naming_helpers():
    assert common._is_default_name("Session abc123")
    assert common._is_default_name("")
    assert not common._is_default_name("帮我写代码")
    assert common._title_from_text("hello\nworld") == "hello"
    assert common._title_from_text("   ") == ""
    assert len(common._title_from_text("x" * 100)) == 40


def test_session_messages_reads_persisted_user_and_assistant_only():
    project = common.pm().get_default_project()
    sm = common.sm_for(project)
    session = sm.create()
    log = sm.get_session_log(session)
    log.append({"role": "system", "content": "hidden"})
    log.append({"role": "user", "content": "hello"})
    log.append({"role": "assistant", "content": "hi"})
    log.append({"role": "tool", "content": "tool result"})

    rows = sessions.list_messages(session.id)

    assert [(r.role, r.content) for r in rows] == [
        ("user", "hello"),
        ("assistant", "hi"),
    ]


def test_mcp_id_decode_errors_return_not_found_and_stdio_round_trips():
    with pytest.raises(NotFound):
        mcps.get_mcp("not-base64")

    row = mcps.create_mcp(
        McpCreate(
            name="local-tool",
            transport="stdio",
            endpoint="python3 -m demo 'arg with space'",
            scope="global",
        )
    )
    assert row.endpoint == "python3 -m demo 'arg with space'"

    with pytest.raises(Conflict):
        mcps.create_mcp(
            McpCreate(
                name="local-tool",
                transport="stdio",
                endpoint="python3 -m other",
                scope="global",
            )
        )

    other = mcps.create_mcp(
        McpCreate(
            name="other-tool",
            transport="stdio",
            endpoint="python3 -m other",
            scope="global",
        )
    )
    with pytest.raises(Conflict):
        mcps.update_mcp(other.id, McpUpdate(name="local-tool"))


def test_skill_source_requires_existing_directory(tmp_path):
    with pytest.raises(BadRequest):
        skills.create_skill(
            SkillCreate(
                name="missing",
                kind="source",
                content=str(tmp_path / "missing"),
                scope="global",
            )
        )

    skill_dir = tmp_path / "demo-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: Demo Skill\ndescription: Demo skill description\n---\n\n# Demo\n",
        encoding="utf-8",
    )

    created = skills.create_skill(
        SkillCreate(
            name="demo-skill",
            kind="source",
            content=str(skill_dir),
            scope="global",
        )
    )

    assert created.name == "Demo Skill"
    assert created.scope == "global"


def test_source_skill_disable_uses_runtime_skill_id(tmp_path):
    from omegaconf import OmegaConf

    from ms_agent.skill.catalog import SkillCatalog
    from ms_agent.tui.managed_config import merge_skills_into_config

    skill_dir = tmp_path / "runtime-skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: Demo Runtime Skill\ndescription: Runtime visible skill\n---\n\n# Demo\n",
        encoding="utf-8",
    )

    created = skills.create_skill(
        SkillCreate(
            name="demo-runtime",
            kind="source",
            content=str(skill_dir.parent),
            scope="global",
        )
    )
    assert created.enabled is True

    disabled = skills.update_skill(created.id, SkillUpdate(enabled=False))
    assert disabled.enabled is False

    skills_json = json.loads((Path(common.home()) / "skills.json").read_text())
    assert skills_json["disabled"] == ["demo"]

    project = common.pm().get_default_project()
    cfg = config._apply_webui_defaults(OmegaConf.create({"tools": {}}))
    cfg = merge_skills_into_config(cfg, common.home(), project.path)
    catalog = SkillCatalog(config=cfg.skills)
    catalog.load_from_config(cfg.skills)

    assert "demo" in catalog._skills
    assert "demo" not in catalog.get_enabled_skills()


def test_skill_bundle_import_materializes_into_live_tree():
    content = json.dumps({
        "format": "webui.skill.bundle.v1",
        "files": [
            {
                "path": "writer/SKILL.md",
                "content": (
                    "---\n"
                    "name: Writer Skill\n"
                    "description: Helps write concise copy\n"
                    "---\n\n"
                    "# Writer\n"
                ),
            },
            {"path": "writer/references/style.md", "content": "# Style\n"},
        ],
    })

    created = skills.create_skill(
        SkillCreate(
            name="writer",
            kind="bundle",
            content=content,
            scope="global",
        )
    )

    assert created.name == "Writer Skill"
    # Materialized into the live tree — presence IS registration, so nothing
    # is written to skills.json (which may not even exist).
    skill_dir = Path(common.home()) / "skills" / "writer-skill"
    assert (skill_dir / "SKILL.md").is_file()
    assert (skill_dir / "references" / "style.md").is_file()
    sj = Path(common.home()) / "skills.json"
    if sj.exists():
        sources = json.loads(sj.read_text()).get("sources", [])
        assert not any(Path(str(src)).name == "writer-skill" for src in sources)
    assert any(row.name == "Writer Skill" for row in skills.list_skills("global"))


def test_live_tree_skill_discovered_and_deletable():
    """A skill dir dropped into <home>/skills is listed without any skills.json
    entry (presence = registration), and deleting it removes the directory."""
    tree_dir = Path(common.home()) / "skills" / "dropped-skill"
    tree_dir.mkdir(parents=True)
    (tree_dir / "SKILL.md").write_text(
        "---\nname: Dropped Skill\ndescription: Appears by presence\n---\n\n# D\n",
        encoding="utf-8",
    )

    rows = [r for r in skills.list_skills("global") if r.name == "Dropped Skill"]
    assert rows and rows[0].id.startswith("src::")

    skills.delete_skill(rows[0].id)
    assert not tree_dir.exists()
    assert not any(r.name == "Dropped Skill" for r in skills.list_skills("global"))


def test_external_source_skill_delete_protected(tmp_path):
    """Skills from an explicit source OUTSIDE the live tree stay delete-protected."""
    ext = tmp_path / "ext-skills" / "outside"
    ext.mkdir(parents=True)
    (ext / "SKILL.md").write_text(
        "---\nname: Outside Skill\ndescription: External source\n---\n\n# O\n",
        encoding="utf-8",
    )
    skills.create_skill(
        SkillCreate(name="outside", kind="source", content=str(ext.parent), scope="global")
    )
    rows = [r for r in skills.list_skills("global") if r.name == "Outside Skill"]
    assert rows
    with pytest.raises(BadRequest):
        skills.delete_skill(rows[0].id)
    assert ext.exists()


def test_webui_defaults_enable_skill_runtime():
    """_apply_webui_defaults seeds skill-runtime defaults but no longer injects
    builtin tools — those come from settings.json via the SDK resolver now."""
    from omegaconf import OmegaConf

    cfg = config._apply_webui_defaults(OmegaConf.create({"tools": {}}))

    assert cfg.skills.prompt_injection == "all"
    assert cfg.skills.auto_discover is True
    assert cfg.skills.enable_manage is False
    # Tools are left untouched here (no file_system/todo_list injection).
    assert "file_system" not in cfg.tools


def test_seed_tools_settings_writes_default_block(tmp_path):
    """bootstrap seeds a full builtin-tools block into settings.json so tools are
    default-enabled; code_executor runs local shell (gated by permission),
    web_search is present but opt-in (enabled=False), and task_control (no UI
    component) is not seeded."""
    from app.backends.ms_agent import bootstrap

    bootstrap._seed_tools_settings(str(tmp_path))
    tools = json.loads((tmp_path / "settings.json").read_text())["tools"]

    assert tools["file_system"]["mcp"] is False
    assert tools["file_system"]["include"] == [
        "read_file", "grep", "glob", "edit_file", "write_file",
    ]
    assert tools["todo_list"]["mcp"] is False
    assert tools["code_executor"]["implementation"] == "python_env"
    assert tools["code_executor"]["include"] == ["shell_executor"]  # terminal only
    assert tools["web_search"]["enabled"] is False
    assert "task_control" not in tools

    # Migration on an existing block: keep user tools untouched, drop retired
    # defaults (task_control), add newly-introduced defaults (code_executor),
    # and narrow an un-customized code_executor to shell-only.
    (tmp_path / "settings.json").write_text(json.dumps(
        {"tools": {"todo_list": {"user_edit": 1}, "task_control": {"mcp": False},
                   "code_executor": {"mcp": False, "implementation": "python_env"}}}))
    bootstrap._seed_tools_settings(str(tmp_path))
    migrated = json.loads((tmp_path / "settings.json").read_text())["tools"]
    assert "task_control" not in migrated             # retired -> dropped
    assert migrated["todo_list"] == {"user_edit": 1}  # user config preserved
    assert migrated["code_executor"]["include"] == ["shell_executor"]  # narrowed
    assert migrated["code_executor"]["implementation"] == "python_env"  # new default added


def test_settings_tools_disable_resolves_through_config(tmp_path):
    """settings.json `tools.<id>.enabled: false` survives the SDK multi-level
    resolve, so a higher config layer can turn a seeded builtin tool off."""
    from ms_agent.config import ConfigResolver

    (tmp_path / "settings.json").write_text(json.dumps({
        "tools": {
            "file_system": {"mcp": False},
            "web_search": {"mcp": False, "enabled": False},
        }
    }))

    cfg = ConfigResolver(global_dir=str(tmp_path)).resolve()

    assert "file_system" in cfg.tools
    assert cfg.tools.web_search.enabled is False


def test_webui_generation_params_are_applied_to_runtime_config():
    from omegaconf import OmegaConf

    from app.backends.ms_agent import sidecar
    from app.backends.ms_agent.mapping import encode_model_id

    provider = "testprov-gen"
    model = "kimi-k2.5"
    model_id = encode_model_id(provider, model)
    sidecar.merge(
        "providers",
        provider,
        {"default_generation_params": {"max_tokens": 123, "temperature": 0.8}},
    )
    sidecar.merge("models", model_id, {"advanced_params": {"top_p": 0.9}})

    cfg = OmegaConf.create({
        "llm": {"service": provider, "model": model},
        "generation_config": {"temperature": 0.3, "extra_body": {"enable_thinking": True}},
    })

    cfg = config._apply_webui_generation_params(cfg)
    cfg = config._apply_model_compatibility(cfg)

    assert cfg.generation_config.max_tokens == 123
    assert cfg.generation_config.top_p == 0.9
    assert cfg.generation_config.temperature == 1.0
    assert cfg.generation_config.extra_body.enable_thinking is False


def test_user_thinking_param_overrides_provider_default_off():
    """A non-Qwen provider defaults enable_thinking off, but an explicit user
    thinking param (per-provider thinking control) must win (#5)."""
    from omegaconf import OmegaConf

    from app.backends.ms_agent import sidecar
    from app.backends.ms_agent.mapping import encode_model_id

    provider = "kimi-think"
    model = "kimi-k2.5"
    sidecar.merge(
        "models",
        encode_model_id(provider, model),
        {"advanced_params": {"extra_body": {"enable_thinking": True}}},
    )
    cfg = OmegaConf.create({
        "llm": {"service": provider, "model": model},
        "generation_config": {"extra_body": {"enable_thinking": True}},
    })
    cfg = config._apply_webui_generation_params(cfg)
    cfg = config._apply_model_compatibility(cfg)

    # Without the user param this provider would be forced to False; it wins here.
    assert cfg.generation_config.extra_body.enable_thinking is True


def test_sdk_default_temperature_is_removed_unless_webui_explicit():
    from omegaconf import OmegaConf

    cfg = OmegaConf.create({
        "llm": {"service": "plain-provider", "model": "plain-model"},
        "generation_config": {"temperature": 0.3, "stream": True},
    })

    cfg = config._apply_model_compatibility(cfg)

    assert "temperature" not in cfg.generation_config
    assert cfg.generation_config.stream is True
