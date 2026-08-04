from datetime import datetime

from pydantic import BaseModel, Field


class WorkspaceFile(BaseModel):
    project_id: str
    path: str
    kind: str = "file"
    size: int = 0
    updated_at: datetime
    preview: str | None = None
    # Full text content, only populated on single-file GET (never in listings).
    # None for folders, binary/undecodable files, or when omitted for size.
    content: str | None = None
    # Best-effort MIME type guessed from the extension. Drives the frontend
    # preview: text -> Monaco, image/video/audio -> media element, else -> a
    # "preview unavailable" placeholder. Raw bytes are served from .../raw.
    content_type: str | None = None


class WorkspaceFileCreate(BaseModel):
    path: str = Field(min_length=1, max_length=400)
    content: str = ""
    kind: str = "file"
    size: int | None = None  # If provided, use this instead of computing from content


class WorkspaceFileUpdate(BaseModel):
    content: str = ""


class WorkspaceFileMove(BaseModel):
    """Rename or move a file/folder: ``src`` and ``dst`` are workspace-relative
    paths. A rename keeps the parent dir; a move changes it. Folders move with
    all their children."""

    src: str = Field(min_length=1, max_length=400)
    dst: str = Field(min_length=1, max_length=400)
