from fastapi import APIRouter, HTTPException

from app.core import store
from app.core.envelope import EnvelopeRoute
from app.core.settings import settings
from app.schemas.project import Project, ProjectCreate, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"],
                   route_class=EnvelopeRoute)


def _ms() -> bool:
    return settings.agent_backend == "ms_agent"


@router.get("")
def list_projects() -> list[Project]:
    if _ms():
        from app.backends.ms_agent import projects

        return projects.list_projects()
    # Default project first, then named ones by creation order.
    rows = sorted(
        store.projects.values(),
        key=lambda p: (not p["is_default"], p["created_at"]),
    )
    return [Project.model_validate(p) for p in rows]


@router.post("", status_code=201)
def create_project(body: ProjectCreate) -> Project:
    if _ms():
        from app.backends.ms_agent import projects

        return projects.create_project(body)
    pid = store.new_id("p-")
    s = store.agent_settings
    row = {
        "id":
        pid,
        "name":
        body.name,
        "description":
        body.description,
        "local_path":
        body.local_path,
        "is_default":
        False,
        "memory_enabled":
        (body.memory_enabled if body.memory_enabled is not None else s.get(
            "default_memory_enabled", True)),
        "memory_backend":
        (body.memory_backend if body.memory_backend is not None else s.get(
            "default_memory_backend", "file")),
        "mcp_auto_attach":
        True,
        "skill_auto_attach":
        True,
        "created_at":
        store.now(),
    }
    store.projects[pid] = row
    return Project.model_validate(row)


@router.get("/{project_id}")
def get_project(project_id: str) -> Project:
    if _ms():
        from app.backends.ms_agent import projects

        return projects.get_project(project_id)
    row = store.projects.get(project_id)
    if not row:
        raise HTTPException(404, "project not found")
    return Project.model_validate(row)


@router.patch("/{project_id}")
def update_project(project_id: str, body: ProjectUpdate) -> Project:
    if _ms():
        from app.backends.ms_agent import projects

        return projects.update_project(project_id, body)
    row = store.projects.get(project_id)
    if not row:
        raise HTTPException(404, "project not found")
    if body.name is not None:
        row["name"] = body.name
    if body.description is not None:
        row["description"] = body.description
    if body.local_path is not None:
        row["local_path"] = body.local_path
    if body.memory_enabled is not None:
        if row["is_default"] and body.memory_enabled:
            raise HTTPException(400, "default project cannot enable memory")
        row["memory_enabled"] = body.memory_enabled
    if body.mcp_auto_attach is not None:
        row["mcp_auto_attach"] = body.mcp_auto_attach
    if body.skill_auto_attach is not None:
        row["skill_auto_attach"] = body.skill_auto_attach
    if body.permission_mode is not None:
        row["permission_mode"] = body.permission_mode
    return Project.model_validate(row)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str) -> None:
    if _ms():
        from app.backends.ms_agent import projects

        return projects.delete_project(project_id)
    row = store.projects.get(project_id)
    if not row:
        raise HTTPException(404, "project not found")
    if row["is_default"]:
        raise HTTPException(400, "cannot delete default project")
    del store.projects[project_id]
    # Cascade: orphan sessions move to default; drop project-owned resources.
    for s in store.sessions.values():
        if s.get("project_id") == project_id:
            s["project_id"] = store.DEFAULT_PROJECT_ID
    store.memory_files.pop(project_id, None)
    store.workspace_files.pop(project_id, None)
    # Remove project-scoped instructions
    store.instructions.pop(f"project:{project_id}", None)
    # Remove project-scoped MCPs
    scope_key = f"project:{project_id}"
    mcp_ids_to_remove = [
        k for k, v in store.mcps.items() if v.get("scope") == scope_key
    ]
    for mid in mcp_ids_to_remove:
        del store.mcps[mid]
    # Remove project-scoped skills
    skill_ids_to_remove = [
        k for k, v in store.skills.items() if v.get("scope") == scope_key
    ]
    for sid in skill_ids_to_remove:
        del store.skills[sid]
