"""Project-scoped workspace files.

Real CRUD against the on-disk SDK workspace: listing, read/write, move, delete,
binary-safe upload, raw byte serving, and a streamed zip of the tree (or of one
folder in it).
"""

from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.core.envelope import EnvelopeRoute
from app.core.filetypes import raw_headers
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


@router.get("/raw/{file_path:path}")
def raw_file(project_id: str, file_path: str) -> Response:
    """Serve raw file bytes (for media preview / download). Not enveloped: the
    EnvelopeRoute only wraps JSON responses, so binary passes through as-is.

    FileResponse rather than reading the bytes ourselves: it streams from disk in
    chunks, so serving a large file costs a buffer instead of its full size in
    resident memory -- which, multiplied by concurrent downloads, was the real
    cost here.

    The path is the URL TAIL (not `/files/<path>/raw`) so that a previewed HTML
    document resolves its own `./style.css` back into this route.
    """
    from app.backends.ms_agent import workspace

    target, ctype = workspace.raw_file(project_id, file_path)
    return FileResponse(target, media_type=ctype, headers=raw_headers(ctype))


# Before the `/files/{file_path:path}` catch-all in URL space but deliberately
# NOT under /files: a path segment there would be swallowed by that route.
@router.get("/archive")
def archive(project_id: str, path: str = "") -> StreamingResponse:
    """Stream a zip of the workspace, or of the folder at ``path``.

    The browser used to fetch every file and zip them itself -- one request per
    file, with the whole workspace and the finished archive both in tab memory.
    Compressing here is a CPU cost the client used to pay, so the level is tuned
    down accordingly (see workspace._ARCHIVE_LEVEL).

    No Content-Length: the archive is compressed as it is sent, so its size
    isn't known when the headers go out. Clients get an indeterminate progress
    indication in exchange for neither end buffering the whole thing.
    """
    from app.backends.ms_agent import workspace

    filename, chunks = workspace.archive(project_id, path)
    # RFC 6266/5987: the bare `filename` stays ASCII for old clients, with the
    # real (possibly non-ASCII) project name in `filename*`. The frontend names
    # the saved file itself; this is for anyone calling the endpoint directly.
    disposition = (f"attachment; filename=\"archive.zip\"; "
                   f"filename*=UTF-8''{quote(filename)}")
    return StreamingResponse(
        chunks,
        media_type="application/zip",
        headers={"Content-Disposition": disposition},
    )


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
        raise HTTPException(422, "A file path is required.")
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
