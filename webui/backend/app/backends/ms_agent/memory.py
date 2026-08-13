"""Per-project memory items over the SDK's unified memory.

- ``memory_backend="file"``: items are the entry lines of
  ``<project.path>/.ms_agent/memory/MEMORY.md`` — the same store the chat
  runtime's FileBasedBackend injects and the agent's ``memory`` tool edits.
  Ids are content hashes (the file has no per-entry ids); ``updated_at`` is
  the file mtime.
- ``memory_backend="vector"``: items are mem0 memories (user_id = project id,
  embedded local qdrant under the project memory dir). UI writes use
  ``infer=False`` so a note is stored verbatim; the agent's conversational
  ingestion (fact extraction) shares the same store. The live chat runtime's
  mem0 instance is reused when present — embedded qdrant is single-client.

Guards on every entry point: the project must exist and have memory enabled.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.backends.errors import BadRequest, NotFound
from app.schemas.memory import (
    MemoryDoc,
    MemoryDocUpdate,
    MemoryItem,
    MemoryItemCreate,
    MemoryItemUpdate,
)


def _guard(pid: str):
    from app.backends.ms_agent.common import pm

    proj = pm().get(pid)
    if proj is None:
        raise NotFound("project not found")
    if not proj.memory_enabled:
        raise BadRequest("memory is disabled for this project")
    return proj


def _storage(proj):
    from ms_agent.memory.unified.config import MemoryConfig
    from ms_agent.memory.unified.storage.file_storage import FileMemoryStorage
    from ms_agent.project.paths import memory_dir

    cfg = MemoryConfig(base_dir=str(memory_dir(proj.path)))
    return FileMemoryStorage(cfg)


def _invalidate_live(proj) -> None:
    """Drop the snapshot/content cache of any live agent sharing this store, so
    a UI edit is visible to the next turn without a runtime rebuild."""
    from ms_agent.memory.memory_manager import SharedMemoryManager
    from ms_agent.project.paths import memory_dir

    target = Path(str(memory_dir(proj.path)))
    for mem in list(SharedMemoryManager._instances.values()):
        base = getattr(getattr(mem, "mem_config", None), "base_dir", None)
        if base and Path(str(base)) == target and hasattr(mem, "invalidate_snapshot"):
            mem.invalidate_snapshot()


def _is_vector(proj) -> bool:
    return (getattr(proj, "memory_backend", None) or "file") == "vector"


def _mem0_result_list(res) -> list[dict]:
    if isinstance(res, dict):
        res = res.get("results", [])
    return list(res or [])


# mem0 2.x's get_all defaults to top_k=20, which silently truncates a notes
# list. 1000 covers any store a person will actually accumulate; if one ever
# exceeds it, list_items logs so the truncation is at least visible.
_MEM0_LIST_LIMIT = 1000


def _mem0_get_all(m0, pid: str) -> list[dict]:
    """mem0 2.x: filters= + top_k; 1.x: user_id kwarg."""
    try:
        res = m0.get_all(filters={"user_id": pid}, top_k=_MEM0_LIST_LIMIT)
    except TypeError:
        res = m0.get_all(user_id=pid)
    rows = _mem0_result_list(res)
    if len(rows) >= _MEM0_LIST_LIMIT:
        import logging

        logging.getLogger("app.ms_agent.memory").warning(
            "memory list for %s hit the %d-row cap; the UI shows a truncated "
            "view", pid, _MEM0_LIST_LIMIT)
    return rows


@contextmanager
def _mem0_for(proj):
    """Yield a mem0.Memory over the project's store.

    Prefer the live chat runtime's instance (same process — embedded qdrant
    holds a file lock, so a second client on the same path would fail). Build
    a transient instance otherwise and close its vector client afterwards."""
    from ms_agent.memory.memory_manager import SharedMemoryManager
    from ms_agent.project.paths import memory_dir

    target = Path(str(memory_dir(proj.path)))
    for mem in list(SharedMemoryManager._instances.values()):
        base = getattr(getattr(mem, "mem_config", None), "base_dir", None)
        backend = getattr(mem, "_backend", None)
        live = getattr(backend, "_mem0", None)
        if base and Path(str(base)) == target and live is not None:
            yield live
            return

    from app.backends.ms_agent.config import MemoryConfigError, _mem0_options

    try:
        import mem0
    except Exception as exc:  # pragma: no cover - import guard
        raise BadRequest(f"vector memory unavailable: {exc}")
    try:
        options = _mem0_options(proj)
    except MemoryConfigError as exc:
        raise BadRequest(f"vector memory unavailable: {exc}")
    try:
        m0 = mem0.Memory.from_config(options)
    except Exception as exc:
        raise BadRequest(f"vector memory init failed: {exc}")
    try:
        yield m0
    finally:
        try:  # release the embedded qdrant lock promptly
            m0.vector_store.client.close()
        except Exception:
            pass


def _vector_item(pid: str, r: dict) -> MemoryItem:
    at = r.get("updated_at") or r.get("created_at") or _now()
    return MemoryItem(
        id=str(r.get("id") or ""),
        project_id=pid,
        content=str(r.get("memory") or r.get("text") or ""),
        updated_at=str(at),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _entry_id(line: str) -> str:
    return "mem_" + hashlib.sha1(line.encode("utf-8")).hexdigest()[:12]


def _entries(storage) -> list[str]:
    return [l.strip() for l in storage.get_content().splitlines() if l.strip()]


def _mtime(storage) -> str:
    try:
        ts = storage.memory_path.stat().st_mtime
    except OSError:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _item(pid: str, line: str, updated_at: str) -> MemoryItem:
    return MemoryItem(
        id=_entry_id(line), project_id=pid, content=line, updated_at=updated_at
    )


def _migrate_sidecar(pid: str, proj, storage) -> None:
    """One-time: fold legacy sidecar note items into MEMORY.md (pre-unified
    versions kept the UI list in webui_meta.json, invisible to the agent)."""
    from app.backends.ms_agent import sidecar

    legacy = list(sidecar.get("memory", pid, []) or [])
    if not legacy:
        return
    for item in legacy:
        content = str(item.get("content") or "").strip()
        if content:
            storage._add_entry(content)
    sidecar.drop("memory", pid)
    _invalidate_live(proj)



def _store_lock_for(proj):
    """The SDK's per-store asyncio lock for this project's memory dir.

    HTTP reads/deletes borrow the live mem0 client, so they must serialize
    against background ingestion the same way agent-side retrieval does —
    qdrant local is lock-free single-client code. Falls back to a no-op lock
    on an SDK predating the discipline."""
    import contextlib

    from ms_agent.project.paths import memory_dir

    try:
        from ms_agent.memory.unified.orchestrator import _store_lock

        return _store_lock(str(memory_dir(proj.path)))
    except Exception:  # pragma: no cover - older SDK
        @contextlib.asynccontextmanager
        async def _noop():
            yield

        return _noop()


async def list_items(pid: str) -> list[MemoryItem]:
    proj = _guard(pid)
    if _is_vector(proj):
        async with _store_lock_for(proj):
            with _mem0_for(proj) as m0:
                rows = _mem0_get_all(m0, pid)
        items = [_vector_item(pid, r) for r in rows]
        return [i for i in items if i.content]
    storage = _storage(proj)
    _migrate_sidecar(pid, proj, storage)
    at = _mtime(storage)
    # File order == MEMORY.md order (what the agent reads).
    return [_item(pid, line, at) for line in _entries(storage)]


def create_item(pid: str, body: MemoryItemCreate) -> MemoryItem:
    proj = _guard(pid)
    content = (body.content or "").strip()
    if not content:
        raise BadRequest("memory content is empty")
    if _is_vector(proj):
        # Vector memories are written by the agent's own fact extraction during
        # conversation; hand-authoring them is not offered (the UI has no such
        # affordance either). Removing a wrong one stays allowed.
        raise BadRequest(
            "vector memories are written by the agent; "
            "they cannot be created manually")
    storage = _storage(proj)
    if not storage._add_entry(content):
        raise BadRequest("memory is full (char budget) — remove entries first")
    _invalidate_live(proj)
    return _item(pid, content, _mtime(storage))


def update_item(pid: str, item_id: str, body: MemoryItemUpdate) -> MemoryItem:
    proj = _guard(pid)
    content = (body.content or "").strip()
    if not content:
        raise BadRequest("memory content is empty")
    if _is_vector(proj):
        # Read-only apart from deletion — see create_item.
        raise BadRequest(
            "vector memories are written by the agent; "
            "they cannot be edited manually")
    storage = _storage(proj)
    old = next((l for l in _entries(storage) if _entry_id(l) == item_id), None)
    if old is None:
        raise NotFound("memory item not found")
    if content != old and not storage.replace_entry(old, content):
        raise BadRequest("memory update rejected (char budget or security scan)")
    _invalidate_live(proj)
    return _item(pid, content, _mtime(storage))


async def delete_item(pid: str, item_id: str) -> None:
    proj = _guard(pid)
    if _is_vector(proj):
        async with _store_lock_for(proj):
            with _mem0_for(proj) as m0:
                try:
                    m0.delete(memory_id=item_id)
                except Exception as exc:
                    if "not found" in str(exc).lower() or isinstance(exc, IndexError):
                        raise NotFound("memory item not found")
                    raise BadRequest(f"vector memory delete failed: {exc}")
        _invalidate_live(proj)
        return
    storage = _storage(proj)
    old = next((l for l in _entries(storage) if _entry_id(l) == item_id), None)
    if old is None:
        raise NotFound("memory item not found")
    storage.remove_entry(old)
    _invalidate_live(proj)


# ── status & rebuild (vector backend health surface) ──────────────────────


def get_status(pid: str):
    """What the memory subsystem is actually doing for this project: the
    resolved embedder identity, why vector memory is unusable if it is, and
    the last ingest outcome of any live runtime. This is how config problems
    stop being silent — the card renders this instead of an empty list."""
    from app.backends.ms_agent.config import (
        MemoryConfigError,
        _load_embedder_identity,
        _local_embed_available,
        _project_memory_models,
        _read_settings,
        _resolve_embedder,
    )
    from app.schemas.memory import (
        MemoryEmbedderInfo,
        MemoryErrorInfo,
        MemoryIngestInfo,
        MemoryStatus,
    )

    proj = _guard(pid)
    if not _is_vector(proj):
        return MemoryStatus(project_id=pid, backend="file",
                            local_embed_available=_local_embed_available())

    embedder = None
    error = None
    try:
        desc = _resolve_embedder(_read_settings(), _project_memory_models(proj))
        identity = _load_embedder_identity(proj)
        current = (desc.get("provider") or "local", desc["model"])
        if identity is not None and (
                identity.get("provider"), identity.get("model")) != current:
            error = MemoryErrorInfo(
                code="embedder_mismatch",
                message=(
                    f"store built with {identity.get('provider')}/"
                    f"{identity.get('model')}, current embedder is "
                    f"{current[0]}/{current[1]}"))
            embedder = MemoryEmbedderInfo(
                mode="local" if identity.get("provider") == "local" else "provider",
                provider=identity.get("provider"),
                model=identity.get("model"),
                dimension=identity.get("dimension"))
        else:
            embedder = MemoryEmbedderInfo(
                mode=desc["mode"],
                provider=desc.get("provider"),
                model=desc["model"],
                dimension=(identity or {}).get("dimension"),
                fallback_reason=desc.get("fallback_reason"))
    except MemoryConfigError as exc:
        error = MemoryErrorInfo(code=exc.code, message=str(exc))

    ingest = None
    status = _live_ingest_status(proj)
    if status is not None:
        ingest = MemoryIngestInfo(
            state=str(status.get("state") or "idle"),
            at=status.get("at"),
            count=status.get("count"),
            error=status.get("error"),
            pending=int(status.get("pending") or 0))

    return MemoryStatus(
        project_id=pid, backend="vector", embedder=embedder, error=error,
        ingest=ingest, local_embed_available=_local_embed_available())


def _live_ingest_status(sdk_proj) -> dict | None:
    """The shared orchestrator's last ingest outcome, if one is live."""
    from ms_agent.memory.memory_manager import SharedMemoryManager
    from ms_agent.project.paths import memory_dir

    target = Path(str(memory_dir(sdk_proj.path)))
    for mem in list(SharedMemoryManager._instances.values()):
        base = getattr(getattr(mem, "mem_config", None), "base_dir", None)
        if base and Path(str(base)) == target:
            status = getattr(mem, "ingest_status", None)
            if isinstance(status, dict):
                return status
    return None


async def rebuild(pid: str):
    """Start the vector store over with the CURRENT embedder.

    The old store is moved aside (``qdrant.bak-<ts>``), never deleted — this
    is the remedy the embedder-mismatch error points at, and a remedy that
    destroys data must not be one click. The ingest ledger is cleared too, so
    the next completed turn re-ingests the session's context into the fresh
    store. Async on purpose: closing the live orchestrator must run on the
    app loop, where its pending ingest tasks live."""
    import shutil
    import time as _time

    from app.backends.ms_agent.config import _embedder_identity_path
    from ms_agent.memory.memory_manager import SharedMemoryManager
    from ms_agent.project.paths import memory_dir

    proj = _guard(pid)
    if not _is_vector(proj):
        raise BadRequest("memory rebuild only applies to the vector backend")
    mem_dir = Path(str(memory_dir(proj.path)))

    # Release the embedded store first — a live runtime holds its exclusive
    # file lock, and moving a locked qdrant dir out from under it corrupts
    # the client's view.
    await SharedMemoryManager.close_matching(str(mem_dir))

    qdrant = mem_dir / "qdrant"
    if qdrant.exists():
        backup = mem_dir / f"qdrant.bak-{_time.strftime('%Y%m%d-%H%M%S')}"
        shutil.move(str(qdrant), str(backup))
    for stale in (_embedder_identity_path(proj), mem_dir / "ingest_state.json"):
        try:
            Path(str(stale)).unlink(missing_ok=True)
        except OSError:
            pass
    return get_status(pid)


# ── file backend: the whole document ──────────────────────────────────────
# With memory_backend="file", memory IS one markdown file the agent reads
# (MEMORY.md). The UI previews/edits it as a document, so these two functions
# expose it wholesale instead of line-by-line. Vector projects have no such
# file and are rejected.

def _require_file_backend(proj):
    if _is_vector(proj):
        raise BadRequest(
            "memory document is only available for the file backend")


def get_doc(pid: str) -> MemoryDoc:
    proj = _guard(pid)
    _require_file_backend(proj)
    storage = _storage(proj)
    _migrate_sidecar(pid, proj, storage)
    return MemoryDoc(
        project_id=pid,
        content=storage.get_content(),
        updated_at=_mtime(storage),
    )


def put_doc(pid: str, body: MemoryDocUpdate) -> MemoryDoc:
    proj = _guard(pid)
    _require_file_backend(proj)
    storage = _storage(proj)
    # Go through the storage object rather than writing the path directly: this
    # document is dumped into the system prompt in full on every turn, so it has
    # to obey the same char budget and security scan the agent's own `memory`
    # tool does. full_replace() applies both (over-budget content is truncated,
    # not silently accepted). Then drop live agents' caches, as item edits do.
    path = Path(str(storage.memory_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    text = body.content or ""
    if text and not text.endswith("\n"):
        text += "\n"
    # full_replace() truncates over-budget content, which is right for the LLM
    # consolidation path it was written for but wrong here: a person pressed
    # Save, so tell them instead of quietly dropping the tail.
    if len(text) > storage.char_limit:
        raise BadRequest(
            f"memory is too long ({len(text)} chars, limit {storage.char_limit}) "
            "— it is injected into the prompt in full on every turn")
    if not storage.full_replace(text):
        raise BadRequest("memory update rejected (security scan)")
    _invalidate_live(proj)
    return MemoryDoc(
        project_id=pid, content=storage.get_content(), updated_at=_mtime(storage)
    )
