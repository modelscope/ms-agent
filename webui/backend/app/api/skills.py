from fastapi import APIRouter, HTTPException

from app.core.envelope import EnvelopeRoute
from app.schemas.skill import (
    Skill,
    SkillCreate,
    SkillFile,
    SkillFileContent,
    SkillUpdate,
)

router = APIRouter(prefix="/api/skills", tags=["skills"],
                   route_class=EnvelopeRoute)


@router.get("")
def list_skills(scope: str | None = None) -> list[Skill]:
    from app.backends.ms_agent import skills

    return skills.list_skills(scope)


@router.post("", status_code=201)
def create_skill(body: SkillCreate) -> Skill:
    from app.backends.ms_agent import skills

    return skills.create_skill(body)


@router.get("/{skill_id}")
def get_skill(skill_id: str) -> Skill:
    from app.backends.ms_agent import skills

    return skills.get_skill(skill_id)


@router.get("/{skill_id}/files")
def list_skill_files(skill_id: str) -> list[SkillFile]:
    """Real file listing of the skill's on-disk directory (viewer tree)."""
    from app.backends.ms_agent import skills

    return skills.list_skill_files(skill_id)


@router.get("/{skill_id}/file")
def read_skill_file(skill_id: str, path: str) -> SkillFileContent:
    """UTF-8 content of one skill file; ``content=null`` marks binary."""
    from app.backends.ms_agent import skills

    return skills.read_skill_file(skill_id, path)


@router.patch("/{skill_id}")
def update_skill(skill_id: str, body: SkillUpdate) -> Skill:
    from app.backends.ms_agent import skills

    return skills.update_skill(skill_id, body)


@router.delete("/{skill_id}", status_code=204)
def delete_skill(skill_id: str) -> None:
    from app.backends.ms_agent import skills

    return skills.delete_skill(skill_id)
