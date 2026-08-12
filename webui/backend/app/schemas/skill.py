from datetime import datetime

from pydantic import BaseModel, Field


class Skill(BaseModel):
    id: str
    name: str
    kind: str = "file-type"
    content: str = ""
    enabled: bool = True
    scope: str
    created_at: datetime


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = "file-type"
    content: str = ""
    enabled: bool = True
    scope: str


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: str | None = None
    content: str | None = None
    enabled: bool | None = None


class SkillFile(BaseModel):
    """One file inside a skill's on-disk directory (relative path)."""

    path: str
    size: int | None = None


class SkillFileContent(BaseModel):
    path: str
    # None ⇒ the file is binary / not valid UTF-8 (frontend shows a notice).
    content: str | None = None
