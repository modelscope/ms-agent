from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ProviderKind = Literal["builtin", "custom"]
Protocol = Literal["openai", "anthropic"]


class Provider(BaseModel):
    id: str
    kind: ProviderKind
    name: str
    base_url: str = ""
    api_key_masked: str = ""
    protocol: Protocol = "openai"
    enabled: bool = True
    default_generation_params: dict = Field(default_factory=dict)
    # Read-only: the generation params the backend applies by default for this
    # provider (currently the protocol-derived ``extra_body.enable_thinking``),
    # so the settings UI can surface the thinking default in the params JSON
    # even before the user sets anything. A model's advanced_params can override.
    generation_defaults: dict = Field(default_factory=dict)
    created_at: datetime


class ProviderCreate(BaseModel):
    # custom providers only — builtin ones are seeded
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,40}$")
    name: str = Field(min_length=1, max_length=80)
    base_url: str = ""
    protocol: Protocol = "openai"
    default_generation_params: dict = Field(default_factory=dict)


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    base_url: str | None = None
    api_key: str | None = None  # plain, server masks on read
    protocol: Protocol | None = None
    enabled: bool | None = None
    default_generation_params: dict | None = None
