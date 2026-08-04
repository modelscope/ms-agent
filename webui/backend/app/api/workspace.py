"""Project-scoped workspace files.

Iter-3 scope: real CRUD against an in-memory mock so the UI can stop using the
hard-coded tree in SessionRightRail. Upload / download / Import are stubbed —
the frontend exposes the affordances but they POST/PUT plain JSON through
this same surface.
"""

import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.core import store
from app.core.envelope import EnvelopeRoute
from app.core.filetypes import guess_type, is_binary_ext
from app.core.settings import settings
from app.schemas.workspace import (
    WorkspaceFile,
    WorkspaceFileCreate,
    WorkspaceFileMove,
    WorkspaceFileUpdate,
)

router = APIRouter(
    prefix="/api/projects/{project_id}/workspace",
    tags=["workspace"],
    route_class=EnvelopeRoute,
)


def _ms() -> bool:
    return settings.agent_backend == "ms_agent"


def _project(project_id: str) -> dict:
    row = store.projects.get(project_id)
    if not row:
        raise HTTPException(404, "project not found")
    return row


def _files(project_id: str) -> list[dict]:
    return store.workspace_files.setdefault(project_id, [])


def _find(project_id: str, path: str) -> dict | None:
    for f in _files(project_id):
        if f["path"] == path:
            return f
    return None


def _dedup_rel(project_id: str, rel: str, data: bytes) -> str:
    """Non-clobbering relative path for a mock-backend dedup upload: the first
    upload of a name keeps it; a later same-named upload reuses that first row
    when the bytes are identical, else is timestamped
    (``<stem>-<epoch_ms><ext>``) — mirrors ms_agent workspace._dedup_target; a
    same-ms collision falls back to a counter."""
    row = _find(project_id, rel)
    if row is None or row.get("_data") == data:
        return rel  # free name, or identical re-upload of the first → reuse
    stem, dot, ext = rel.rpartition(".")
    base, suffix = (stem, f".{ext}") if dot else (rel, "")
    ts = int(time.time() * 1000)
    cand = f"{base}-{ts}{suffix}"
    i = 1
    while _find(project_id, cand) is not None:
        cand = f"{base}-{ts}-{i}{suffix}"
        i += 1
    return cand


@router.get("/files")
def list_files(project_id: str) -> list[WorkspaceFile]:
    if _ms():
        from app.backends.ms_agent import workspace

        return workspace.list_files(project_id)
    _project(project_id)
    rows = sorted(_files(project_id), key=lambda f: f["path"])
    return [WorkspaceFile.model_validate(f) for f in rows]


@router.post("/files", status_code=201)
def create_file(project_id: str, body: WorkspaceFileCreate) -> WorkspaceFile:
    if _ms():
        from app.backends.ms_agent import workspace

        return workspace.create_file(project_id, body)
    _project(project_id)
    if _find(project_id, body.path) is not None:
        raise HTTPException(409, "file already exists")
    row = {
        "project_id":
        project_id,
        "path":
        body.path,
        "kind":
        body.kind,
        "size":
        body.size if body.size is not None else len(
            body.content.encode("utf-8")),
        "updated_at":
        store.now(),
        "preview":
        body.content[:200] if body.content else None,
        "content":
        None if body.kind == "folder" or is_binary_ext(body.path) else
        body.content,
        "content_type":
        None if body.kind == "folder" else guess_type(body.path),
    }
    _files(project_id).append(row)
    return WorkspaceFile.model_validate(row)


@router.post("/files/move")
def move_file(project_id: str, body: WorkspaceFileMove) -> WorkspaceFile:
    """Rename/move a file or folder. Folder moves rewrite every child path."""
    if _ms():
        from app.backends.ms_agent import workspace

        return workspace.move_file(project_id, body.src, body.dst)
    _project(project_id)
    src, dst = body.src, body.dst
    if src == dst:
        row = _find(project_id, src)
        if row is None:
            raise HTTPException(404, "file not found")
        return WorkspaceFile.model_validate(row)
    if _find(project_id, dst) is not None:
        raise HTTPException(409, "target already exists")
    files = _files(project_id)
    moved: dict | None = None
    touched = False
    for f in files:
        p = f["path"]
        if p == src:
            f["path"] = dst
            f["updated_at"] = store.now()
            moved = f
            touched = True
        elif p.startswith(src + "/"):
            f["path"] = dst + p[len(src):]
            f["updated_at"] = store.now()
            touched = True
    if not touched:
        raise HTTPException(404, "file not found")
    if moved is None:
        # Folder with no own row (only children moved): synthesize a folder row.
        moved = {
            "project_id": project_id,
            "path": dst,
            "kind": "folder",
            "size": 0,
            "updated_at": store.now(),
        }
    return WorkspaceFile.model_validate(moved)


@router.get("/files/{file_path:path}/raw")
def raw_file(project_id: str, file_path: str) -> Response:
    """Serve raw file bytes (for media preview / download). Not enveloped: the
    EnvelopeRoute only wraps JSON responses, so binary passes through as-is."""
    if _ms():
        from app.backends.ms_agent import workspace

        target, ctype = workspace.raw_file(project_id, file_path)
        return Response(content=target.read_bytes(), media_type=ctype)
    _project(project_id)
    row = _find(project_id, file_path)
    if not row or row.get("kind") == "folder":
        raise HTTPException(404, "file not found")
    data = row.get("_data")
    if data is None:
        data = (row.get("content") or "").encode("utf-8")
    ctype = row.get("content_type") or guess_type(file_path) \
        or "application/octet-stream"
    return Response(content=data, media_type=ctype)


@router.post("/files/upload", status_code=201)
async def upload_file(
    project_id: str,
    file: UploadFile = File(...),
    path: str | None = Form(None),
    dedup: bool = Form(False),
) -> WorkspaceFile:
    """Binary-safe upload via multipart/form-data. Raw bytes are written to disk
    unchanged. A same-path file is overwritten by default; with ``dedup`` (chat
    attachments into ``user_files/``) a same-named-but-different file is
    auto-suffixed and the returned ``path`` is the real, deduped location."""
    rel = (path or file.filename or "").strip()
    if not rel:
        raise HTTPException(422, "missing file path")
    data = await file.read()
    if _ms():
        from app.backends.ms_agent import workspace

        return workspace.save_upload(project_id, rel, data, dedup=dedup)
    _project(project_id)
    try:
        text: str | None = data.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if is_binary_ext(rel):
        text = None  # never inline archives/media/etc. as text
    ctype = file.content_type or guess_type(rel) or "application/octet-stream"
    # dedup (chat attachments): the first upload of a name keeps it; a later
    # same-named upload reuses it when the bytes match, else is timestamped.
    # Parity with the ms_agent backend's _dedup_target.
    if dedup:
        rel = _dedup_rel(project_id, rel, data)
    existing = _find(project_id, rel)
    row = existing
    if row is None:
        row = {"project_id": project_id, "path": rel, "kind": "file"}
        _files(project_id).append(row)
    row.update({
        "kind": "file",
        "size": len(data),
        "updated_at": store.now(),
        "preview": text[:200] if text else None,
        "content": text,
        "content_type": ctype,
        "_data": data,
    })
    return WorkspaceFile.model_validate(row)


@router.get("/files/{file_path:path}")
def get_file(project_id: str, file_path: str) -> WorkspaceFile:
    if _ms():
        from app.backends.ms_agent import workspace

        return workspace.get_file(project_id, file_path)
    _project(project_id)
    row = _find(project_id, file_path)
    if not row:
        raise HTTPException(404, "file not found")
    return WorkspaceFile.model_validate(row)


@router.put("/files/{file_path:path}")
def update_file(project_id: str, file_path: str,
                body: WorkspaceFileUpdate) -> WorkspaceFile:
    if _ms():
        from app.backends.ms_agent import workspace

        return workspace.update_file(project_id, file_path, body)
    _project(project_id)
    row = _find(project_id, file_path)
    if not row:
        raise HTTPException(404, "file not found")
    row["size"] = len(body.content.encode("utf-8"))
    row["preview"] = body.content[:200] if body.content else None
    row["updated_at"] = store.now()
    return WorkspaceFile.model_validate(row)


@router.delete("/files/{file_path:path}", status_code=204)
def delete_file(project_id: str, file_path: str) -> None:
    if _ms():
        from app.backends.ms_agent import workspace

        return workspace.delete_file(project_id, file_path)
    _project(project_id)
    files = _files(project_id)
    for i, f in enumerate(files):
        if f["path"] == file_path:
            files.pop(i)
            return
    raise HTTPException(404, "file not found")
