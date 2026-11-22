from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MemoryItem(BaseModel):
    id: str
    project_id: str
    content: str = ""
    updated_at: datetime


class MemoryItemCreate(BaseModel):
    content: str = Field(min_length=1)


class MemoryItemUpdate(BaseModel):
    content: str = Field(min_length=1)


class MemoryDoc(BaseModel):
    """The whole file-backend memory document (``MEMORY.md``).

    Only meaningful for ``memory_backend="file"``, where memory IS one markdown
    file the agent reads: the UI previews and edits it as a document instead of
    line-by-line items. The vector backend has no such file.
    """

    project_id: str
    content: str = ""
    updated_at: datetime


class MemoryDocUpdate(BaseModel):
    # Empty is allowed here (unlike an item): clearing the document is how the
    # user wipes file-backend memory.
    content: str = ""


# ── vector backend health surface ──────────────────────────────────────────


class MemoryEmbedderInfo(BaseModel):
    """Which embedding model this project's vector store runs on."""

    mode: str  # "provider" | "local"
    provider: str | None = None  # None for local
    model: str | None = None
    dimension: int | None = None  # None until first probed
    # Set when the default resolution had to fall back (e.g. the conversation
    # provider serves no embeddings) — the UI shows this verbatim.
    fallback_reason: str | None = None


class MemoryErrorInfo(BaseModel):
    """Why vector memory is unusable right now. ``code`` is machine-readable
    (embedder_mismatch | embed_unavailable | local_missing) so the UI can
    offer the right remedy (e.g. a rebuild button for a mismatch)."""

    code: str
    message: str


class MemoryProviderOption(BaseModel):
    id: str
    credentials_available: bool
    endpoint_available: bool
    embedding_models: list[str] = Field(default_factory=list)


class MemoryModelCheck(BaseModel):
    memory_llm_provider_id: str | None = None
    memory_llm_model: str | None = None
    memory_embed_mode: Literal["provider", "local"] = "provider"
    memory_embed_provider_id: str | None = None
    memory_embed_model: str | None = None
    # Only an explicit check/submit calls the service. Opening a dropdown is free.
    probe: bool = False


class MemoryModelCheckResult(BaseModel):
    valid: bool
    verified: bool = False
    embedder: MemoryEmbedderInfo | None = None
    errors: list[MemoryErrorInfo] = Field(default_factory=list)


class MemoryIngestInfo(BaseModel):
    """Last background-ingest outcome of the live runtime, if any."""

    state: str  # idle | scheduled | running | ok | error
    at: str | None = None
    count: int | None = None
    error: str | None = None
    pending: int = 0


class MemoryStatus(BaseModel):
    project_id: str
    backend: str  # "file" | "vector"
    embedder: MemoryEmbedderInfo | None = None
    error: MemoryErrorInfo | None = None
    ingest: MemoryIngestInfo | None = None
    # Whether the optional fastembed extra is installed (drives UI hints).
    local_embed_available: bool = False
    # A re-embedding rebuild is running right now (re-embedding a large store
    # takes a while, and a second one must not be started).
    rebuilding: bool = False


class MemoryRebuildResult(BaseModel):
    """Outcome of a rebuild, so the UI can say what actually happened."""

    project_id: str
    # Entries carried into the new store, re-embedded with the current model.
    migrated: int = 0
    # The store already spoke the current embedder: nothing was touched.
    reused: bool = False
    status: MemoryStatus
