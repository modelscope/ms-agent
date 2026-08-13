from datetime import datetime

from pydantic import BaseModel, Field


class Model(BaseModel):
    id: str
    provider_id: str
    name: str
    display_name: str = ""
    is_builtin: bool = False
    advanced_params: dict = Field(default_factory=dict)
    created_at: datetime


class ModelCreate(BaseModel):
    provider_id: str
    name: str = Field(min_length=1, max_length=160)
    display_name: str = ""
    advanced_params: dict = Field(default_factory=dict)


class ModelUpdate(BaseModel):
    display_name: str | None = None
    advanced_params: dict | None = None
