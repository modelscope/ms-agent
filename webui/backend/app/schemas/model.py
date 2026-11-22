from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ReasoningEffort = Literal["auto", "off", "on", "minimal", "low", "medium", "high", "xhigh", "max"]


class CatalogMetadata(BaseModel):
    source: str = "models.dev"
    revision: str
    provider_id: str
    context_limit: int | None = None
    input_limit: int | None = None
    output_limit: int | None = None
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    reasoning: bool | None = None
    tool_call: bool | None = None


class ContextBudget(BaseModel):
    context_limit: int
    model_context_limit: int | None = None
    input_limit: int | None = None
    output_reserve: int
    compression_threshold: int
    compression_ratio: float = 0.85


class GenerationDefaults(BaseModel):
    effort: str = "auto"
    effort_options: list[str] = Field(default_factory=list)
    effective: str = "auto"
    wire_params: dict = Field(default_factory=dict)
    family: str = ""
    extra_hint: str = ""
    reasoning: bool | None = None
    reasoning_control: str = "unknown"
    raw_override: bool = False
    configuration_error: str = ""
    catalog: CatalogMetadata | None = None
    context_budget: ContextBudget | None = None
    effective_supports_vision: bool = False


class Model(BaseModel):
    id: str
    provider_id: str
    name: str
    display_name: str = ""
    is_builtin: bool = False
    advanced_params: dict = Field(default_factory=dict)
    supports_vision: bool | None = None
    effective_supports_vision: bool = False
    context_limit: int | None = None
    catalog: CatalogMetadata | None = None
    context_budget: ContextBudget | None = None
    generation_defaults: GenerationDefaults | None = None
    created_at: datetime


class ModelCreate(BaseModel):
    provider_id: str
    name: str = Field(min_length=1, max_length=160)
    display_name: str = ""
    advanced_params: dict = Field(default_factory=dict)
    reasoning_effort: ReasoningEffort | None = None
    supports_vision: bool | None = None
    context_limit: int | None = Field(default=None, ge=1024, le=100_000_000)


class ModelUpdate(BaseModel):
    display_name: str | None = None
    advanced_params: dict | None = None
    reasoning_effort: ReasoningEffort | None = None
    supports_vision: bool | None = None
    context_limit: int | None = Field(default=None, ge=1024, le=100_000_000)
