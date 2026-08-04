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


class McpUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    transport: Transport | None = None
    endpoint: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None
    env: dict | None = None
    headers: dict | None = None


class McpHealth(BaseModel):
    """Live reachability of an enabled MCP server (real connect+initialize).
    `id` matches the Mcp row so the frontend can join. When healthy is False,
    `error` is a short reason (e.g. 'Session terminated', 'timed out')."""
    id: str
    name: str
    scope: str
    healthy: bool
    error: str | None = None
