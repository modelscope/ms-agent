"""Project-scoped memory items.

Memory is gated per-project: every route 404s for an unknown project and 400s
when the project has `memory_enabled=False`. The default project is not special
here — it simply ships with memory off.
"""

from fastapi import APIRouter, HTTPException

from app.core.envelope import EnvelopeRoute
from app.schemas.memory import (
    MemoryDoc,
    MemoryDocUpdate,
    MemoryItem,
    MemoryItemCreate,
    MemoryItemUpdate,
    MemoryStatus,
)

router = APIRouter(prefix="/api/projects/{project_id}/memory", tags=["memory"],
                   route_class=EnvelopeRoute)


@router.get("/status")
def get_status(project_id: str) -> MemoryStatus:
    """Health of the project's memory: the resolved embedder identity, why
    vector memory is unusable if it is, and the last ingest outcome."""
    from app.backends.ms_agent import memory

    return memory.get_status(project_id)


@router.post("/rebuild")
async def rebuild(project_id: str) -> MemoryStatus:
    """Start the vector store over with the current embedder (the remedy for
    an embedder mismatch). The old store is moved to qdrant.bak-<ts>."""
    from app.backends.ms_agent import memory

    return await memory.rebuild(project_id)


@router.get("/items")
async def list_items(project_id: str) -> list[MemoryItem]:
    from app.backends.ms_agent import memory

    return await memory.list_items(project_id)


@router.post("/items", status_code=201)
def create_item(project_id: str, body: MemoryItemCreate) -> MemoryItem:
    from app.backends.ms_agent import memory

    return memory.create_item(project_id, body)


@router.put("/items/{item_id}")
def update_item(project_id: str, item_id: str,
                body: MemoryItemUpdate) -> MemoryItem:
    from app.backends.ms_agent import memory

    return memory.update_item(project_id, item_id, body)


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(project_id: str, item_id: str) -> None:
    from app.backends.ms_agent import memory

    return await memory.delete_item(project_id, item_id)


# ── file backend only: memory as one markdown document ─────────────────────
# `memory_backend="file"` stores memory as a single MEMORY.md the agent reads,
# so the UI previews/edits it as a document. 400 for vector projects.


@router.get("/doc")
def get_doc(project_id: str) -> MemoryDoc:
    from app.backends.ms_agent import memory

    return memory.get_doc(project_id)


@router.put("/doc")
def put_doc(project_id: str, body: MemoryDocUpdate) -> MemoryDoc:
    from app.backends.ms_agent import memory

    return memory.put_doc(project_id, body)
