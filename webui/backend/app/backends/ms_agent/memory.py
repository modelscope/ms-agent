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

import asyncio
import hashlib
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.backends.errors import BadRequest, Conflict, NotFound
from app.schemas.memory import (
    MemoryDoc,
    MemoryDocUpdate,
    MemoryItem,
    MemoryItemCreate,
    MemoryItemUpdate,
)

logger = logging.getLogger("app.ms_agent.memory")


def _guard(pid: str):
    from app.backends.ms_agent.common import pm

    proj = pm().get(pid)
    if proj is None:
        raise NotFound("Project not found.")
    if not proj.memory_enabled:
        raise BadRequest("Memory is turned off for this project.")
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


# The UI list is capped so a pathological store cannot stall a render; 1000
# covers any store a person will actually accumulate. Rows are FETCHED without
# that cap and sorted by recency first, so the cut drops the oldest instead of
# an arbitrary slice — qdrant scrolls by point id, i.e. by random UUID, and
# mem0's get_all does not sort at all.
_MEM0_LIST_LIMIT = 1000
_MEM0_FETCH_LIMIT = 100_000


def _mem0_get_all(m0, pid: str) -> list[dict]:
    """mem0 2.x: filters= + top_k; 1.x: user_id kwarg."""
    try:
        res = m0.get_all(filters={"user_id": pid}, top_k=_MEM0_FETCH_LIMIT)
    except TypeError:
        res = m0.get_all(user_id=pid)
    rows = _mem0_result_list(res)
    if len(rows) >= _MEM0_FETCH_LIMIT:
        logger.warning(
            "memory list for %s hit the %d-row fetch cap; the UI shows a "
            "truncated view", pid, _MEM0_FETCH_LIMIT)
    return rows


def _live_mem0(proj):
    """The chat runtime's own mem0 client for this store, if one is live.

    Embedded qdrant holds an exclusive file lock, so a second client on the same
    path cannot open it — borrowing the live one is not an optimization, it is
    the only way to read while a session is running."""
    from ms_agent.memory.memory_manager import SharedMemoryManager
    from ms_agent.project.paths import memory_dir

    target = Path(str(memory_dir(proj.path)))
    for mem in list(SharedMemoryManager._instances.values()):
        base = getattr(getattr(mem, "mem_config", None), "base_dir", None)
        live = getattr(getattr(mem, "_backend", None), "_mem0", None)
        if base and Path(str(base)) == target and live is not None:
            return live
    return None


@contextmanager
def _mem0_for(proj):
    """Yield a mem0.Memory over the project's store.

    Prefer the live chat runtime's instance; build a transient instance
    otherwise and close its vector client afterwards. Building one loads the
    embedding model, so read paths should prefer ``_vector_items``, which needs
    no embedder at all."""
    live = _live_mem0(proj)
    if live is not None:
        yield live
        return

    from app.backends.ms_agent.config import MemoryConfigError, _mem0_options

    try:
        import mem0
    except Exception:  # pragma: no cover - import guard
        raise BadRequest("Vector memory is unavailable right now.")
    try:
        options = _mem0_options(proj)
    except MemoryConfigError:
        raise BadRequest("Vector memory is unavailable right now.")
    try:
        m0 = mem0.Memory.from_config(options)
    except Exception:
        raise BadRequest("Vector memory could not be started.")
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


def _row_recency(row: dict) -> datetime:
    """Sort key over RAW rows, tolerant of a missing or odd timestamp.

    On the raw dicts rather than on MemoryItem: sorting first and building
    objects only for the page we return keeps a large store from paying for
    validation on rows nobody sees.
    """
    raw = str(row.get("updated_at") or row.get("created_at") or "")
    try:
        at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _store_rows_for_reading(proj, pid: str) -> list[dict]:
    """The project's memories as mem0-shaped rows, WITHOUT an embedder.

    Listing needs payload text and timestamps — nothing that requires embedding
    anything. Going through mem0 for it meant every read built a client and
    loaded the embedding model: ~800ms per request in steady state, on an
    endpoint the memory card polls. So borrow the live client when a session has
    one, and otherwise read the payloads straight out of qdrant.
    """
    from ms_agent.project.paths import memory_dir

    live = _live_mem0(proj)
    if live is not None:
        return _mem0_get_all(live, pid)

    store = Path(str(memory_dir(proj.path))) / "qdrant"
    if not store.exists():  # opening one would CREATE it
        return []
    rows = []
    for row in _read_store_rows(store):
        payload = row["payload"]
        owner = payload.get("user_id")
        if owner is not None and str(owner) != pid:
            continue
        rows.append({
            "id": row["id"],
            "memory": payload.get("data"),
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
        })
    return rows


def _vector_items(proj, pid: str) -> list[MemoryItem]:
    """Read the project's memories, newest first. BLOCKING (qdrant is sync), so
    callers hand it to a thread rather than run it on the event loop."""
    rows = _store_rows_for_reading(proj, pid)
    rows = [r for r in rows if (r.get("memory") or r.get("text"))]
    # Newest first: the store's own order is by point UUID (meaningless to a
    # reader), and since mem0 2.x only ever ADDs, a superseded memory sits next
    # to the one that replaced it — recency is what tells them apart.
    rows.sort(key=_row_recency, reverse=True)
    return [_vector_item(pid, r) for r in rows[:_MEM0_LIST_LIMIT]]


def _vector_delete(proj, item_id: str) -> None:
    """BLOCKING, same reason as ``_vector_items``."""
    with _mem0_for(proj) as m0:
        try:
            m0.delete(memory_id=item_id)
        except Exception as exc:
            if "not found" in str(exc).lower() or isinstance(exc, IndexError):
                raise NotFound("Memory item not found.")
            raise BadRequest("This memory item could not be deleted.")


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



def _reject_while_rebuilding(pid: str) -> None:
    if is_rebuilding(pid):
        raise Conflict("This project's memory is being rebuilt right now. Try again shortly.")


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
        # Fail fast rather than block on the store lock: a re-embedding rebuild
        # holds it for as long as the embedder takes, and a request that hangs
        # for a minute reads as a broken page.
        _reject_while_rebuilding(pid)
        async with _store_lock_for(proj):
            # Off the event loop: mem0 is synchronous and a transient client
            # loads the embedding model, which measured 2s for a NINE-entry
            # store — every other request on the server waited that out.
            return await asyncio.to_thread(_vector_items, proj, pid)
    storage = _storage(proj)
    _migrate_sidecar(pid, proj, storage)
    at = _mtime(storage)
    # File order == MEMORY.md order (what the agent reads).
    return [_item(pid, line, at) for line in _entries(storage)]


def create_item(pid: str, body: MemoryItemCreate) -> MemoryItem:
    proj = _guard(pid)
    content = (body.content or "").strip()
    if not content:
        raise BadRequest("Memory content cannot be empty.")
    if _is_vector(proj):
        # Vector memories are written by the agent's own fact extraction during
        # conversation; hand-authoring them is not offered (the UI has no such
        # affordance either). Removing a wrong one stays allowed.
        raise BadRequest(
            "Memories here are written automatically by the agent and "
            "cannot be added manually.")
    storage = _storage(proj)
    if not storage._add_entry(content):
        raise BadRequest("Memory is full. Remove some entries first.")
    _invalidate_live(proj)
    return _item(pid, content, _mtime(storage))


def update_item(pid: str, item_id: str, body: MemoryItemUpdate) -> MemoryItem:
    proj = _guard(pid)
    content = (body.content or "").strip()
    if not content:
        raise BadRequest("Memory content cannot be empty.")
    if _is_vector(proj):
        # Read-only apart from deletion — see create_item.
        raise BadRequest(
            "Memories here are written automatically by the agent and "
            "cannot be edited manually.")
    storage = _storage(proj)
    old = next((l for l in _entries(storage) if _entry_id(l) == item_id), None)
    if old is None:
        raise NotFound("Memory item not found.")
    if content != old and not storage.replace_entry(old, content):
        raise BadRequest("This update was rejected because memory is full or failed a safety check.")
    _invalidate_live(proj)
    return _item(pid, content, _mtime(storage))


async def delete_item(pid: str, item_id: str) -> None:
    proj = _guard(pid)
    if _is_vector(proj):
        # Deleting from a store that is about to be replaced by its migrated
        # copy would silently come back.
        _reject_while_rebuilding(pid)
        async with _store_lock_for(proj):
            await asyncio.to_thread(_vector_delete, proj, item_id)
        _invalidate_live(proj)
        return
    storage = _storage(proj)
    old = next((l for l in _entries(storage) if _entry_id(l) == item_id), None)
    if old is None:
        raise NotFound("Memory item not found.")
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
        _mem0_llm,
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

    if is_rebuilding(pid):
        # Mid-rebuild the store is being written into a staging directory and the
        # identity file still names the OLD model — reporting either as fact
        # would be wrong. Say what is happening instead.
        return MemoryStatus(project_id=pid, backend="vector", rebuilding=True,
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

    if error is None:
        from app.backends.ms_agent.memory_configuration import current_build_error
        error = current_build_error(proj)
    if error is None:
        try:
            _mem0_llm(_read_settings(), _project_memory_models(proj))
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


# One in-flight rebuild per project. A second request is refused rather than
# queued: it would re-embed the same rows again, and the caller is a button.
_REBUILD_LOCKS: dict[str, asyncio.Lock] = {}
_REBUILDING: set[str] = set()

_COLLECTION = "webui_memory"


def _rebuild_lock(pid: str) -> asyncio.Lock:
    lock = _REBUILD_LOCKS.get(pid)
    if lock is None:
        lock = _REBUILD_LOCKS.setdefault(pid, asyncio.Lock())
    return lock


def is_rebuilding(pid: str) -> bool:
    return pid in _REBUILDING


def _read_store_rows(store: Path) -> list[dict]:
    """Every memory in an on-disk qdrant store: id + payload, no vectors.

    Read from qdrant directly rather than through mem0, because a rebuild
    exists precisely when the store's own embedder may be unusable (key
    revoked, model gone) — and payload text needs no embedder at all.
    """
    from qdrant_client import QdrantClient

    client = QdrantClient(path=str(store))
    try:
        if not client.collection_exists(_COLLECTION):
            return []
        rows: list[dict] = []
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name=_COLLECTION, limit=512, offset=offset,
                with_payload=True, with_vectors=False)
            rows.extend({
                "id": str(p.id),
                "payload": dict(p.payload or {})
            } for p in points)
            if offset is None:
                return rows
    finally:
        try:
            client.close()
        except Exception:  # pragma: no cover - best-effort teardown
            pass


def _write_rows(options: dict, rows: list[dict]) -> int:
    """Re-embed ``rows`` with the embedder in ``options`` and insert them there.

    Ids and payloads are carried over verbatim, so created_at / hash / the BM25
    lemma field survive and mem0's own qdrant insert recomputes the sparse
    vector from that text. Deliberately NOT ``mem0.add()``: that would re-run
    fact extraction and invent different sentences.
    """
    import mem0

    m0 = mem0.Memory.from_config(options)
    try:
        keep = [r for r in rows if str(r["payload"].get("data") or "").strip()]
        if not keep:
            return 0
        texts = [str(r["payload"]["data"]) for r in keep]
        embed_batch = getattr(m0.embedding_model, "embed_batch", None)
        if embed_batch is not None:
            vectors = list(embed_batch(texts, "add"))
        else:  # pragma: no cover - older mem0
            vectors = [m0.embedding_model.embed(t, "add") for t in texts]
        m0.vector_store.insert(
            vectors=vectors,
            ids=[r["id"] for r in keep],
            payloads=[r["payload"] for r in keep])
        return len(keep)
    finally:
        try:
            m0.vector_store.client.close()
        except Exception:  # pragma: no cover - best-effort teardown
            pass


def _embedder_key(identity: dict | None) -> tuple[str, str]:
    return (str((identity or {}).get("provider") or "unknown"),
            str((identity or {}).get("model") or ""))


def _embedder_slug(identity: dict | None) -> str:
    """Filesystem-safe, COLLISION-FREE name for a store's embedder.

    The readable part drops vendor prefixes and unsafe characters and is
    truncated, so on its own it can map two different models onto one name
    (``openai/org-a/embed-large`` and ``openai/org-b/embed-large`` both became
    ``openai-embed-large``) — and the backup for one would then be deleted as if
    it belonged to the other. The digest is over the FULL identity, so equal
    names mean equal embedders.
    """
    import re

    provider, model = _embedder_key(identity)
    digest = hashlib.sha256(
        f"{provider}\x1f{model}".encode("utf-8")).hexdigest()[:8]
    readable = re.sub(r"[^A-Za-z0-9._-]+", "-",
                      f"{provider}-{model.split('/')[-1]}").strip("-")
    return f"{(readable or 'unknown')[:60]}-{digest}"


def _retire_store(mem_dir: Path, qdrant: Path, identity: dict | None) -> Path:
    """Move the live store aside, keeping AT MOST ONE backup per embedder.

    Named by the embedder that produced it rather than by timestamp, so
    switching back and forth between two models keeps two backups instead of
    one per click. Replacing the same model's previous backup loses nothing: a
    rebuild always carries every entry forward, so the older snapshot of that
    model is a strict subset of what is being retired now.

    A copy of the identity goes into the backup, so the directory still says
    what it holds even if this naming ever changes.
    """
    import shutil

    from app.backends.ms_agent.config import _EMBEDDER_IDENTITY_FILE

    backup = mem_dir / f"qdrant.bak-{_embedder_slug(identity)}"
    if backup.exists():
        # Belt and braces on top of the digest: only delete a backup that says
        # it holds the same embedder. Anything else (hand-made directory, a
        # marker from a future naming scheme) is kept and this one gets a
        # timestamped name instead of being silently overwritten.
        marker = backup / _EMBEDDER_IDENTITY_FILE
        existing = None
        try:
            existing = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = None
        if existing is None or _embedder_key(existing) == _embedder_key(identity):
            logger.info("replacing previous backup for the same embedder: %s",
                        backup.name)
            shutil.rmtree(backup, ignore_errors=True)
        else:
            logger.warning(
                "backup %s claims %s, not %s — keeping it and stamping this one",
                backup.name, _embedder_key(existing), _embedder_key(identity))
            import time as _t

            backup = mem_dir / f"qdrant.bak-{_t.strftime('%Y%m%d-%H%M%S')}"
    shutil.move(str(qdrant), str(backup))
    if identity:
        try:
            (backup / _EMBEDDER_IDENTITY_FILE).write_text(
                json.dumps(identity, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError as exc:  # pragma: no cover - marker is best-effort
            logger.warning("could not mark backup %s: %s", backup, exc)
    _prune_unattributed_backups(mem_dir)
    return backup


def _prune_unattributed_backups(mem_dir: Path) -> None:
    """Collapse the timestamped backups from before per-embedder naming.

    They carry no record of which model built them, so they cannot be grouped:
    keep the newest as a single last-resort copy and drop the rest, otherwise
    every past switch stays on disk forever (a provider store is ~4x the size
    of a local one — this grows in tens of MB, not KB).
    """
    import re
    import shutil

    legacy = sorted(
        (p for p in mem_dir.glob("qdrant.bak-*")
         if p.is_dir() and re.fullmatch(r"\d{8}-\d{6}", p.name[len("qdrant.bak-"):])),
        key=lambda p: p.stat().st_mtime,
        reverse=True)
    for stale in legacy[1:]:
        logger.info("pruning superseded backup %s", stale.name)
        shutil.rmtree(stale, ignore_errors=True)


def _backup_ledger(mem_dir: Path, stamp: str) -> None:
    """Set the ingest ledger aside (kept, not deleted).

    Only when nothing was carried over: the ledger says "these messages are
    already in the store", which stops being true for an empty store, and the
    next completed turn should re-ingest the session instead of writing nothing.
    """
    ledger = mem_dir / "ingest_state.json"
    if not ledger.exists():
        return
    try:
        ledger.replace(mem_dir / f"ingest_state.json.bak-{stamp}")
    except OSError as exc:  # pragma: no cover - bookkeeping never breaks
        logger.warning("ingest ledger backup failed for %s: %s", mem_dir, exc)


async def _rebuild_store(proj, mem_dir: Path) -> tuple[int, bool]:
    """The rebuild's actual work. Returns ``(migrated, reused)``."""
    import shutil
    import time as _time

    from app.backends.ms_agent.config import (
        MemoryConfigError,
        _commit_embedder_identity,
        _load_embedder_identity,
        _mem0_options_for,
        _mem0_llm,
        _new_embedder_identity,
        _project_memory_models,
        _read_settings,
        _resolve_embedder,
        _stage_embedder_identity,
        ensure_embedder_usable,
    )
    from ms_agent.memory.memory_manager import SharedMemoryManager

    qdrant = mem_dir / "qdrant"
    settings = _read_settings()
    mem_cfg = _project_memory_models(proj)
    # Resolve the target embedder ONCE, up front. The project's config can
    # change again while we re-embed, and vectors must be labelled with the
    # model that actually produced them — never with whatever is configured by
    # the time we finish.
    def _prepare_embedder(d: dict) -> dict:
        # Load the model BEFORE anything destructive happens (below this point
        # the project's runtimes get retired and the store is moved). For the
        # local mode this is the ~220 MB first-use download: doing it here
        # means a network failure costs the user a clear error and nothing
        # else, instead of a retired runtime plus a bare errno.
        ensure_embedder_usable(d)
        return _new_embedder_identity(d)

    try:
        desc = _resolve_embedder(settings, mem_cfg)
        identity = await asyncio.to_thread(_prepare_embedder, desc)
    except MemoryConfigError as exc:
        raise BadRequest(f"Memory cannot be rebuilt: {exc}")
    except Exception:
        raise BadRequest(
            "Memory cannot be rebuilt because the embedding model is "
            "unavailable. Check the model settings and try again.")

    stored = _load_embedder_identity(proj)
    if (stored is not None and qdrant.exists()
            and (stored.get("provider"), stored.get("model")) == (
                identity["provider"], identity["model"])):
        # The store already speaks this embedder — switching away and back
        # again is not a reason to touch it.
        return 0, True

    try:
        _mem0_llm(settings, mem_cfg)
    except MemoryConfigError as exc:
        raise BadRequest(f"Memory cannot be rebuilt: {exc}") from exc

    # Residue from an interrupted attempt. Inert, but it would confuse this one.
    for stale in mem_dir.glob("qdrant.new-*"):
        shutil.rmtree(stale, ignore_errors=True)

    from app.backends.ms_agent.runtime import registry

    # A turn in flight cannot be served across this: the store it retrieves from
    # and ingests into is about to be replaced, and the shared instance it holds
    # gets retired. Rather than let that turn silently lose its memory, refuse —
    # the caller is a button, and the turn is seconds away from finishing.
    if registry.project_is_running(proj.id):
        raise Conflict(
            "A conversation in this project is still running. Rebuild memory "
            "once it finishes.")

    # Retire the runtimes that hold this project's memory FIRST. Closing a
    # shared orchestrator retires it for good, so an agent still holding one
    # would keep running with memory that silently does nothing — no retrieval,
    # no ingestion — until its runtime was evicted.
    await registry._discard_project(proj.id)
    # Whatever is left (a runtime that became busy in between, or nothing): the
    # store's exclusive file lock must be released before the directory moves.
    # Released before taking the store lock, because closing an orchestrator
    # takes it too.
    await SharedMemoryManager.close_matching(str(mem_dir))

    async with _store_lock_for(proj):
        stamp = _time.strftime("%Y%m%d-%H%M%S")
        rows = (await asyncio.to_thread(_read_store_rows, qdrant)
                if qdrant.exists() else [])
        # Prove we can record the new identity BEFORE moving anything: a store
        # that speaks model B under an identity that still says model A reads as
        # a permanent mismatch, and the project's embedder gets pinned to the
        # wrong one. Staged next to its target, so the commit below is a rename.
        try:
            staged_identity = _stage_embedder_identity(proj, identity)
        except OSError:
            raise BadRequest(
                "Memory could not be rebuilt. Nothing was changed — your "
                "existing memory is intact.")

        if not rows:
            if qdrant.exists():
                _retire_store(mem_dir, qdrant, stored)
            _backup_ledger(mem_dir, stamp)
            _commit_embedder_identity(proj, staged_identity)
            return 0, False

        staging = mem_dir / f"qdrant.new-{stamp}"
        options = _mem0_options_for(
            proj, settings, mem_cfg, desc, identity, qdrant_path=str(staging))
        try:
            migrated = await asyncio.to_thread(_write_rows, options, rows)
        except Exception:
            # Nothing has moved yet, so the project keeps working exactly as it
            # did — still mismatched, still one click away from another attempt.
            shutil.rmtree(staging, ignore_errors=True)
            staged_identity.unlink(missing_ok=True)
            raise BadRequest(
                "Rebuilding memory failed. Your existing memory was left "
                "untouched — you can try again.")
        # Swap only now that the new store is complete — and put the old one
        # back if either half of the swap fails, so a rebuild that goes wrong
        # never costs the project its live store. (The same model's previous
        # backup was deleted to make room; it held a strict subset of what is
        # being restored, so the rollback loses nothing.)
        retired = _retire_store(mem_dir, qdrant, stored)

        def _undo() -> None:
            if qdrant.exists():  # the new store had already landed
                shutil.move(str(qdrant), str(staging))
            if retired.exists():
                shutil.move(str(retired), str(qdrant))
            shutil.rmtree(staging, ignore_errors=True)
            staged_identity.unlink(missing_ok=True)

        try:
            shutil.move(str(staging), str(qdrant))
            # The ledger stays: the memories came along, so re-ingesting the
            # session would only duplicate them.
            _commit_embedder_identity(proj, staged_identity)
        except Exception:
            _undo()
            raise BadRequest(
                "Rebuilding memory failed at the last step. Your previous "
                "memory was restored — you can try again.")
        logger.info("rebuilt memory store for %s: %d entries re-embedded with "
                    "%s/%s", proj.id, migrated, identity["provider"],
                    identity["model"])
        return migrated, False


async def rebuild(pid: str):
    """Re-embed this project's memories with the CURRENT embedder.

    Changing the embedding model invalidates the vectors, not the memories:
    every entry's text is right there in the store's payload, so the remedy is
    to re-embed it — the old behaviour (open an empty store, leave the entries
    in a backup nobody reads) lost them for all practical purposes.

    The old store still moves to ``qdrant.bak-<ts>`` and is never deleted, and
    the swap happens only after the replacement is fully written, so an
    interrupted or failed rebuild leaves the project exactly as it was. Async on
    purpose: closing the live orchestrator must run on the app loop, where its
    pending ingest tasks live.
    """
    from ms_agent.project.paths import memory_dir

    from app.schemas.memory import MemoryRebuildResult

    proj = _guard(pid)
    if not _is_vector(proj):
        raise BadRequest("Rebuilding memory is only available for vector memory.")

    lock = _rebuild_lock(pid)
    if lock.locked():
        raise Conflict("A memory rebuild is already running for this project.")
    async with lock:
        _REBUILDING.add(pid)
        try:
            migrated, reused = await _rebuild_store(
                proj, Path(str(memory_dir(proj.path))))
        finally:
            _REBUILDING.discard(pid)
    return MemoryRebuildResult(
        project_id=pid, migrated=migrated, reused=reused,
        status=get_status(pid))


# ── file backend: the whole document ──────────────────────────────────────
# With memory_backend="file", memory IS one markdown file the agent reads
# (MEMORY.md). The UI previews/edits it as a document, so these two functions
# expose it wholesale instead of line-by-line. Vector projects have no such
# file and are rejected.

def _require_file_backend(proj):
    if _is_vector(proj):
        raise BadRequest(
            "This project uses vector memory, which has no memory document.")


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
            f"Memory is too long ({len(text)} of {storage.char_limit} "
            "characters allowed). Shorten it and save again.")
    if not storage.full_replace(text):
        raise BadRequest("This update was rejected because it failed a safety check.")
    _invalidate_live(proj)
    return MemoryDoc(
        project_id=pid, content=storage.get_content(), updated_at=_mtime(storage)
    )
