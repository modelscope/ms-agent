"""Project-scoped workspace files.

Iter-3 scope: real CRUD against an in-memory mock so the UI can stop using the
hard-coded tree in SessionRightRail. Upload / download / Import are stubbed —
the frontend exposes the affordances but they POST/PUT plain JSON through
this same surface.
"""

import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.core.envelope import EnvelopeRoute
from app.core.filetypes import guess_type, is_binary_ext
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


@router.get("/files")
def list_files(project_id: str) -> list[WorkspaceFile]:
    from app.backends.ms_agent import workspace

    return workspace.list_files(project_id)


@router.post("/files", status_code=201)
def create_file(project_id: str, body: WorkspaceFileCreate) -> WorkspaceFile:
    from app.backends.ms_agent import workspace

    return workspace.create_file(project_id, body)


@router.post("/files/move")
def move_file(project_id: str, body: WorkspaceFileMove) -> WorkspaceFile:
    """Rename/move a file or folder. Folder moves rewrite every child path."""
    from app.backends.ms_agent import workspace

    return workspace.move_file(project_id, body.src, body.dst)


@router.get("/files/{file_path:path}/raw")
def raw_file(project_id: str, file_path: str) -> Response:
    """Serve raw file bytes (for media preview / download). Not enveloped: the
    EnvelopeRoute only wraps JSON responses, so binary passes through as-is."""
    from app.backends.ms_agent import workspace

    target, ctype = workspace.raw_file(project_id, file_path)
    return Response(content=target.read_bytes(), media_type=ctype)


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
    from app.backends.ms_agent import workspace

    return workspace.save_upload(project_id, rel, data, dedup=dedup)


@router.get("/files/{file_path:path}")
def get_file(project_id: str, file_path: str) -> WorkspaceFile:
    from app.backends.ms_agent import workspace

    return workspace.get_file(project_id, file_path)


@router.put("/files/{file_path:path}")
def update_file(project_id: str, file_path: str,
                body: WorkspaceFileUpdate) -> WorkspaceFile:
    from app.backends.ms_agent import workspace

    return workspace.update_file(project_id, file_path, body)


@router.delete("/files/{file_path:path}", status_code=204)
def delete_file(project_id: str, file_path: str) -> None:
    from app.backends.ms_agent import workspace

    return workspace.delete_file(project_id, file_path)
