"""Project-scoped memory items.

Memory is gated per-project. Default project never has memory. Each project
that has `memory_enabled=True` holds a list of content items (no path/filename).
"""

from fastapi import APIRouter, HTTPException

from app.core import store
from app.core.envelope import EnvelopeRoute
from app.core.settings import settings
from app.schemas.memory import MemoryItem, MemoryItemCreate, MemoryItemUpdate

router = APIRouter(prefix="/api/projects/{project_id}/memory", tags=["memory"],
                   route_class=EnvelopeRoute)


def _ms() -> bool:
    return settings.agent_backend == "ms_agent"


def _project(project_id: str) -> dict:
    row = store.projects.get(project_id)
    if not row:
        raise HTTPException(404, "project not found")
    if row["is_default"]:
        raise HTTPException(400, "default project does not support memory")
    if not row.get("memory_enabled"):
        raise HTTPException(400, "memory is disabled for this project")
    return row


def _items(project_id: str) -> list[dict]:
    return store.memory_files.setdefault(project_id, [])


def _find(project_id: str, item_id: str) -> dict | None:
    for item in _items(project_id):
        if item["id"] == item_id:
            return item
    return None


@router.get("/items")
def list_items(project_id: str) -> list[MemoryItem]:
    if _ms():
        from app.backends.ms_agent import memory

        return memory.list_items(project_id)
    _project(project_id)
    rows = sorted(_items(project_id), key=lambda x: x.get("updated_at", ""))
    return [MemoryItem.model_validate(r) for r in rows]


@router.post("/items", status_code=201)
def create_item(project_id: str, body: MemoryItemCreate) -> MemoryItem:
    if _ms():
        from app.backends.ms_agent import memory

        return memory.create_item(project_id, body)
    _project(project_id)
    row = {
        "id": store.new_id("mem_"),
        "project_id": project_id,
        "content": body.content,
        "updated_at": store.now(),
    }
    _items(project_id).append(row)
    return MemoryItem.model_validate(row)


@router.put("/items/{item_id}")
def update_item(project_id: str, item_id: str,
                body: MemoryItemUpdate) -> MemoryItem:
    if _ms():
        from app.backends.ms_agent import memory

        return memory.update_item(project_id, item_id, body)
    _project(project_id)
    row = _find(project_id, item_id)
    if not row:
        raise HTTPException(404, "memory item not found")
    row["content"] = body.content
    row["updated_at"] = store.now()
    return MemoryItem.model_validate(row)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(project_id: str, item_id: str) -> None:
    if _ms():
        from app.backends.ms_agent import memory

        return memory.delete_item(project_id, item_id)
    _project(project_id)
    items = _items(project_id)
    for i, item in enumerate(items):
        if item["id"] == item_id:
            items.pop(i)
            return
    raise HTTPException(404, "memory item not found")
