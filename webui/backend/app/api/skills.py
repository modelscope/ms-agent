from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from app.core.envelope import EnvelopeRoute
from app.core.filetypes import raw_headers
from app.schemas.skill import (
    Skill,
    SkillCreate,
    SkillFile,
    SkillFileContent,
    SkillPathImport,
    SkillUpdate,
    SkillSourceInspect,
    SkillInstallPlan,
    SkillUpdateCheck,
    SkillPlanApply,
    SkillManagementSettings,
    SkillLinkPlan,
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


@router.post("/import-path", status_code=201)
def import_skills_from_path(body: SkillPathImport) -> list[Skill]:
    """Copy every Skill found below a server-readable local directory."""
    from app.backends.ms_agent import skills

    return skills.import_skills_from_path(body)


@router.get("/management-settings")
def management_settings():
    from app.backends.ms_agent import skill_management as management
    return management.settings()


@router.patch("/management-settings")
def update_management_settings(body: SkillManagementSettings):
    from app.backends.ms_agent import skill_management as management
    return management.save_settings(body.auto_check)


@router.post("/sources/inspect", status_code=202)
async def inspect_source(body: SkillSourceInspect):
    from app.backends.ms_agent import skill_management as management
    return management.submit_inspect(body.scope, body.source)


@router.post("/install-plans", status_code=202)
async def prepare_install(body: SkillInstallPlan):
    from app.backends.ms_agent import skill_management as management
    return management.submit_install(body.scope, body.source_snapshot_id, body.candidate_ids)


@router.post("/update-checks", status_code=202)
async def check_updates(body: SkillUpdateCheck):
    from app.backends.ms_agent import skill_management as management
    return management.submit_check(body.scope, body.force, body.skill_ids)


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str):
    from app.backends.ms_agent import skill_management as management
    return management.guarded_call(management.service().get_plan, plan_id).to_dict()


@router.get("/plans/{plan_id}/diff")
def get_plan_diff(plan_id: str, item_id: str, path: str):
    from app.backends.ms_agent import skill_management as management
    return management.guarded_call(management.service().diff, plan_id, item_id, path)


@router.post("/plans/{plan_id}/apply", status_code=202)
async def apply_plan(plan_id: str, body: SkillPlanApply):
    from app.backends.ms_agent import skill_management as management
    return management.submit_apply(plan_id, body.local_changes_policy,
                                    body.request_id, body.acknowledge_risk)


@router.get("/operations/{operation_id}")
def get_operation(operation_id: str):
    from app.backends.ms_agent import skill_management as management
    return management.guarded_call(management.operations().get, operation_id)


@router.delete("/operations/{operation_id}")
async def cancel_operation(operation_id: str):
    from app.backends.ms_agent import skill_management as management
    management.guarded_call(management.operations().get, operation_id)
    return await management.operations().cancel(operation_id)


@router.post("/{skill_id}/update-plans", status_code=202)
async def prepare_update(skill_id: str):
    from app.backends.ms_agent import skill_management as management
    return management.guarded_call(management.submit_replace, skill_id, "update")


@router.post("/{skill_id}/link-plans", status_code=202)
async def prepare_link(skill_id: str, body: SkillLinkPlan):
    from app.backends.ms_agent import skill_management as management
    return management.guarded_call(management.submit_link, skill_id,
                                   body.source_snapshot_id, body.candidate_id)


@router.post("/{skill_id}/restore-plans", status_code=202)
async def prepare_restore(skill_id: str):
    from app.backends.ms_agent import skill_management as management
    return management.guarded_call(management.submit_replace, skill_id, "restore")


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


@router.get("/{skill_id}/raw/{file_path:path}")
def raw_skill_file(skill_id: str, file_path: str) -> Response:
    """Raw bytes of one skill file, for the assets a previewed document pulls in.
    The path is the URL tail so those `./img/a.png` references resolve here.
    """
    from app.backends.ms_agent import skills

    target, ctype = skills.raw_skill_file(skill_id, file_path)
    return FileResponse(target, media_type=ctype, headers=raw_headers(ctype))


@router.patch("/{skill_id}")
def update_skill(skill_id: str, body: SkillUpdate) -> Skill:
    from app.backends.ms_agent import skills

    return skills.update_skill(skill_id, body)


@router.delete("/{skill_id}", status_code=204)
def delete_skill(skill_id: str) -> None:
    from app.backends.ms_agent import skills

    return skills.delete_skill(skill_id)
