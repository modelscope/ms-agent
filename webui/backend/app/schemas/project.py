from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


MemoryBackend = Literal["file", "vector"]
# Embedding source for a vector project: an OpenAI-compatible provider or the
# local fastembed model.
MemoryEmbedMode = Literal["provider", "local"]

# Project-level tool authorization: "restricted" = every non-whitelisted tool
# asks (default), "auto" = full access, no asks (SafetyGuard still applies).
PermissionMode = Literal["restricted", "auto"]


class Project(BaseModel):
    id: str
    name: str
    description: str = ""
    local_path: str = ""
    is_default: bool = False
    memory_enabled: bool = True
    memory_backend: MemoryBackend = "file"
    # True once memory has been saved as ENABLED at least once. From then on the
    # backend choice is frozen: it decides the on-disk storage layout, so
    # switching it would orphan whatever is already stored. Toggling
    # ``memory_enabled`` off (and on again) stays allowed — only the backend is
    # locked. Surfaced so the UI can disable the selector and explain why.
    memory_backend_locked: bool = False
    # Vector-memory model choices, owned by the PROJECT (materialized from the
    # global defaults at creation; global changes never touch existing
    # projects). None provider/model = follow the conversation model.
    memory_llm_provider_id: str | None = None
    memory_llm_model: str | None = None
    memory_embed_mode: MemoryEmbedMode = "provider"
    memory_embed_provider_id: str | None = None
    memory_embed_model: str | None = None
    # Recalled memories injected per turn (vector backend). None = default 10.
    memory_recall_top_k: int | None = None
    mcp_auto_attach: bool = True
    skill_auto_attach: bool = True
    permission_mode: PermissionMode = "restricted"
    created_at: datetime


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    local_path: str = ""
    # Optional — when omitted, inherits from AgentSettings.default_memory_*.
    memory_enabled: bool | None = None
    memory_backend: MemoryBackend | None = None
    # Memory-model group: when NONE of these is sent, the global defaults are
    # materialized instead (`model_fields_set` decides sent-ness).
    memory_llm_provider_id: str | None = None
    memory_llm_model: str | None = None
    memory_embed_mode: MemoryEmbedMode | None = None
    memory_embed_provider_id: str | None = None
    memory_embed_model: str | None = None
    memory_recall_top_k: int | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    local_path: str | None = None
    memory_enabled: bool | None = None
    # Only accepted while the project has never had memory enabled (see
    # ``Project.memory_backend_locked``); rejected with 400 afterwards.
    memory_backend: MemoryBackend | None = None
    # Sent as a whole group (the modal owns the section): if ANY of the five is
    # present the stored group is replaced from the body.
    memory_llm_provider_id: str | None = None
    memory_llm_model: str | None = None
    memory_embed_mode: MemoryEmbedMode | None = None
    memory_embed_provider_id: str | None = None
    memory_embed_model: str | None = None
    memory_recall_top_k: int | None = None
    mcp_auto_attach: bool | None = None
    skill_auto_attach: bool | None = None
    permission_mode: PermissionMode | None = None


# The five per-project memory-model fields, shared by create/update handling.
MEMORY_MODEL_FIELDS = (
    "memory_llm_provider_id",
    "memory_llm_model",
    "memory_embed_mode",
    "memory_embed_provider_id",
    "memory_embed_model",
    "memory_recall_top_k",
)
