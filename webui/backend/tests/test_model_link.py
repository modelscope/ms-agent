"""Offline unit tests for the model link, MCP health probe, and session naming."""
import asyncio
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
from app.schemas.skill import SkillCreate, SkillPathImport, SkillUpdate


@pytest.fixture
def prepared_project_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("MS_AGENT_HOME", str(tmp_path))
    common.pm().initialize()


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
    mcp_health.invalidate_cache()
    healthy, dropped = await mcp_health.filter_healthy(servers, timeout=1.0)
    assert "good" in healthy and "bad" not in healthy
    # The REASON now comes back too: it used to be logged and thrown away, which
    # is how a stale server became invisible to every UI surface.
    assert "bad" in dropped and "not found" in dropped["bad"]
    assert "good" not in dropped


async def test_timeout_is_retried_once_but_protocol_errors_are_not():
    """A timeout means "nobody answered in N seconds of wall clock", which this
    process can cause by starving its own coroutine — a healthy endpoint that
    answers in 0.7 s was struck through in the UI and withheld from the model
    because its first probe timed out. A protocol answer is not ambiguous."""
    calls = {"n": 0}

    async def _slow_then_fine(server):
        calls["n"] += 1
        if calls["n"] == 1:
            raise asyncio.TimeoutError
        return True

    original = mcp_health._remote_handshake
    mcp_health._remote_handshake = _slow_then_fine
    try:
        ok, err = await mcp_health.check_server({"url": "http://x/mcp"}, 0.5)
        assert ok is True and err is None
        assert calls["n"] == 2, "the timeout should be retried exactly once"
    finally:
        mcp_health._remote_handshake = original

    # A decisive failure is believed immediately — no wasted second attempt.
    calls["n"] = 0

    async def _protocol_error(server):
        calls["n"] += 1
        raise RuntimeError("Session terminated")

    mcp_health._remote_handshake = _protocol_error
    try:
        ok, err = await mcp_health.check_server({"url": "http://x/mcp"}, 0.5)
        assert ok is False and "Session terminated" in err
        assert calls["n"] == 1
    finally:
        mcp_health._remote_handshake = original


async def test_failures_expire_sooner_than_successes():
    """A cached failure withholds the server from the model, so it must not
    outlive the blip that caused it."""
    assert mcp_health._TTL_FAIL < mcp_health._TTL_OK
    assert mcp_health._ttl(True) == mcp_health._TTL_OK
    assert mcp_health._ttl(False) == mcp_health._TTL_FAIL


async def test_filter_healthy_caches_probes():
    """One unreachable server used to cost the full timeout on EVERY session
    build (measured: a flat +6 s per new conversation)."""
    probes = []

    async def _counting(server, timeout=6.0):
        probes.append(server)
        return False, "timed out"

    mcp_health.invalidate_cache()
    original = mcp_health.check_server
    mcp_health.check_server = _counting
    try:
        servers = {"slow": {"url": "http://10.255.255.1:9/mcp"}}
        for _ in range(3):
            healthy, dropped = await mcp_health.filter_healthy(servers, timeout=1.0)
            assert not healthy and dropped["slow"] == "timed out"
        assert len(probes) == 1, "cached after the first probe"
        mcp_health.invalidate_cache()
        await mcp_health.filter_healthy(servers, timeout=1.0)
        assert len(probes) == 2, "an explicit re-check bypasses the cache"
    finally:
        mcp_health.check_server = original
        mcp_health.invalidate_cache()


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


def test_session_messages_reads_persisted_user_and_assistant_only(prepared_project_storage):
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


def test_project_mcp_can_be_re_added_after_removal(prepared_project_storage):
    """Removing a project MCP that shadows a GLOBAL one leaves a MASK in the
    project file (that is how a project hides a global server). The mask is a row
    that exists without defining a server, so `list` skipped it while the
    id-addressed operations did not — the card vanished but the name stayed
    taken: re-adding it answered "already exists", `get` returned a phantom entry
    with an empty endpoint, and `update` wrote an ENABLED row for a server that
    was never defined."""
    from ms_agent.config import MCPConfigManager

    from app.backends.ms_agent.common import pm

    proj = pm().list()[0]
    scope = f"project:{proj.id}"
    url = "http://127.0.0.1:1/mcp"
    glob = mcps.create_mcp(
        McpCreate(name="shadowed", transport="http", endpoint=url, scope="global")
    )
    try:
        first = mcps.create_mcp(
            McpCreate(name="shadowed", transport="http", endpoint=url, scope=scope)
        )
        mcps.delete_mcp(first.id)
        # Gone from the listing...
        assert "shadowed" not in [m.name for m in mcps.list_mcps(scope)]
        # ...and therefore gone from every other view of the same scope.
        with pytest.raises(NotFound):
            mcps.get_mcp(first.id)
        with pytest.raises(NotFound):
            mcps.update_mcp(first.id, McpUpdate(enabled=True))
        with pytest.raises(NotFound):
            mcps.delete_mcp(first.id)
        # The reported symptom: adding it back must work, repeatedly.
        for _ in range(2):
            again = mcps.create_mcp(
                McpCreate(name="shadowed", transport="http", endpoint=url, scope=scope)
            )
            assert again.endpoint == url
            assert "shadowed" in [m.name for m in mcps.list_mcps(scope)]
            mcps.delete_mcp(again.id)
        # The global definition survives, and is INHERITED again once the
        # project override is gone — delete removes the override, it does not
        # suppress the server. "Off for this project" is the card's switch.
        assert "shadowed" in [m.name for m in mcps.list_mcps("global")]
        proj_file = json.loads(
            MCPConfigManager(
                global_root=common.home(), project_root=proj.path
            ).project_mcp_path.read_text(encoding="utf-8")
        )
        assert "shadowed" not in proj_file.get("mcpServers", {}), (
            "the row must be gone, not left as a mask"
        )
    finally:
        try:
            mcps.delete_mcp(glob.id)
        except Exception:
            pass


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
    assert created.origin == "managed"
    copied = Path(common.home()) / "skills" / "demo-skill"
    assert (copied / "SKILL.md").is_file()
    # Import is a copy: the caller-owned directory remains untouched and no
    # path reference is added to skills.json.
    assert (skill_dir / "SKILL.md").is_file()
    sj = Path(common.home()) / "skills.json"
    if sj.exists():
        assert str(skill_dir) not in (sj.read_text(encoding="utf-8"))


def test_source_skill_disable_uses_runtime_skill_id(tmp_path, prepared_project_storage):
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


# NOTE: conftest points MS_AGENT_HOME at ONE temp dir for the whole session, so
# the live skills tree is shared between tests. Each test below therefore uses its
# own skill name — otherwise the first import would collide with a neighbour's
# leftovers and the collision under test would be indistinguishable from that.
def _writer_bundle(
    marker: str,
    *,
    name: str,
    description: str = "Helps write concise copy",
) -> str:
    """A valid single-skill bundle whose body carries `marker`."""
    return json.dumps({
        "format": "webui.skill.bundle.v1",
        "files": [
            {
                "path": "writer/SKILL.md",
                "content": (
                    "---\n"
                    f"name: {name}\n"
                    f"description: {description}\n"
                    "---\n\n"
                    f"# Writer\n\nmarker: {marker}\n"
                ),
            },
            {"path": f"writer/{marker}.md", "content": f"# {marker}\n"},
        ],
    })


def _import_writer(content: str, *, overwrite: bool = False):
    return skills.create_skill(
        SkillCreate(
            name="writer",
            kind="bundle",
            content=content,
            scope="global",
            overwrite=overwrite,
        )
    )


def test_skill_bundle_duplicate_name_is_rejected_without_overwrite():
    name, dirname = "Dup Reject Skill", "dup-reject-skill"
    _import_writer(_writer_bundle("first", name=name))
    root = Path(common.home()) / "skills"

    with pytest.raises(Conflict):
        _import_writer(_writer_bundle("second", name=name))

    # The original is intact and NO `-2` shadow directory was left behind (the
    # old behaviour wrote one that the registry then hid).
    assert (root / dirname / "first.md").is_file()
    assert not (root / f"{dirname}-2").exists()
    assert not (root / dirname / "second.md").exists()
    assert len([r for r in skills.list_skills("global") if r.name == name]) == 1


def test_skill_bundle_overwrite_replaces_the_existing_directory():
    name, dirname = "Overwrite Skill", "overwrite-skill"
    _import_writer(_writer_bundle("first", name=name))
    root = Path(common.home()) / "skills"

    created = _import_writer(
        _writer_bundle("second", name=name, description="Rewritten copy"),
        overwrite=True,
    )

    assert created.name == name
    assert created.content == "Rewritten copy"
    skill_dir = root / dirname
    # Replaced, not merged: the previous marker file is gone.
    assert (skill_dir / "second.md").is_file()
    assert not (skill_dir / "first.md").exists()
    assert "marker: second" in (skill_dir / "SKILL.md").read_text()
    # Still exactly one entry, and no staging directories survive the swap.
    assert len([r for r in skills.list_skills("global") if r.name == name]) == 1
    assert not list(root.glob(f".{dirname}.*"))


def test_skill_bundle_overwrite_keeps_original_when_new_bundle_is_invalid():
    name, dirname = "Rollback Skill", "rollback-skill"
    _import_writer(_writer_bundle("first", name=name))
    root = Path(common.home()) / "skills"

    # Frontmatter without a description is rejected during validation, i.e.
    # AFTER the overwrite has been requested — the existing skill must survive.
    broken = json.dumps({
        "format": "webui.skill.bundle.v1",
        "files": [
            {
                "path": "writer/SKILL.md",
                "content": f"---\nname: {name}\n---\n\n# Writer\n",
            }
        ],
    })
    with pytest.raises(BadRequest):
        _import_writer(broken, overwrite=True)

    skill_dir = root / dirname
    assert (skill_dir / "first.md").is_file()
    assert "marker: first" in (skill_dir / "SKILL.md").read_text()
    assert "description:" in (skill_dir / "SKILL.md").read_text()
    assert not list(root.glob(f".{dirname}.*"))


def test_skill_bundle_overwrite_on_a_fresh_name_just_creates_it():
    # `overwrite=True` must not require an existing skill.
    name, dirname = "Fresh Overwrite Skill", "fresh-overwrite-skill"
    created = _import_writer(_writer_bundle("only", name=name), overwrite=True)

    assert created.name == name
    root = Path(common.home()) / "skills"
    assert (root / dirname / "only.md").is_file()
    assert not list(root.glob(f".{dirname}.*"))


def test_skill_slug_keeps_non_ascii_names():
    """A CJK name keeps its characters instead of collapsing to "skill".

    The old ASCII allowlist erased them entirely, so every Chinese-named skill
    landed in the same `skill` directory and the second one "already existed".
    """
    assert skills._slug("中文技能") == "中文技能"
    assert skills._slug("数据分析") == "数据分析"
    assert skills._slug("中文技能") != skills._slug("数据分析")
    assert skills._slug("café helper") == "café-helper"
    # Still neutralises what a path genuinely cannot hold, and never yields a
    # hidden/traversal-looking or Windows-reserved component.
    assert "/" not in skills._slug("a/b")
    assert skills._slug("../../etc/passwd") == "etc-passwd"
    assert not skills._slug("../etc").startswith(".")
    assert not skills._slug(".hidden").startswith(".")
    assert skills._slug("CON") == "skill"
    assert skills._slug("   ") == "skill"
    assert skills._slug("MySkill") == skills._slug("myskill")
    # Truncation is by BYTES (filesystem components cap at 255), and must not
    # leave a half-encoded character behind.
    for probe in ("技" * 200, "🎯" * 200, "a" * 400):
        out = skills._slug(probe)
        assert len(out.encode()) <= 128
        assert out.encode().decode() == out


def test_chinese_named_skills_do_not_collide_with_each_other():
    first = _import_writer(_writer_bundle("a", name="中文技能一"))
    second = _import_writer(_writer_bundle("b", name="中文技能二"))

    assert first.name == "中文技能一"
    assert second.name == "中文技能二"
    root = Path(common.home()) / "skills"
    assert (root / "中文技能一" / "a.md").is_file()
    assert (root / "中文技能二" / "b.md").is_file()
    # And a same-named CJK import is still caught as a conflict.
    with pytest.raises(Conflict):
        _import_writer(_writer_bundle("c", name="中文技能一"))


def test_conflict_is_detected_for_a_nested_source_not_only_by_directory():
    """A skill registered from a nested source occupies its NAME even though
    `<tree>/<slug>` is free. Checking only that directory let a second skill with
    the same name be created for the registry to shadow."""
    root = Path(common.home()) / "skills"
    nested = root / "vendor" / "oddly-placed"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "SKILL.md").write_text(
        "---\nname: Nested Skill\ndescription: lives off the slug path\n---\n\n"
        "# Nested\n\nmarker: original\n",
        encoding="utf-8",
    )
    from ms_agent.config.skills_manager import SkillsConfigManager

    SkillsConfigManager(global_dir=common.home()).add_source(
        str(nested), scope="global"
    )
    assert any(r.name == "Nested Skill" for r in skills.list_skills("global"))
    # The directory a plain slug check would have looked at is genuinely free.
    assert not (root / "nested-skill").exists()

    with pytest.raises(Conflict):
        _import_writer(_writer_bundle("new", name="Nested Skill"))
    assert not (root / "nested-skill").exists()

    # Overwriting replaces the directory it actually occupies, so the source
    # registration keeps pointing at live files.
    _import_writer(_writer_bundle("new", name="Nested Skill"), overwrite=True)
    assert (nested / "new.md").is_file()
    assert "marker: new" in (nested / "SKILL.md").read_text()
    assert not (root / "nested-skill").exists()
    assert len([r for r in skills.list_skills("global") if r.name == "Nested Skill"]) == 1


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


def test_legacy_path_skill_delete_removes_the_registration(tmp_path):
    """Old skills.json path references remain deletable after imports switch
    to copies. Deleting removes the reference, never the caller-owned files."""
    from ms_agent.config.skills_manager import SkillsConfigManager

    ext = tmp_path / "ext-skills" / "outside"
    ext.mkdir(parents=True)
    (ext / "SKILL.md").write_text(
        "---\nname: Outside Skill\ndescription: External source\n---\n\n# O\n",
        encoding="utf-8",
    )
    manager = SkillsConfigManager(global_dir=common.home())
    manager.add_source(str(ext.parent), scope="global")
    skills._invalidate_scope("global")
    rows = [r for r in skills.list_skills("global") if r.name == "Outside Skill"]
    assert rows and rows[0].origin == "legacy-path" and rows[0].removable

    skills.delete_skill(rows[0].id)

    assert not any(r.name == "Outside Skill" for r in skills.list_skills("global"))
    assert str(ext.parent) not in manager.list_explicit_sources(scope="global")
    # The referenced directory is left alone — deleting it is not ours to do.
    assert ext.exists() and (ext / "SKILL.md").exists()


def test_legacy_shared_source_delete_removes_reference_and_keeps_files(tmp_path):
    """A legacy source is one registration unit. Removing either displayed
    card removes that one reference (and therefore its sibling cards) while all
    original directories remain intact."""
    from ms_agent.config.skills_manager import SkillsConfigManager

    root = tmp_path / "shared-skills"
    for name in ("alpha", "beta"):
        d = root / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name.title()} Skill\ndescription: shared\n---\n\n# {name}\n",
            encoding="utf-8",
        )
    manager = SkillsConfigManager(global_dir=common.home())
    manager.add_source(str(root), scope="global")
    skills._invalidate_scope("global")
    rows = [r for r in skills.list_skills("global") if r.name == "Alpha Skill"]
    assert rows and rows[0].origin == "legacy-path"

    skills.delete_skill(rows[0].id)

    remaining = {row.name for row in skills.list_skills("global")}
    assert "Alpha Skill" not in remaining and "Beta Skill" not in remaining
    assert str(root) not in manager.list_explicit_sources(scope="global")
    assert (root / "alpha" / "SKILL.md").is_file()
    assert (root / "beta" / "SKILL.md").is_file()


def test_path_import_copies_all_skills_as_one_transaction(tmp_path):
    root = tmp_path / "copy-pack"
    for directory, display in (
        ("copy-alpha", "Copy Alpha Skill"),
        ("copy-beta", "Copy Beta Skill"),
    ):
        skill_dir = root / directory
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {display}\ndescription: copied path\n---\n\n# {display}\n",
            encoding="utf-8",
        )
        (skill_dir / "marker.txt").write_text("original", encoding="utf-8")

    imported = skills.import_skills_from_path(
        SkillPathImport(path=str(root), scope="global")
    )

    assert {row.name for row in imported} == {
        "Copy Alpha Skill", "Copy Beta Skill",
    }
    assert all(row.origin == "managed" and row.removable for row in imported)
    managed = Path(common.home()) / "skills"
    for directory in ("copy-alpha", "copy-beta"):
        assert (managed / directory / "SKILL.md").is_file()
        assert (root / directory / "SKILL.md").is_file()
    # Prove this is a copy, not a live reference.
    (root / "copy-alpha" / "marker.txt").write_text("changed", encoding="utf-8")
    assert (managed / "copy-alpha" / "marker.txt").read_text() == "original"

    from ms_agent.config.skills_manager import SkillsConfigManager

    explicit = SkillsConfigManager(global_dir=common.home()).list_explicit_sources(
        scope="global"
    )
    assert str(root) not in explicit


def test_path_import_conflict_is_atomic_and_overwrite_replaces(tmp_path):
    managed = Path(common.home()) / "skills"
    _import_writer(_writer_bundle("old", name="Path Replace Skill"))
    source = tmp_path / "replace-pack"
    target = source / "incoming-target"
    sibling = source / "incoming-sibling"
    for directory, display, marker in (
        (target, "Path Replace Skill", "new"),
        (sibling, "Path Atomic Sibling", "sibling"),
    ):
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: {display}\ndescription: path batch\n---\n\nmarker: {marker}\n",
            encoding="utf-8",
        )

    with pytest.raises(Conflict):
        skills.import_skills_from_path(
            SkillPathImport(path=str(source), scope="global")
        )
    # Batch preflight means the non-conflicting sibling was not copied either.
    assert not (managed / "incoming-sibling").exists()
    assert (managed / "path-replace-skill" / "old.md").is_file()

    imported = skills.import_skills_from_path(
        SkillPathImport(path=str(source), scope="global", overwrite=True)
    )
    assert {row.name for row in imported} == {
        "Path Replace Skill", "Path Atomic Sibling",
    }
    # Existing display name keeps its actual managed directory; its old files
    # are replaced instead of merged.
    replaced = managed / "path-replace-skill"
    assert "marker: new" in (replaced / "SKILL.md").read_text()
    assert not (replaced / "old.md").exists()
    assert (managed / "incoming-sibling" / "SKILL.md").is_file()


def test_path_import_never_replaces_a_different_skill_by_directory_name(tmp_path):
    managed = Path(common.home()) / "skills"
    occupied = managed / "same-directory"
    occupied.mkdir(parents=True)
    (occupied / "SKILL.md").write_text(
        "---\nname: Existing Different Skill\ndescription: keep me\n---\n\nold\n",
        encoding="utf-8",
    )
    source = tmp_path / "directory-collision" / "same-directory"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: Incoming Different Skill\ndescription: do not replace\n---\n\nnew\n",
        encoding="utf-8",
    )

    for overwrite in (False, True):
        with pytest.raises(Conflict):
            skills.import_skills_from_path(
                SkillPathImport(
                    path=str(source.parent),
                    scope="global",
                    overwrite=overwrite,
                )
            )

    assert "Existing Different Skill" in (occupied / "SKILL.md").read_text()
    assert "old" in (occupied / "SKILL.md").read_text()


def test_legacy_same_name_overwrite_migrates_siblings_then_replaces(tmp_path):
    from ms_agent.config.skills_manager import SkillsConfigManager

    root = tmp_path / "legacy-overwrite-pack"
    for directory, display in (
        ("legacy-target", "Legacy Replace Target"),
        ("legacy-sibling", "Legacy Replace Sibling"),
    ):
        skill_dir = root / directory
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {display}\ndescription: legacy old\n---\n\nmarker: old\n",
            encoding="utf-8",
        )

    manager = SkillsConfigManager(global_dir=common.home())
    manager.add_source(str(root), scope="global")
    skills._invalidate_scope("global")
    assert any(
        row.name == "Legacy Replace Target" and row.origin == "legacy-path"
        for row in skills.list_skills("global")
    )

    replaced = _import_writer(
        _writer_bundle("new", name="Legacy Replace Target"), overwrite=True
    )

    assert replaced.origin == "managed"
    assert str(root) not in manager.list_explicit_sources(scope="global")
    managed = Path(common.home()) / "skills"
    assert (managed / "legacy-target" / "new.md").is_file()
    assert (managed / "legacy-sibling" / "SKILL.md").is_file()
    names = {row.name for row in skills.list_skills("global")}
    assert "Legacy Replace Target" in names
    assert "Legacy Replace Sibling" in names
    # Migration never edits the path the user originally referenced.
    assert "marker: old" in (root / "legacy-target" / "SKILL.md").read_text()


def test_standard_agents_skill_is_live_but_not_deletable(tmp_path, monkeypatch):
    standard = tmp_path / ".agents" / "skills"
    skill_dir = standard / "standard-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: Standard Agents Skill\ndescription: standard live tree\n---\n\n# S\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ms_agent.config.skills_manager.global_standard_skills_tree",
        lambda: standard,
    )
    skills._invalidate_scope("global")

    rows = [
        row for row in skills.list_skills("global")
        if row.name == "Standard Agents Skill"
    ]
    assert rows and rows[0].origin == "standard" and not rows[0].removable
    with pytest.raises(BadRequest):
        skills.delete_skill(rows[0].id)
    assert (skill_dir / "SKILL.md").is_file()


def test_managed_skill_wins_same_runtime_id_over_standard_tree(tmp_path, monkeypatch):
    standard = tmp_path / ".agents" / "skills"
    standard_skill = standard / "same-runtime-id"
    standard_skill.mkdir(parents=True)
    (standard_skill / "SKILL.md").write_text(
        "---\nname: Shadowed Standard Skill\ndescription: lower priority\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ms_agent.config.skills_manager.global_standard_skills_tree",
        lambda: standard,
    )
    managed = Path(common.home()) / "skills" / "same-runtime-id"
    managed.mkdir(parents=True)
    (managed / "SKILL.md").write_text(
        "---\nname: Effective Managed Skill\ndescription: higher priority\n---\n",
        encoding="utf-8",
    )
    skills._invalidate_scope("global")

    rows = skills.list_skills("global")
    effective = [row for row in rows if row.name == "Effective Managed Skill"]
    assert len(effective) == 1 and effective[0].origin == "managed"
    assert not any(row.name == "Shadowed Standard Skill" for row in rows)
    assert skills.get_skill(effective[0].id).name == "Effective Managed Skill"

    skills.delete_skill(effective[0].id)
    assert not managed.exists()
    rows = skills.list_skills("global")
    shadowed = [row for row in rows if row.name == "Shadowed Standard Skill"]
    assert len(shadowed) == 1 and not shadowed[0].removable


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
    web_search is on by default (opt-out; credentials configured separately under
    Settings -> Search), and task_control (no UI component) is not seeded."""
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
    assert all(tool["enabled"] is True for tool in tools.values())
    # Tavily, not exa: the seeded engine must be one that works with no
    # credentials (keyless tier), so a fresh install can search immediately.
    assert tools["web_search"]["engine"] == "tavily"
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
    assert migrated["todo_list"] == {"enabled": True, "mcp": False, "user_edit": 1}
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
    # Unknown provider -> no thinking parameter reaches the wire at all. It used
    # to be pinned to False here, which reads the same but is not: an explicit
    # false switches thinking OFF on models that have it on natively.
    assert "enable_thinking" not in cfg.generation_config.extra_body


def test_user_thinking_param_overrides_provider_default_off():
    """A non-Qwen provider defaults to sending no thinking parameter, but an
    explicit user thinking param (per-provider thinking control) must win and
    survive the drop (#5)."""
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

    # Without the user param the key would be dropped entirely; it wins here.
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
