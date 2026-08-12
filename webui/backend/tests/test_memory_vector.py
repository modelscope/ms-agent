"""Vector-backend memory: config resolution and the mem0-backed item APIs.

These were the completely untested paths, and the two config bugs they now
cover both presented identically in the product -- a conversation that looks
fine while memory stays empty forever, because ``Mem0Backend.on_messages``
swallows its failures:

* the fact-extraction LLM was declared as mem0's ``openai`` provider whatever
  protocol the active model actually spoke, so an Anthropic-protocol endpoint
  (DeepSeek's ``/anthropic``) got ``/chat/completions`` posted at it and 404'd;
* mem0 opens a second, process-global qdrant store for telemetry, and embedded
  qdrant locks per path -- so the machine could only ever hold ONE live vector
  project.

Everything here is offline: the mem0 client is faked, and the config helpers
are pure functions over a settings dict.
"""
from pathlib import Path

import asyncio

import pytest

from app.backends.errors import BadRequest, NotFound
from app.backends.ms_agent import config as C
from app.backends.ms_agent import memory as M
from app.backends.ms_agent import projects as P
from app.schemas.project import ProjectCreate


# ── fact-extraction LLM resolution (pure) ─────────────────────────────────

def _settings(provider: str, protocol: str, base_url: str) -> dict:
    return {
        "llm": {
            "provider": provider,
            "model": f"{provider}-chat",
            "api_key": "k-llm",
            "base_url": base_url,
        },
        "providers": {
            provider: {
                "protocol": protocol,
                "api_key": "k-prov",
                "base_url": base_url,
            }
        },
    }


def test_openai_protocol_provider_is_used_as_is():
    block = C._mem0_llm(
        _settings("dashscope", "openai", "https://example.test/compatible/v1"))
    assert block == {
        "provider": "openai",
        "config": {
            "model": "dashscope-chat",
            "api_key": "k-llm",
            "openai_base_url": "https://example.test/compatible/v1",
        },
    }


def test_anthropic_protocol_falls_back_to_mem0_native_provider():
    """The regression that made vector memory a no-op.

    DeepSeek configured on its Anthropic endpoint must NOT be handed to mem0 as
    `openai` pointing at `/anthropic` -- mem0's DeepSeek adapter is an OpenAI
    client underneath, so it needs the vendor's OpenAI-compatible url from the
    SDK provider registry, not the one sitting in settings.json.
    """
    block = C._mem0_llm(
        _settings("deepseek", "anthropic", "https://api.deepseek.com/anthropic"))
    assert block["provider"] == "deepseek"
    assert block["config"]["model"] == "deepseek-chat"
    base = block["config"]["deepseek_base_url"]
    assert base == "https://api.deepseek.com/v1"
    assert "anthropic" not in base


def test_non_openai_vendor_without_a_native_adapter_is_declined():
    """Better no `llm` key (mem0 warns and uses its default) than a provider
    we know cannot be reached -- and never a silent mislabel."""
    assert C._mem0_llm(_settings("acme", "anthropic", "https://acme.test")) is None


@pytest.mark.parametrize("settings", [
    {},
    {"llm": {"provider": "deepseek"}},                        # no model
    {"llm": {"provider": "deepseek", "model": "m"}},          # no credentials
])
def test_incomplete_settings_yield_no_llm_block(settings):
    assert C._mem0_llm(settings) is None


# ── embedder resolution (explicit → conversation provider → local) ─────────

def _settings_with(llm_provider="zhipu", **providers):
    return {
        "llm": {"provider": llm_provider, "model": "chat-model",
                "api_key": "k", "base_url": providers.get(llm_provider, {}).get("base_url")},
        "providers": providers,
    }


def test_default_embedder_follows_the_conversation_provider():
    """No explicit choice → the provider the user already picked for chat,
    with its known embedding model. Never a silently different vendor."""
    settings = _settings_with(
        "zhipu", zhipu={"api_key": "z", "base_url": "https://zhipu.example/v4"})
    desc = C._resolve_embedder(settings, {})
    assert (desc["mode"], desc["provider"]) == ("provider", "zhipu")
    assert desc["model"] == C._KNOWN_EMBED_MODELS["zhipu"]
    assert desc["fallback_reason"] is None


def test_conversation_provider_without_embeddings_falls_back_to_local(monkeypatch):
    """The chat provider may serve no /embeddings at all (deepseek, kimi, a
    custom gateway). The default then goes LOCAL — visible in
    fallback_reason — instead of silently billing some other vendor."""
    monkeypatch.setattr(C, "_local_embed_available", lambda: True)
    settings = _settings_with(
        "deepseek", deepseek={"api_key": "d", "base_url": "https://api.deepseek.com/anthropic"})
    desc = C._resolve_embedder(settings, {})
    assert desc["mode"] == "local"
    assert desc["model"] == C._LOCAL_EMBED_MODEL
    assert "deepseek" in (desc["fallback_reason"] or "")


def test_explicit_provider_is_never_silently_switched(monkeypatch):
    """A pinned provider that cannot embed is an ERROR, not a fallback — the
    user chose it; switching behind their back is the old bug."""
    monkeypatch.setattr(C, "_local_embed_available", lambda: True)
    settings = _settings_with(
        "zhipu", zhipu={"api_key": "z", "base_url": "https://zhipu.example/v4"})
    with pytest.raises(C.MemoryConfigError) as exc:
        C._resolve_embedder(settings, {"embed_provider_id": "kimi"})
    assert exc.value.code == "embed_unavailable"


def test_explicit_local_mode_requires_the_extra(monkeypatch):
    monkeypatch.setattr(C, "_local_embed_available", lambda: False)
    with pytest.raises(C.MemoryConfigError) as exc:
        C._resolve_embedder(_settings_with(), {"embed_mode": "local"})
    assert exc.value.code == "local_missing"
    assert "local-embed" in str(exc.value)  # the message names the remedy


def test_no_provider_and_no_local_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(C, "_local_embed_available", lambda: False)
    with pytest.raises(C.MemoryConfigError) as exc:
        C._resolve_embedder({}, {})
    assert exc.value.code == "local_missing"


def test_explicit_embed_model_overrides_the_known_default():
    settings = _settings_with(
        "zhipu", zhipu={"api_key": "z", "base_url": "https://zhipu.example/v4"})
    desc = C._resolve_embedder(settings, {"embed_provider_id": "zhipu",
                                          "embed_model": "embedding-2"})
    assert desc["model"] == "embedding-2"


# ── embedder identity (recorded once, then enforced) ───────────────────────

def _proj(tmp_path):
    return type("P", (), {"id": "p", "path": str(tmp_path)})()


def test_identity_is_recorded_on_first_build(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "_probe_embed_dimension", lambda desc: (1024, True))
    proj = _proj(tmp_path)
    identity = C._resolve_embedder_identity(
        proj, {"mode": "provider", "provider": "zhipu", "model": "embedding-3",
               "api_key": "k", "base_url": "https://x/v4"})
    assert identity["dimension"] == 1024 and identity["pass_dimensions"]
    stored = C._load_embedder_identity(proj)
    assert (stored["provider"], stored["model"]) == ("zhipu", "embedding-3")


def test_identity_mismatch_refuses_instead_of_mixing_spaces(monkeypatch, tmp_path):
    """A store built with model A must not be written with model B: mixed
    vector spaces don't error, they just make recall garbage. The error names
    both models and points at the rebuild."""
    monkeypatch.setattr(C, "_probe_embed_dimension", lambda desc: (1024, True))
    proj = _proj(tmp_path)
    C._resolve_embedder_identity(
        proj, {"mode": "provider", "provider": "zhipu", "model": "embedding-3"})
    with pytest.raises(C.MemoryConfigError) as exc:
        C._resolve_embedder_identity(
            proj, {"mode": "local", "provider": None,
                   "model": C._LOCAL_EMBED_MODEL})
    assert exc.value.code == "embedder_mismatch"
    assert "zhipu/embedding-3" in str(exc.value)


def test_same_identity_skips_the_probe(monkeypatch, tmp_path):
    """The dimension probe is a network call; a recorded identity must satisfy
    later builds without re-probing."""
    proj = _proj(tmp_path)
    monkeypatch.setattr(C, "_probe_embed_dimension", lambda desc: (1024, False))
    desc = {"mode": "provider", "provider": "zhipu", "model": "embedding-3"}
    C._resolve_embedder_identity(proj, desc)

    def _explode(_desc):
        raise AssertionError("re-probed a recorded identity")

    monkeypatch.setattr(C, "_probe_embed_dimension", _explode)
    identity = C._resolve_embedder_identity(proj, desc)
    assert identity["dimension"] == 1024


def test_mem0_telemetry_is_off():
    """Not cosmetic: mem0 2.x opens a process-global ~/.mem0/migrations_qdrant
    per Memory instance, and embedded qdrant locks per path -- leaving telemetry
    on caps the whole machine at one live vector project."""
    import os

    assert os.environ["MEM0_TELEMETRY"] == "false"


# ── list / delete over a faked mem0 ───────────────────────────────────────

class _FakeMem0:
    """Enough of mem0.Memory for the adapter, in the 2.x shape (results
    envelope, `filters=` + `top_k`). The 1.x path is exercised separately."""

    def __init__(self, rows=None, legacy=False):
        self.rows = list(rows or [])
        self.legacy = legacy
        self.deleted: list[str] = []

    def get_all(self, **kwargs):
        if self.legacy:
            # 1.x rejects the 2.x kwargs, which is what drives the fallback.
            if "filters" in kwargs or "top_k" in kwargs:
                raise TypeError("unexpected keyword argument")
            return list(self.rows)          # bare list, no envelope
        assert kwargs["filters"] == {"user_id": self.pid}
        assert kwargs["top_k"] > 20, "default top_k truncates a notes list"
        return {"results": list(self.rows)}

    def delete(self, memory_id):
        if memory_id not in [r["id"] for r in self.rows]:
            raise ValueError("Memory not found")
        self.rows = [r for r in self.rows if r["id"] != memory_id]
        self.deleted.append(memory_id)


@pytest.fixture
def vector_project():
    proj = P.create_project(
        ProjectCreate(name="vec-test", memory_enabled=True,
                      memory_backend="vector"))
    yield proj
    P.delete_project(proj.id)


@pytest.fixture
def fake_mem0(monkeypatch, vector_project):
    """Swap the real client in, keeping _mem0_for's contextmanager shape."""
    import contextlib

    fake = _FakeMem0()
    fake.pid = vector_project.id

    @contextlib.contextmanager
    def _for(_proj):
        yield fake

    monkeypatch.setattr(M, "_mem0_for", _for)
    monkeypatch.setattr(M, "_invalidate_live", lambda _proj: None)
    return fake


def test_list_maps_mem0_rows_to_items(fake_mem0, vector_project):
    fake_mem0.rows = [
        {"id": "uuid-1", "memory": "prefers concise Chinese",
         "updated_at": "2026-08-06T04:53:21+00:00"},
        {"id": "uuid-2", "memory": "develops on macOS",
         "created_at": "2026-08-06T04:53:22+00:00"},
    ]
    items = asyncio.run(M.list_items(vector_project.id))
    assert [i.id for i in items] == ["uuid-1", "uuid-2"]
    assert items[0].content == "prefers concise Chinese"
    # created_at stands in when the row has no updated_at.
    assert items[1].updated_at is not None


def test_list_drops_contentless_rows(fake_mem0, vector_project):
    fake_mem0.rows = [{"id": "a", "memory": ""}, {"id": "b", "memory": "kept"}]
    assert [i.content for i in asyncio.run(M.list_items(vector_project.id))] == ["kept"]


def test_list_falls_back_to_the_1x_get_all_signature(fake_mem0, vector_project):
    fake_mem0.legacy = True
    fake_mem0.rows = [{"id": "old", "memory": "from mem0 1.x"}]
    assert [i.id for i in asyncio.run(M.list_items(vector_project.id))] == ["old"]


def test_delete_removes_by_id(fake_mem0, vector_project):
    fake_mem0.rows = [{"id": "uuid-1", "memory": "wrong fact"}]
    asyncio.run(M.delete_item(vector_project.id, "uuid-1"))
    assert fake_mem0.deleted == ["uuid-1"]
    assert asyncio.run(M.list_items(vector_project.id)) == []


def test_delete_of_an_unknown_id_is_a_404(fake_mem0, vector_project):
    with pytest.raises(NotFound):
        asyncio.run(M.delete_item(vector_project.id, "nope"))


def test_writes_are_refused_on_the_vector_backend(fake_mem0, vector_project):
    """Vector entries come from the agent's fact extraction; the UI offers no
    hand-authoring, so the API must not either (removal stays allowed)."""
    from app.schemas.memory import MemoryItemCreate, MemoryItemUpdate

    with pytest.raises(BadRequest):
        M.create_item(vector_project.id, MemoryItemCreate(content="typed by hand"))
    with pytest.raises(BadRequest):
        M.update_item(vector_project.id, "uuid-1", MemoryItemUpdate(content="edited"))


# ── live-instance reuse (the thing standing between us and a lock error) ──

def test_mem0_for_borrows_a_live_instance_instead_of_opening_a_second(
        monkeypatch, vector_project):
    """Embedded qdrant is single-client. When a chat runtime already holds the
    store, the API MUST reuse its handle -- building a transient one would
    raise "already accessed by another instance" instead of listing memories.
    """
    from app.backends.ms_agent.common import pm
    from ms_agent.memory.memory_manager import SharedMemoryManager
    from ms_agent.project.paths import memory_dir

    # _mem0_for takes the SDK project (it reads `.path`), not the API schema.
    proj = pm().get(vector_project.id)

    live = object()
    holder = type("Orchestrator", (), {})()
    holder.mem_config = type("Cfg", (), {})()
    holder.mem_config.base_dir = str(memory_dir(proj.path))
    holder._backend = type("Backend", (), {})()
    holder._backend._mem0 = live

    def _explode(*_a, **_kw):
        raise AssertionError("built a second client while one was live")

    monkeypatch.setattr(C, "_mem0_options", _explode)
    monkeypatch.setitem(SharedMemoryManager._instances, "test-live", holder)
    try:
        with M._mem0_for(proj) as m0:
            assert m0 is live
    finally:
        SharedMemoryManager._instances.pop("test-live", None)


# ── config injection ──────────────────────────────────────────────────────

def _memory_node(project, settings):
    from omegaconf import OmegaConf

    cfg = C._apply_webui_memory(OmegaConf.create({}), project)
    node = OmegaConf.select(cfg, "memory.unified_memory")
    return None if node is None else OmegaConf.to_container(node)


def test_vector_project_gets_the_mem0_storage_backend(monkeypatch, vector_project):
    monkeypatch.setattr(C, "_mem0_options", lambda _p: {"embedder": {}, "vector_store": {}})
    node = _memory_node(vector_project, None)
    assert node["storage"]["backend"] == "mem0"
    assert node["namespace"]["user_id"] == vector_project.id
    # add_after_step is what activates per-step ingestion; without it the agent
    # never calls on_messages and nothing is ever written.
    assert node["add_after_step"]["user_id"] == vector_project.id


def test_unbuildable_vector_memory_disables_memory_not_file_fallback(
        monkeypatch, vector_project):
    """A vector project whose memory cannot be built runs WITHOUT memory —
    never as a silent file fallback, which would write a MEMORY.md the vector
    UI never shows. The reason reaches the user via GET /memory/status."""

    def _raise(_p):
        raise C.MemoryConfigError("embed_unavailable", "no embedder")

    monkeypatch.setattr(C, "_mem0_options", _raise)
    assert _memory_node(vector_project, None) is None


# ── status & rebuild ───────────────────────────────────────────────────────

def test_status_for_a_file_project_is_minimal():
    proj = P.create_project(
        ProjectCreate(name="status-file", memory_enabled=True,
                      memory_backend="file"))
    try:
        status = M.get_status(proj.id)
        assert status.backend == "file"
        assert status.embedder is None and status.error is None
    finally:
        P.delete_project(proj.id)


def test_status_surfaces_the_resolution_error(monkeypatch, vector_project):
    """The whole point of /status: a config problem stops being an empty
    panel and becomes a machine-readable reason."""

    def _raise(_settings, _mem_cfg):
        raise C.MemoryConfigError("local_missing", "run uv sync --extra local-embed")

    monkeypatch.setattr(C, "_resolve_embedder", _raise)
    status = M.get_status(vector_project.id)
    assert status.backend == "vector"
    assert status.error.code == "local_missing"
    assert "local-embed" in status.error.message


def test_status_reports_identity_mismatch_with_rebuild_code(
        monkeypatch, vector_project):
    from app.backends.ms_agent.common import pm

    sdk_proj = pm().get(vector_project.id)
    monkeypatch.setattr(C, "_probe_embed_dimension", lambda desc: (384, False))
    C._resolve_embedder_identity(
        sdk_proj, {"mode": "local", "provider": None, "model": "old-model"})
    monkeypatch.setattr(
        C, "_resolve_embedder",
        lambda s, m: {"mode": "local", "provider": None, "model": "new-model",
                      "fallback_reason": None})
    status = M.get_status(vector_project.id)
    assert status.error is not None and status.error.code == "embedder_mismatch"
    # The stored identity (what the store was built with) is what's shown.
    assert status.embedder.model == "old-model"


def test_rebuild_backs_up_the_store_and_clears_identity(
        monkeypatch, vector_project):
    import asyncio

    from app.backends.ms_agent.common import pm
    from ms_agent.project.paths import memory_dir

    sdk_proj = pm().get(vector_project.id)
    mem_dir = Path(str(memory_dir(sdk_proj.path)))
    (mem_dir / "qdrant").mkdir(parents=True)
    (mem_dir / "qdrant" / "meta.json").write_text("{}")
    (mem_dir / "ingest_state.json").write_text('{"hashes": ["x"]}')
    monkeypatch.setattr(C, "_probe_embed_dimension", lambda desc: (384, False))
    C._resolve_embedder_identity(
        sdk_proj, {"mode": "local", "provider": None, "model": "old-model"})
    monkeypatch.setattr(
        C, "_resolve_embedder",
        lambda s, m: {"mode": "local", "provider": None, "model": "new-model",
                      "fallback_reason": None})

    asyncio.run(M.rebuild(vector_project.id))

    assert not (mem_dir / "qdrant").exists()
    backups = list(mem_dir.glob("qdrant.bak-*"))
    assert len(backups) == 1  # moved aside, never deleted
    assert (backups[0] / "meta.json").exists()
    assert C._load_embedder_identity(sdk_proj) is None
    assert not (mem_dir / "ingest_state.json").exists()


# ── per-project memory-model ownership ─────────────────────────────────────

def test_creation_materializes_global_defaults(monkeypatch):
    """Global settings are a factory template: copied into the project at
    creation, then never read again for it — changing a global default later
    must not touch existing projects."""
    from app.backends.ms_agent import sidecar

    sidecar.put("agent_settings", "memory_models", {
        "llm_provider_id": "zhipu", "llm_model": "glm-5",
        "embed_mode": "local", "embed_provider_id": None,
        "embed_model": None, "recall_top_k": 7,
    })
    proj = P.create_project(ProjectCreate(name="materialize-me"))
    try:
        assert proj.memory_llm_provider_id == "zhipu"
        assert proj.memory_embed_mode == "local"
        assert proj.memory_recall_top_k == 7
        # Now change the global default — the project must keep its copy.
        sidecar.put("agent_settings", "memory_models", {
            "llm_provider_id": None, "llm_model": None,
            "embed_mode": "provider", "embed_provider_id": None,
            "embed_model": None, "recall_top_k": None,
        })
        again = P.get_project(proj.id)
        assert again.memory_llm_provider_id == "zhipu"
        assert again.memory_embed_mode == "local"
    finally:
        P.delete_project(proj.id)
        sidecar.put("agent_settings", "memory_models", {})


def test_explicit_create_values_beat_global_defaults(monkeypatch):
    from app.backends.ms_agent import sidecar

    sidecar.put("agent_settings", "memory_models", {"embed_mode": "local"})
    proj = P.create_project(ProjectCreate(
        name="explicit-wins", memory_embed_mode="provider",
        memory_embed_provider_id="zhipu"))
    try:
        assert proj.memory_embed_mode == "provider"
        assert proj.memory_embed_provider_id == "zhipu"
    finally:
        P.delete_project(proj.id)
        sidecar.put("agent_settings", "memory_models", {})


def test_update_replaces_the_group_and_feeds_resolution():
    """The edit modal owns the whole group; config resolution must read the
    PROJECT's values (not the globals)."""
    from app.schemas.project import ProjectUpdate

    proj = P.create_project(ProjectCreate(name="group-replace"))
    try:
        P.update_project(proj.id, ProjectUpdate(
            memory_llm_provider_id="zhipu", memory_llm_model="glm-5",
            memory_embed_mode="local", memory_embed_provider_id=None,
            memory_embed_model=None, memory_recall_top_k=5))
        from app.backends.ms_agent.common import pm

        mem_cfg = C._project_memory_models(pm().get(proj.id))
        assert mem_cfg["llm_model"] == "glm-5"
        assert mem_cfg["embed_mode"] == "local"
        assert mem_cfg["recall_top_k"] == 5
    finally:
        P.delete_project(proj.id)


def test_legacy_project_without_group_resolves_as_follow():
    proj = P.create_project(ProjectCreate(name="legacy-like"))
    try:
        from app.backends.ms_agent import sidecar
        from app.backends.ms_agent.common import pm

        # Simulate a pre-feature project: drop the materialized group.
        meta = sidecar.get("projects", proj.id, {}) or {}
        meta.pop("memory_models", None)
        sidecar.put("projects", proj.id, meta)
        assert C._project_memory_models(pm().get(proj.id)) == {}
    finally:
        P.delete_project(proj.id)
