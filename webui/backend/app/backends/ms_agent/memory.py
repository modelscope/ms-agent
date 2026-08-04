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

Same guards as the mock: real project, not default, memory enabled.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.backends.errors import BadRequest, NotFound
from app.schemas.memory import MemoryItem, MemoryItemCreate, MemoryItemUpdate


def _guard(pid: str):
    from ms_agent.project.types import DEFAULT_PROJECT_ID

    from app.backends.ms_agent.common import pm

    proj = pm().get(pid)
    if proj is None:
        raise NotFound("project not found")
    if proj.id == DEFAULT_PROJECT_ID:
        raise BadRequest("default project does not support memory")
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


def _mem0_get_all(m0, pid: str) -> list[dict]:
    """mem0 2.x: filters= + top_k (default 20 is too small for a notes list);
    1.x: user_id kwarg."""
    try:
        res = m0.get_all(filters={"user_id": pid}, top_k=200)
    except TypeError:
        res = m0.get_all(user_id=pid)
    return _mem0_result_list(res)


def _mem0_update(m0, item_id: str, content: str) -> None:
    try:
        m0.update(memory_id=item_id, text=content)
    except TypeError:
        m0.update(memory_id=item_id, data=content)


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

    from app.backends.ms_agent.config import _mem0_options

    try:
        import mem0
    except Exception as exc:  # pragma: no cover - import guard
        raise BadRequest(f"vector memory unavailable: {exc}")
    options = _mem0_options(proj)
    if options is None:
        raise BadRequest("vector memory unavailable: no embeddings provider configured")
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


def list_items(pid: str) -> list[MemoryItem]:
    proj = _guard(pid)
    if _is_vector(proj):
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
        with _mem0_for(proj) as m0:
            # infer=False stores the note verbatim (no LLM rewriting).
            res = _mem0_result_list(m0.add(content, user_id=pid, infer=False))
        added = next((r for r in res if r.get("id")), None)
        if added is None:
            raise BadRequest("vector memory rejected the entry")
        _invalidate_live(proj)
        return _vector_item(pid, {**added, "memory": added.get("memory") or content})
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
        with _mem0_for(proj) as m0:
            try:
                _mem0_update(m0, item_id, content)
            except Exception as exc:
                if "not found" in str(exc).lower():
                    raise NotFound("memory item not found")
                raise BadRequest(f"vector memory update failed: {exc}")
        _invalidate_live(proj)
        return _vector_item(pid, {"id": item_id, "memory": content, "updated_at": _now()})
    storage = _storage(proj)
    old = next((l for l in _entries(storage) if _entry_id(l) == item_id), None)
    if old is None:
        raise NotFound("memory item not found")
    if content != old and not storage.replace_entry(old, content):
        raise BadRequest("memory update rejected (char budget or security scan)")
    _invalidate_live(proj)
    return _item(pid, content, _mtime(storage))


def delete_item(pid: str, item_id: str) -> None:
    proj = _guard(pid)
    if _is_vector(proj):
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
