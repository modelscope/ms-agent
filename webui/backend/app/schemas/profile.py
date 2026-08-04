from datetime import datetime

from pydantic import BaseModel, Field


class Profile(BaseModel):
    agent_calls_user: str = "User"
    description: str = ""
    updated_at: datetime


class ProfileUpsert(BaseModel):
    agent_calls_user: str | None = Field(default=None, max_length=80)
    description: str | None = None
