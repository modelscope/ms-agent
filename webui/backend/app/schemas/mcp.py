from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Transport = Literal["stdio", "http", "sse", "streamable_http"]


class Mcp(BaseModel):
    id: str
    name: str
    description: str = ""
    transport: Transport = "stdio"
    endpoint: str
    enabled: bool = True
    scope: str  # 'global' | 'project:<id>'
    # Structured connection extras (round-tripped by the ms_agent backend):
    # env for stdio servers, headers for remote (sse/http) servers.
    env: dict = Field(default_factory=dict)
    headers: dict = Field(default_factory=dict)
    startup_timeout: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    created_at: datetime


class McpCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    transport: Transport = "stdio"
    endpoint: str = Field(min_length=1)
    enabled: bool = True
    scope: str
    env: dict = Field(default_factory=dict)
    headers: dict = Field(default_factory=dict)
    startup_timeout: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class McpReplace(BaseModel):
    """Desired full contents of one scope, in display order.

    Used by the raw-JSON editor: the document it saves IS the whole scope, so it
    is applied as a single atomic replace rather than a delete-all + re-create
    sequence from the client.
    """

    scope: str
    servers: list[McpCreate] = Field(default_factory=list)


class McpUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    transport: Transport | None = None
    endpoint: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None
    env: dict | None = None
    headers: dict | None = None
    startup_timeout: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class McpHealth(BaseModel):
    """Independent diagnostic, not the current session's connection state.

    None means the command exists but the connection has not been verified.
    A connection-level success includes initialize and list_tools.
    """
    id: str
    name: str
    scope: str
    healthy: bool | None
    level: Literal["command", "connection"] = "command"
    checked_at: float = 0
    expires_at: float = 0
    error: str | None = None


class McpReconnect(BaseModel):
    scheduled: int
    status: Literal["scheduled"] = "scheduled"
