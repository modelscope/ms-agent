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
    # custom providers only — builtin ones are seeded. Length matches the common
    # slug / DNS-label ceiling (63/64) rather than the older, arbitrary 41.
    # Letters of either case are fine; the shape only has to stay an identifier
    # (no spaces or punctuation) because this is the permanent settings.json key.
    # Uniqueness is exact, so `OpenAI` alongside builtin `openai` is allowed and
    # is simply a separate provider — which means every lookup keyed by this id
    # has to use it verbatim (see config._apply_model_compatibility).
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    # Optional: a blank display name falls back to the id, which is what both the
    # SDK's add_provider and the read mapping already do for entries without one.
    name: str = Field(default="", max_length=80)
    base_url: str = ""
    protocol: Protocol = "openai"
    default_generation_params: dict = Field(default_factory=dict)


class ProviderUpdate(BaseModel):
    # "" is meaningful (unlike None = leave alone): it clears the user's display
    # name so the default shows again — hence no min_length here.
    name: str | None = Field(default=None, max_length=80)
    base_url: str | None = None
    api_key: str | None = None  # plain, server masks on read
    protocol: Protocol | None = None
    enabled: bool | None = None
    default_generation_params: dict | None = None


class ProviderOrder(BaseModel):
    # Full list of provider ids in display order. Unknown ids are dropped and
    # any known id left out keeps its default position after the listed ones.
    order: list[str] = Field(default_factory=list)
