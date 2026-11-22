from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Skill(BaseModel):
    id: str
    name: str
    kind: str = "file-type"
    content: str = ""
    enabled: bool = True
    scope: str
    created_at: datetime
    # managed: copied into ms-agent's skills tree; legacy-path: an older
    # skills.json reference; standard: discovered from .agents/skills; content:
    # old sidecar-only row.  The UI uses this to describe deletion accurately.
    origin: str = "content"
    removable: bool = True
    installation: dict | None = None
    update: dict | None = None
    capabilities: dict[str, bool] = Field(default_factory=dict)


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = "file-type"
    content: str = ""
    enabled: bool = True
    scope: str
    # Bundle imports only. False (default) rejects a name that already exists in
    # the scope; True replaces that skill's directory. Importing used to silently
    # write a second `<name>-2` directory, which the registry then shadowed — the
    # caller saw success while nothing changed and a stray copy accumulated on
    # disk. Callers must now choose explicitly.
    overwrite: bool = False


class SkillPathImport(BaseModel):
    path: str = Field(min_length=1)
    scope: str
    overwrite: bool = False


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


class SkillSourceInspect(BaseModel):
    scope: str
    source: str = Field(min_length=1, max_length=2048)


class SkillInstallPlan(BaseModel):
    scope: str
    source_snapshot_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    candidate_ids: list[str] = Field(min_length=1, max_length=100)


class SkillUpdateCheck(BaseModel):
    scope: str
    skill_ids: list[str] | None = Field(default=None, max_length=100)
    force: bool = False


class SkillLinkPlan(BaseModel):
    source_snapshot_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    candidate_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class SkillPlanApply(BaseModel):
    local_changes_policy: Literal["abort", "replace"] = "abort"
    request_id: str = Field(min_length=1, max_length=128)
    acknowledge_risk: bool = False


class SkillManagementSettings(BaseModel):
    auto_check: bool = True
