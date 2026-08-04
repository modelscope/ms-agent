from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


MemoryBackend = Literal["file", "vector"]

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


class ProjectUpdate(BaseModel):
    # Note: memory_backend is intentionally absent — spec disallows runtime
    # switching of the backend once a project exists.
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    local_path: str | None = None
    memory_enabled: bool | None = None
    mcp_auto_attach: bool | None = None
    skill_auto_attach: bool | None = None
    permission_mode: PermissionMode | None = None
