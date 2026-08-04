from datetime import datetime

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
