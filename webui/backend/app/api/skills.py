from fastapi import APIRouter, HTTPException

from app.core import store
from app.core.envelope import EnvelopeRoute
from app.core.settings import settings
from app.schemas.skill import (
    Skill,
    SkillCreate,
    SkillFile,
    SkillFileContent,
    SkillUpdate,
)

router = APIRouter(prefix="/api/skills", tags=["skills"],
                   route_class=EnvelopeRoute)


def _ms() -> bool:
    return settings.agent_backend == "ms_agent"


def _validate_scope(scope: str) -> str:
    try:
        return store.scope_key(scope)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("")
def list_skills(scope: str | None = None) -> list[Skill]:
    if _ms():
        from app.backends.ms_agent import skills

        return skills.list_skills(scope)
    rows = list(store.skills.values())
    if scope is not None:
        normalized = _validate_scope(scope)
        rows = [s for s in rows if s["scope"] == normalized]
    rows.sort(key=lambda s: s["created_at"])
    return [Skill.model_validate(s) for s in rows]


@router.post("", status_code=201)
def create_skill(body: SkillCreate) -> Skill:
    if _ms():
        from app.backends.ms_agent import skills

        return skills.create_skill(body)
    scope = _validate_scope(body.scope)
    sk_id = store.new_id("sk-")
    row = {
        "id": sk_id,
        "name": body.name,
        "kind": body.kind,
        "content": body.content,
        "enabled": body.enabled,
        "scope": scope,
        "created_at": store.now(),
    }
    store.skills[sk_id] = row
    return Skill.model_validate(row)


@router.get("/{skill_id}")
def get_skill(skill_id: str) -> Skill:
    if _ms():
        from app.backends.ms_agent import skills

        return skills.get_skill(skill_id)
    row = store.skills.get(skill_id)
    if not row:
        raise HTTPException(404, "skill not found")
    return Skill.model_validate(row)


@router.get("/{skill_id}/files")
def list_skill_files(skill_id: str) -> list[SkillFile]:
    """Real file listing of the skill's on-disk directory (viewer tree)."""
    if _ms():
        from app.backends.ms_agent import skills

        return skills.list_skill_files(skill_id)
    row = store.skills.get(skill_id)
    if not row:
        raise HTTPException(404, "skill not found")
    return [SkillFile(path="SKILL.md")]


@router.get("/{skill_id}/file")
def read_skill_file(skill_id: str, path: str) -> SkillFileContent:
    """UTF-8 content of one skill file; ``content=null`` marks binary."""
    if _ms():
        from app.backends.ms_agent import skills

        return skills.read_skill_file(skill_id, path)
    row = store.skills.get(skill_id)
    if not row:
        raise HTTPException(404, "skill not found")
    if path != "SKILL.md":
        raise HTTPException(404, "file not found")
    return SkillFileContent(path="SKILL.md", content=row["content"])


@router.patch("/{skill_id}")
def update_skill(skill_id: str, body: SkillUpdate) -> Skill:
    if _ms():
        from app.backends.ms_agent import skills

        return skills.update_skill(skill_id, body)
    row = store.skills.get(skill_id)
    if not row:
        raise HTTPException(404, "skill not found")
    for field in ("name", "kind", "content", "enabled"):
        value = getattr(body, field)
        if value is not None:
            row[field] = value
    return Skill.model_validate(row)


@router.delete("/{skill_id}", status_code=204)
def delete_skill(skill_id: str) -> None:
    if _ms():
        from app.backends.ms_agent import skills

        return skills.delete_skill(skill_id)
    if skill_id not in store.skills:
        raise HTTPException(404, "skill not found")
    del store.skills[skill_id]
