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
    """Stand in for the client a live chat session owns.

    Both entry points are swapped: ``_live_mem0`` (what reads borrow) and
    ``_mem0_for`` (what deletes go through)."""
    import contextlib

    fake = _FakeMem0()
    fake.pid = vector_project.id

    @contextlib.contextmanager
    def _for(_proj):
        yield fake

    monkeypatch.setattr(M, "_live_mem0", lambda _proj: fake)
    monkeypatch.setattr(M, "_mem0_for", _for)
    monkeypatch.setattr(M, "_invalidate_live", lambda _proj: None)
    return fake


def test_list_maps_mem0_rows_to_items_newest_first(fake_mem0, vector_project):
    """Newest first — mem0/qdrant hand rows back in point-UUID order, which is
    arbitrary to a reader, and since mem0 2.x only ever ADDs, a superseded
    memory sits right next to the one that replaced it."""
    fake_mem0.rows = [
        {"id": "uuid-1", "memory": "prefers concise Chinese",
         "updated_at": "2026-08-06T04:53:21+00:00"},
        {"id": "uuid-2", "memory": "develops on macOS",
         "created_at": "2026-08-06T04:53:22+00:00"},
    ]
    items = asyncio.run(M.list_items(vector_project.id))
    assert [i.id for i in items] == ["uuid-2", "uuid-1"]
    assert items[1].content == "prefers concise Chinese"
    # created_at stands in when the row has no updated_at.
    assert items[0].updated_at is not None


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
    # The rebuild materializes the embedder before touching anything (for a
    # real local model that is the first-use download); these tests use a fake
    # model name, so the preflight has nothing to load.
    monkeypatch.setattr(C, "ensure_embedder_usable", lambda desc: None)
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


# ── rebuild = re-embedding migration ──────────────────────────────────────
# Changing the embedding model invalidates the vectors, not the memories: their
# text is in the store's payload. The old behaviour opened an empty store and
# left the entries in a backup nobody reads, which is data loss in every sense
# the user cares about.

def _mismatched_store(monkeypatch, vector_project, rows=None):
    """A project whose store was built by ``old-model`` while the configured
    embedder is now ``new-model`` — the state the rebuild button exists for.

    Returns ``(sdk_proj, mem_dir, written)``, where ``written`` records the rows
    handed to the re-embedding step (faked: a real one loads an embedder).
    """
    from app.backends.ms_agent.common import pm
    from ms_agent.project.paths import memory_dir

    sdk_proj = pm().get(vector_project.id)
    mem_dir = Path(str(memory_dir(sdk_proj.path)))
    (mem_dir / "qdrant").mkdir(parents=True)
    (mem_dir / "qdrant" / "meta.json").write_text("{}")
    (mem_dir / "ingest_state.json").write_text('{"hashes": ["x"]}')
    monkeypatch.setattr(C, "_probe_embed_dimension", lambda desc: (384, False))
    # The rebuild materializes the embedder before touching anything (for a
    # real local model that is the first-use download); these tests use a fake
    # model name, so the preflight has nothing to load.
    monkeypatch.setattr(C, "ensure_embedder_usable", lambda desc: None)
    C._resolve_embedder_identity(
        sdk_proj, {"mode": "local", "provider": None, "model": "old-model"})
    monkeypatch.setattr(
        C, "_resolve_embedder",
        lambda s, m: {"mode": "local", "provider": None, "model": "new-model",
                      "fallback_reason": None})

    stored = rows if rows is not None else [
        {"id": "uuid-1", "payload": {"data": "prefers concise Chinese"}},
        {"id": "uuid-2", "payload": {"data": "develops on macOS"}},
    ]
    monkeypatch.setattr(M, "_read_store_rows", lambda store: list(stored))
    written: dict = {}

    def _write(options, given):
        written["rows"] = list(given)
        written["path"] = options["vector_store"]["config"]["path"]
        Path(written["path"]).mkdir(parents=True, exist_ok=True)
        (Path(written["path"]) / "meta.json").write_text('{"new": true}')
        return len(given)

    monkeypatch.setattr(M, "_write_rows", _write)
    return sdk_proj, mem_dir, written


def test_rebuild_carries_entries_into_the_new_store(monkeypatch, vector_project):
    sdk_proj, mem_dir, written = _mismatched_store(monkeypatch, vector_project)

    result = asyncio.run(M.rebuild(vector_project.id))

    assert result.migrated == 2 and result.reused is False
    # Re-embedded into a staging dir, then swapped in.
    assert [r["id"] for r in written["rows"]] == ["uuid-1", "uuid-2"]
    assert "qdrant.new-" in written["path"]
    assert (mem_dir / "qdrant" / "meta.json").read_text() == '{"new": true}'
    backups = list(mem_dir.glob("qdrant.bak-*"))
    assert len(backups) == 1  # old store moved aside, never deleted
    assert (backups[0] / "meta.json").read_text() == "{}"
    assert not list(mem_dir.glob("qdrant.new-*"))  # nothing left behind
    # The identity is recorded only now that those vectors actually exist.
    assert C._load_embedder_identity(sdk_proj)["model"] == "new-model"
    # The memories came along, so re-ingesting the session would duplicate them.
    assert (mem_dir / "ingest_state.json").exists()


def test_rebuild_reuses_a_store_that_already_matches(monkeypatch, vector_project):
    """Switching away and back again must not cost the store.

    Two rebuilds in a row (GLM, then back to the original model) is exactly how
    a user loses everything when a rebuild means "start empty".
    """
    from app.backends.ms_agent.common import pm
    from ms_agent.project.paths import memory_dir

    sdk_proj = pm().get(vector_project.id)
    mem_dir = Path(str(memory_dir(sdk_proj.path)))
    (mem_dir / "qdrant").mkdir(parents=True)
    (mem_dir / "qdrant" / "meta.json").write_text("{}")
    monkeypatch.setattr(C, "_probe_embed_dimension", lambda desc: (384, False))
    # The rebuild materializes the embedder before touching anything (for a
    # real local model that is the first-use download); these tests use a fake
    # model name, so the preflight has nothing to load.
    monkeypatch.setattr(C, "ensure_embedder_usable", lambda desc: None)
    desc = {"mode": "local", "provider": None, "model": "same-model",
            "fallback_reason": None}
    C._resolve_embedder_identity(sdk_proj, desc)
    monkeypatch.setattr(C, "_resolve_embedder", lambda s, m: dict(desc))
    monkeypatch.setattr(
        M, "_read_store_rows",
        lambda store: pytest.fail("a matching store must not be re-read"))

    result = asyncio.run(M.rebuild(vector_project.id))

    assert result.reused is True and result.migrated == 0
    assert not list(mem_dir.glob("qdrant.bak-*"))
    assert (mem_dir / "qdrant" / "meta.json").exists()


def test_rebuild_of_an_empty_store_backs_the_ledger_up(monkeypatch, vector_project):
    """Nothing carried over → the ledger's "already ingested" claim is void, so
    it is set aside (kept, not deleted) and the next turn re-ingests."""
    sdk_proj, mem_dir, _ = _mismatched_store(monkeypatch, vector_project, rows=[])

    result = asyncio.run(M.rebuild(vector_project.id))

    assert result.migrated == 0 and result.reused is False
    assert len(list(mem_dir.glob("qdrant.bak-*"))) == 1
    assert not (mem_dir / "ingest_state.json").exists()
    assert len(list(mem_dir.glob("ingest_state.json.bak-*"))) == 1
    assert C._load_embedder_identity(sdk_proj)["model"] == "new-model"


def test_rebuild_failure_leaves_everything_as_it_was(monkeypatch, vector_project):
    """Re-embedding hits the provider (quota, revoked key, wrong dimension). On
    failure the project must be exactly as before — still mismatched, still one
    click from another attempt — never half-migrated."""
    sdk_proj, mem_dir, _ = _mismatched_store(monkeypatch, vector_project)

    def _boom(options, rows):
        Path(options["vector_store"]["config"]["path"]).mkdir(parents=True)
        raise RuntimeError("Free quota exhausted")

    monkeypatch.setattr(M, "_write_rows", _boom)

    with pytest.raises(BadRequest):
        asyncio.run(M.rebuild(vector_project.id))

    assert (mem_dir / "qdrant" / "meta.json").read_text() == "{}"
    assert not list(mem_dir.glob("qdrant.bak-*"))
    assert not list(mem_dir.glob("qdrant.new-*"))  # staging cleaned up
    assert C._load_embedder_identity(sdk_proj)["model"] == "old-model"
    assert (mem_dir / "ingest_state.json").exists()


def test_rebuild_refuses_to_run_twice_at_once(monkeypatch, vector_project):
    from app.backends.errors import Conflict

    _mismatched_store(monkeypatch, vector_project)
    M._REBUILD_LOCKS.clear()  # asyncio locks bind to the loop that takes them

    async def main():
        lock = M._rebuild_lock(vector_project.id)
        await lock.acquire()
        try:
            with pytest.raises(Conflict):
                await M.rebuild(vector_project.id)
        finally:
            lock.release()

    asyncio.run(main())


def test_status_reports_a_rebuild_in_flight(vector_project):
    """Mid-rebuild the identity file still names the OLD model while the new
    vectors are in staging — reporting either as fact would be a lie."""
    M._REBUILDING.add(vector_project.id)
    try:
        status = M.get_status(vector_project.id)
    finally:
        M._REBUILDING.discard(vector_project.id)
    assert status.rebuilding is True and status.error is None


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


# ── config changes reaching a live runtime ─────────────────────────────────
# An agent freezes its whole configuration (and its store client) at build
# time, so without this a saved change keeps being ignored for as long as a
# runtime stays alive — up to the idle TTL. That is what "changing the recall
# size does nothing" actually was.

@pytest.fixture
def dropped(monkeypatch):
    from app.backends.ms_agent.runtime import registry

    calls: list[str] = []
    monkeypatch.setattr(registry, "discard_project",
                        lambda pid: calls.append(pid) or 0)
    return calls


def _group(**over):
    from app.schemas.project import ProjectUpdate

    base = dict(memory_llm_provider_id="zhipu", memory_llm_model="glm-5",
                memory_embed_mode="local", memory_embed_provider_id=None,
                memory_embed_model=None, memory_recall_top_k=10)
    base.update(over)
    return ProjectUpdate(**base)


def test_changing_the_memory_group_drops_live_runtimes(dropped):
    proj = P.create_project(ProjectCreate(name="recall-change"))
    try:
        P.update_project(proj.id, _group())
        dropped.clear()  # the first save is a change too
        P.update_project(proj.id, _group(memory_recall_top_k=3))
        assert dropped == [proj.id]
    finally:
        P.delete_project(proj.id)


def test_resaving_the_same_group_leaves_runtimes_alone(dropped):
    """The edit modal submits the whole shape on every save, so an unchanged
    group must not cost the user their live session's agent."""
    proj = P.create_project(ProjectCreate(name="recall-resave"))
    try:
        P.update_project(proj.id, _group())
        dropped.clear()
        P.update_project(proj.id, _group())
        assert dropped == []
    finally:
        P.delete_project(proj.id)


def test_toggling_memory_drops_live_runtimes(dropped):
    from app.schemas.project import ProjectUpdate

    proj = P.create_project(ProjectCreate(name="mem-toggle",
                                          memory_enabled=False))
    try:
        P.update_project(proj.id, ProjectUpdate(memory_enabled=True))
        assert dropped == [proj.id]
        dropped.clear()
        P.update_project(proj.id, ProjectUpdate(name="mem-toggle-renamed"))
        assert dropped == []
    finally:
        P.delete_project(proj.id)


def test_discard_project_closes_idle_runtimes_and_releases_the_store():
    """The implementation behind the hook above — untested until now, and the
    live PATCHes never reached it (it returns early when nothing is live).

    Idle runtimes of that project are closed (which is what releases the shared
    embedded store), an in-flight turn is left alone, other projects untouched.
    """
    from app.backends.ms_agent.runtime import RuntimeRegistry

    class FakeRT:
        def __init__(self, pid, sid):
            self.project = type("P", (), {"id": pid, "path": "/tmp/" + pid})()
            self.session = type("S", (), {"id": sid})()
            self.turn_lock = asyncio.Lock()
            self.closed = False

        async def aclose(self):
            self.closed = True

    async def main():
        reg = RuntimeRegistry()
        idle, busy, other = FakeRT("p1", "s1"), FakeRT("p1", "s2"), FakeRT("p2", "s3")
        await busy.turn_lock.acquire()  # a turn in flight
        reg._runtimes = {"s1": idle, "s2": busy, "s3": other}
        released: list[str] = []

        async def _release(project):
            released.append(project.id)

        reg._release_project_memory = _release
        dropped = await reg._discard_project("p1")
        return dropped, reg, idle, busy, other, released

    dropped, reg, idle, busy, other, released = asyncio.run(main())
    assert dropped == 1
    assert idle.closed and "s1" not in reg._runtimes  # closed AND forgotten
    assert busy.closed is False and other.closed is False
    assert set(reg._runtimes) == {"s2", "s3"}
    assert released == ["p1"]


# ── the embedder never follows a GLOBAL setting ────────────────────────────
# The conversation provider is global, so an embedder that follows it changes
# under a project whenever the user switches models while chatting in another
# one — which invalidates this project's store and asks for a re-embed nobody
# wanted. The UI dropped the "follow" option; these pin the behaviour for
# projects saved before it did.

def _stub_project(tmp_path, pid):
    return type("P", (), {"id": pid, "path": str(tmp_path)})()


def _pin_store_to(proj, provider, model):
    C._store_embedder_identity(
        proj, {"provider": provider, "model": model, "dimension": 384,
               "pass_dimensions": False})


def test_a_store_pins_the_provider_when_none_was_saved(tmp_path):
    from app.backends.ms_agent import sidecar

    proj = _stub_project(tmp_path, "pin-provider")
    sidecar.put("projects", proj.id, {
        "memory_models": {"embed_mode": "provider", "embed_provider_id": None}})
    _pin_store_to(proj, "zhipu", "embedding-3")

    cfg = C._project_memory_models(proj)
    assert cfg["embed_provider_id"] == "zhipu"

    # Chatting elsewhere switched the conversation provider to deepseek.
    settings = _settings_with(
        "deepseek",
        deepseek={"api_key": "d", "base_url": "https://api.deepseek.com/v1"},
        zhipu={"api_key": "z", "base_url": "https://zhipu.example/v4"})
    desc = C._resolve_embedder(settings, cfg)
    assert (desc["provider"], desc["model"]) == ("zhipu", "embedding-3")


def test_a_store_built_locally_stays_local(monkeypatch, tmp_path):
    """The nastier half: a project that fell back to the local model would flip
    to a provider as soon as one that CAN embed became the conversation
    provider — same invalidation, from the opposite direction."""
    from app.backends.ms_agent import sidecar

    monkeypatch.setattr(C, "_local_embed_available", lambda: True)
    proj = _stub_project(tmp_path, "pin-local")
    sidecar.put("projects", proj.id, {
        "memory_models": {"embed_mode": "provider", "embed_provider_id": None}})
    _pin_store_to(proj, "local", C._LOCAL_EMBED_MODEL)

    cfg = C._project_memory_models(proj)
    assert cfg["embed_mode"] == "local"

    settings = _settings_with(
        "zhipu", zhipu={"api_key": "z", "base_url": "https://zhipu.example/v4"})
    assert C._resolve_embedder(settings, cfg)["mode"] == "local"


def test_an_explicit_provider_is_left_alone(tmp_path):
    from app.backends.ms_agent import sidecar

    proj = _stub_project(tmp_path, "explicit-provider")
    sidecar.put("projects", proj.id, {
        "memory_models": {"embed_mode": "provider",
                          "embed_provider_id": "dashscope"}})
    _pin_store_to(proj, "zhipu", "embedding-3")  # must NOT win
    assert C._project_memory_models(proj)["embed_provider_id"] == "dashscope"


# ── backups: at most one per embedding model ───────────────────────────────
# A rebuild always carries every entry forward, so the previous backup for the
# SAME model is a strict subset of what is being retired — keeping it costs disk
# for nothing. (A provider store is ~4x a local one; a few thousand memories
# turn each switch into tens of MB.)

def _switch_embedder_to(monkeypatch, model):
    monkeypatch.setattr(
        C, "_resolve_embedder",
        lambda s, m: {"mode": "local", "provider": None, "model": model,
                      "fallback_reason": None})


def _backup_names(mem_dir):
    return {p.name for p in mem_dir.glob("qdrant.bak-*") if p.is_dir()}


def _backup_for(model, provider=None):
    """The backup directory name a local store built by ``model`` retires to.

    Derived, never hardcoded: the name carries a digest of the full identity so
    two models whose readable part collides cannot share (and delete) one
    backup."""
    return "qdrant.bak-" + M._embedder_slug(
        {"provider": provider or "local", "model": model})


def test_rebuild_keeps_one_backup_per_embedder(monkeypatch, vector_project):
    _, mem_dir, _ = _mismatched_store(monkeypatch, vector_project)

    asyncio.run(M.rebuild(vector_project.id))  # old-model -> new-model
    assert _backup_names(mem_dir) == {_backup_for("old-model")}

    # Switching back retires the new-model store: a second backup, for the
    # other model.
    _switch_embedder_to(monkeypatch, "old-model")
    asyncio.run(M.rebuild(vector_project.id))
    assert _backup_names(mem_dir) == {_backup_for("old-model"),
                                      _backup_for("new-model")}

    # Switching yet again REPLACES that model's backup instead of piling up.
    _switch_embedder_to(monkeypatch, "new-model")
    asyncio.run(M.rebuild(vector_project.id))
    assert _backup_names(mem_dir) == {_backup_for("old-model"),
                                      _backup_for("new-model")}


def test_backup_records_which_model_built_it(monkeypatch, vector_project):
    """Named by embedder, and self-describing: the identity goes into the
    directory, so a backup is still attributable if the naming ever changes."""
    import json

    _, mem_dir, _ = _mismatched_store(monkeypatch, vector_project)
    asyncio.run(M.rebuild(vector_project.id))
    marker = mem_dir / _backup_for("old-model") / "embedder.json"
    assert json.loads(marker.read_text(encoding="utf-8"))["model"] == "old-model"


def test_legacy_timestamped_backups_collapse_to_the_newest(monkeypatch,
                                                           vector_project):
    """Backups from before per-embedder naming carry no record of their model,
    so they cannot be grouped: keep the newest as a last-resort copy, drop the
    rest instead of leaving every past switch on disk forever."""
    import os

    _, mem_dir, _ = _mismatched_store(monkeypatch, vector_project)
    for name, mtime in (("qdrant.bak-20260101-000000", 1_700_000_000),
                        ("qdrant.bak-20260102-000000", 1_700_001_000),
                        ("qdrant.bak-20260103-000000", 1_700_002_000)):
        (mem_dir / name).mkdir()
        os.utime(mem_dir / name, (mtime, mtime))

    asyncio.run(M.rebuild(vector_project.id))

    names = _backup_names(mem_dir)
    assert _backup_for("old-model") in names  # this rebuild's own
    assert {n for n in names if n.startswith("qdrant.bak-2026")} == {
        "qdrant.bak-20260103-000000"}


def test_listing_never_builds_an_embedder(monkeypatch, vector_project):
    """Listing needs payload text and timestamps — nothing that requires
    embedding anything. Going through mem0 for it built a client and loaded the
    embedding model on every request: ~800ms in steady state, measured, on the
    endpoint the memory card polls."""
    monkeypatch.setattr(M, "_live_mem0", lambda _proj: None)  # no live session

    def _boom(_proj):
        raise AssertionError("a read must not construct a mem0 client")

    monkeypatch.setattr(M, "_mem0_for", _boom)
    assert asyncio.run(M.list_items(vector_project.id)) == []


def test_listing_reads_payloads_straight_from_the_store(monkeypatch,
                                                       vector_project):
    from app.backends.ms_agent.common import pm
    from ms_agent.project.paths import memory_dir

    sdk_proj = pm().get(vector_project.id)
    (Path(str(memory_dir(sdk_proj.path))) / "qdrant").mkdir(parents=True)
    monkeypatch.setattr(M, "_live_mem0", lambda _proj: None)
    monkeypatch.setattr(M, "_read_store_rows", lambda store: [
        {"id": "a", "payload": {"data": "older", "user_id": vector_project.id,
                                "updated_at": "2026-08-01T00:00:00+00:00"}},
        {"id": "b", "payload": {"data": "newer", "user_id": vector_project.id,
                                "updated_at": "2026-08-09T00:00:00+00:00"}},
        # Another namespace in the same collection is not this project's.
        {"id": "c", "payload": {"data": "someone else", "user_id": "other"}},
    ])
    items = asyncio.run(M.list_items(vector_project.id))
    assert [i.content for i in items] == ["newer", "older"]


# ── a rebuild must not leave agents holding a retired store ────────────────
# Closing a shared orchestrator retires it for good (the SDK refuses to reopen
# an embedded store behind its owner's back), so any agent still holding one
# keeps running with memory that silently does nothing.

class _FakeRuntime:

    def __init__(self, pid, sid):
        self.project = type("P", (), {"id": pid, "path": "/tmp/" + pid})()
        self.session = type("S", (), {"id": sid})()
        self.turn_lock = asyncio.Lock()
        self.run_task = type("T", (), {"done": lambda self: False})()
        self.needs_rebuild = False
        self.closed = False
        self.model_key = None

    def touch(self):
        pass

    async def aclose(self):
        self.closed = True


def test_rebuild_retires_the_projects_runtimes_first(monkeypatch, vector_project):
    from app.backends.ms_agent.runtime import registry

    _mismatched_store(monkeypatch, vector_project)
    idle = _FakeRuntime(vector_project.id, "s-idle")
    other = _FakeRuntime("someone-else", "s-other")
    monkeypatch.setitem(registry._runtimes, "s-idle", idle)
    monkeypatch.setitem(registry._runtimes, "s-other", other)

    async def _release(project):
        pass

    monkeypatch.setattr(registry, "_release_project_memory", _release)

    asyncio.run(M.rebuild(vector_project.id))

    assert idle.closed and "s-idle" not in registry._runtimes
    assert not other.closed and "s-other" in registry._runtimes


def test_rebuild_refuses_while_a_turn_is_running(monkeypatch, vector_project):
    """A turn in flight cannot be served across a rebuild: the store it
    retrieves from is about to be replaced and the shared instance it holds gets
    retired. Refuse rather than let that turn silently lose its memory."""
    from app.backends.errors import Conflict
    from app.backends.ms_agent.runtime import registry

    _, mem_dir, _ = _mismatched_store(monkeypatch, vector_project)
    busy = _FakeRuntime(vector_project.id, "s-busy")

    async def main():
        await busy.turn_lock.acquire()
        monkeypatch.setitem(registry._runtimes, "s-busy", busy)
        try:
            with pytest.raises(Conflict):
                await M.rebuild(vector_project.id)
        finally:
            busy.turn_lock.release()

    asyncio.run(main())

    # Nothing touched, and the turn kept its agent.
    assert (mem_dir / "qdrant" / "meta.json").read_text() == "{}"
    assert not _backup_names(mem_dir)
    assert not busy.closed and "s-busy" in registry._runtimes


def test_a_flagged_runtime_is_rebuilt_on_the_next_turn(tmp_path, monkeypatch):
    """The other half: `get()` used to look only at the conversation model, so
    a flagged runtime kept serving the old configuration anyway."""
    from app.backends.ms_agent import runtime as R
    from app.backends.ms_agent import session_models

    monkeypatch.setenv("MS_AGENT_HOME", str(tmp_path))
    snapshot = session_models.ModelSnapshot(("openai", "unused"), {}, {})
    monkeypatch.setattr(session_models, "prepare", lambda project, session:
                        (session, snapshot))
    reg = R.RuntimeRegistry()
    monkeypatch.setattr(reg, "_ensure_sweeper", lambda: None)
    stale = _FakeRuntime("p1", "s1")
    stale.project.path = str(tmp_path / "workspace")
    stale.model_key = snapshot.key
    stale.settings_fingerprint = R._settings_fingerprint(stale.project, snapshot)
    stale.mcp_fingerprint = R._mcp_fingerprint(stale.project)
    reg._runtimes["s1"] = stale
    built = []

    def _fake_runtime(project, session, mcp, model_snapshot=None):
        built.append(session.id)
        return _FakeRuntime("p1", session.id)

    monkeypatch.setattr(R, "SessionRuntime", _fake_runtime)

    async def _mcp(project):
        return {}

    monkeypatch.setattr(reg, "_resolve_mcp", _mcp)

    async def check():
        assert await reg.get(stale.project, stale.session) is stale
        assert not built and not stale.closed
        stale.needs_rebuild = True
        got = await reg.get(stale.project, stale.session)
        assert built == ["s1"] and got is not stale and stale.closed

    asyncio.run(check())


def test_identity_that_cannot_be_written_aborts_before_moving_anything(
        monkeypatch, vector_project):
    """A store that speaks model B under an identity file still naming model A
    reads as a permanent mismatch — and pins the project to the wrong model. So
    the write is proven possible BEFORE anything moves."""
    _, mem_dir, _ = _mismatched_store(monkeypatch, vector_project)

    def _no_write(project, identity):
        raise OSError("read-only file system")

    monkeypatch.setattr(C, "_stage_embedder_identity", _no_write)

    with pytest.raises(BadRequest):
        asyncio.run(M.rebuild(vector_project.id))

    from app.backends.ms_agent.common import pm

    assert (mem_dir / "qdrant" / "meta.json").read_text() == "{}"  # untouched
    assert not _backup_names(mem_dir)
    assert C._load_embedder_identity(
        pm().get(vector_project.id))["model"] == "old-model"


# ── races and rollbacks around retiring runtimes / swapping stores ──────────

def test_discard_never_closes_a_runtime_that_just_became_busy():
    """Idleness has to be decided under the create lock, right before removal:
    a turn can start between any two awaits, and dropping it then cancels an
    answer mid-generation."""
    from app.backends.ms_agent.runtime import RuntimeRegistry

    async def main():
        reg = RuntimeRegistry()
        first = _FakeRuntime("p1", "s1")
        second = _FakeRuntime("p1", "s2")
        reg._runtimes = {"s1": first, "s2": second}

        async def _release(project):
            pass

        reg._release_project_memory = _release
        closing = first.aclose

        async def close_then_start_a_turn():
            await closing()
            await second.turn_lock.acquire()  # the next turn begins right here

        first.aclose = close_then_start_a_turn
        dropped = await reg._discard_project("p1")
        second.turn_lock.release()
        return dropped, first, second

    dropped, first, second = asyncio.run(main())
    assert first.closed and dropped == 1
    assert not second.closed          # the turn was not cancelled
    assert second.needs_rebuild is True  # ...it rebuilds on its next turn
    assert "s2" in second.session.id


def test_a_queued_turn_does_not_run_on_a_superseded_runtime(monkeypatch):
    """The second request may already be waiting on the turn lock when the
    config changes. `registry.get` cannot rebuild a busy runtime, so the check
    has to happen again AFTER the wait — otherwise that request runs on the old
    agent (old config, or a memory instance that has been retired)."""
    from app.backends.ms_agent import chat as CH

    built = []

    class Reg:

        def __init__(self, rt):
            self._runtimes = {rt.session.id: rt}

        async def get(self, project, session):
            rt = self._runtimes.get(session.id)
            # Same rebuild rule as the real registry: no mapping, or an idle
            # runtime that was flagged.
            if rt is None or (not rt.turn_lock.locked() and rt.needs_rebuild):
                fresh = _FakeRuntime("p1", session.id)
                self._runtimes[session.id] = fresh
                built.append(fresh)
                return fresh
            return rt

        def peek_exact(self, sid):
            return self._runtimes.get(sid)

        async def close(self, sid):
            rt = self._runtimes.pop(sid, None)
            if rt is not None:
                await rt.aclose()

    async def main():
        old = _FakeRuntime("p1", "s1")
        reg = Reg(old)
        monkeypatch.setattr(CH, "registry", reg)
        await old.turn_lock.acquire()  # turn 1 in flight
        queued = asyncio.create_task(
            CH._acquire_live_runtime(old.project, old.session))
        await asyncio.sleep(0.05)  # the request is now waiting on the lock
        old.needs_rebuild = True  # ...and the config changes
        old.turn_lock.release()  # turn 1 ends
        got = await queued
        got.turn_lock.release()
        return got, old

    got, old = asyncio.run(main())
    assert got is not old and built and got is built[0]
    assert old.closed  # retired rather than left around


def test_backup_names_cannot_collide_across_models():
    """Two models whose readable part is identical must not share a backup
    directory — the second retirement would delete the first one's copy."""
    a = M._embedder_slug({"provider": "openai", "model": "openai/org-a/embed-large"})
    b = M._embedder_slug({"provider": "openai", "model": "openai/org-b/embed-large"})
    long_a = M._embedder_slug({"provider": "x", "model": "m" * 100 + "-v1"})
    long_b = M._embedder_slug({"provider": "x", "model": "m" * 100 + "-v2"})
    assert a != b and long_a != long_b
    # ...while the same identity still maps to one stable name.
    assert a == M._embedder_slug(
        {"provider": "openai", "model": "openai/org-a/embed-large"})


def test_a_backup_claiming_another_model_is_not_deleted(monkeypatch,
                                                       vector_project):
    import json

    _, mem_dir, _ = _mismatched_store(monkeypatch, vector_project)
    squatter = mem_dir / _backup_for("old-model")
    squatter.mkdir()
    (squatter / "embedder.json").write_text(
        json.dumps({"provider": "local", "model": "someone-else"}),
        encoding="utf-8")

    asyncio.run(M.rebuild(vector_project.id))

    assert json.loads((squatter / "embedder.json").read_text())[
        "model"] == "someone-else"  # left alone
    assert any(n.startswith("qdrant.bak-2026") for n in _backup_names(mem_dir))


def test_a_failed_swap_puts_the_previous_store_back(monkeypatch, vector_project):
    """Losing the live store is the one outcome a rebuild must never produce."""
    import shutil

    _, mem_dir, _ = _mismatched_store(monkeypatch, vector_project)
    real_move = shutil.move

    def flaky(src, dst):
        if "qdrant.new-" in str(src):
            raise OSError("simulated: cannot move the new store into place")
        return real_move(src, dst)

    monkeypatch.setattr(shutil, "move", flaky)

    with pytest.raises(BadRequest):
        asyncio.run(M.rebuild(vector_project.id))

    monkeypatch.undo()
    assert (mem_dir / "qdrant" / "meta.json").read_text() == "{}"  # restored
    assert not _backup_names(mem_dir)
    assert not list(mem_dir.glob("qdrant.new-*"))


def test_rebuild_fails_before_touching_anything_when_the_local_model_is_unusable(
        monkeypatch, vector_project):
    """The local embedder is downloaded on first use (~220 MB). When that fails
    the rebuild must say so and stop BEFORE the destructive part: previously the
    error surfaced from inside the re-embedding step as a bare
    ``[Errno 60] Operation timed out``, after the project's runtimes had already
    been retired for a rebuild that could not proceed."""
    from app.backends.ms_agent.runtime import registry

    _, mem_dir, _ = _mismatched_store(monkeypatch, vector_project)

    def _boom(desc):
        raise C.MemoryConfigError(
            "local_model_unavailable",
            "the local embedding model (x) could not be loaded: "
            "[Errno 60] Operation timed out. It is downloaded on first use "
            "(~220 MB) — check the network/proxy to huggingface.co and try again")

    monkeypatch.setattr(C, "ensure_embedder_usable", _boom)
    retired: list[str] = []

    async def _record(project_id):
        retired.append(project_id)
        return 0

    monkeypatch.setattr(registry, "_discard_project", _record)

    with pytest.raises(BadRequest) as err:
        asyncio.run(M.rebuild(vector_project.id))

    assert "downloaded on first use" in str(err.value)
    assert "local embedding model" in str(err.value)
    # Nothing was retired and the store is exactly as it was.
    assert retired == []
    assert (mem_dir / "qdrant" / "meta.json").exists()
    assert not list(mem_dir.glob("qdrant.new-*"))
