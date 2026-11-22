from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ModelPurpose = Literal["unknown", "chat", "embedding"]

class Model(BaseModel):
    id: str
    provider_id: str
    name: str
    display_name: str = ""
    is_builtin: bool = False
    advanced_params: dict = Field(default_factory=dict)
    purpose: ModelPurpose = "unknown"
    #: Whether this model may be shown image attachments. Tri-state on purpose:
    #: None = "nobody has said", which lets the SDK fall back to the provider's
    #: declared capability and then to runtime learning (a model that rejects an
    #: image is remembered and never shown one again). A hard default either way
    #: is worse — False makes a capable model silently ignore attachments, True
    #: burns a 400 on every text-only model's first use.
    supports_vision: bool | None = None
    created_at: datetime


class ModelCreate(BaseModel):
    provider_id: str
    name: str = Field(min_length=1, max_length=160)
    display_name: str = ""
    advanced_params: dict = Field(default_factory=dict)
    #: Set from the "image understanding" switch on the create form.
    supports_vision: bool | None = None
    purpose: ModelPurpose = "unknown"


class ModelUpdate(BaseModel):
    display_name: str | None = None
    advanced_params: dict | None = None
    supports_vision: bool | None = None
    purpose: ModelPurpose | None = None


class GenerationDefaults(BaseModel):
    """What the runtime will send for this provider/model before the user edits
    anything — the read-only half of the advanced-params editor.

    Deliberately only about thinking. Sampling knobs (temperature, top_p, ...)
    are not surfaced: reasoning models ignore them (DeepSeek's docs say so
    outright) and the backend already strips temperature unless the user turns
    it on, so showing them would advertise settings that do nothing."""

    #: Canonical knob and its current value, e.g. ``auto``.
    effort: str = "auto"
    #: Every value the editor accepts, weakest to strongest.
    effort_options: list[str] = Field(default_factory=list)
    #: The tier after clamping to what this endpoint supports (``auto`` stays
    #: ``auto``). Differs from ``effort`` when e.g. ``medium`` is asked of an
    #: endpoint that only has low/high/max.
    effective: str = "auto"
    #: The params that will actually be sent. ``{}`` means nothing about
    #: thinking ships and the model's own default stands.
    wire_params: dict = Field(default_factory=dict)
    #: Endpoint dialect (``dashscope``, ``deepseek``, ``unknown``, ...).
    family: str = ""
    #: Raw keys this endpoint also understands, shown as an example of what may
    #: be added by hand. We never send them — their defaults are vendor-tuned.
    extra_hint: str = ""
