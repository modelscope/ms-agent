"""Projects adapter — ProjectManager + sidecar (description / auto-attach)."""
from __future__ import annotations

from app.backends.errors import BadRequest, NotFound
from app.backends.ms_agent import sidecar
from app.backends.ms_agent.common import home, pm
from app.backends.ms_agent.mapping import project_to_schema
from app.schemas.project import Project, ProjectCreate, ProjectUpdate


def _memory_defaults() -> tuple[bool, str]:
    """New-project memory defaults come from the global personalization block
    (what the agent-settings page writes)."""
    from ms_agent.personalization import PersonalizationSettings

    cfg = PersonalizationSettings(global_dir=home()).load()
    return bool(cfg.memory_enabled), (cfg.memory_backend or "file")


def _is_default(pid: str) -> bool:
    from ms_agent.project.types import DEFAULT_PROJECT_ID

    return pid == DEFAULT_PROJECT_ID


def list_projects() -> list[Project]:
    from ms_agent.project.types import DEFAULT_PROJECT_ID

    projects = pm().list()
    projects.sort(key=lambda p: (p.id != DEFAULT_PROJECT_ID, p.created_at))
    return [project_to_schema(p) for p in projects]


def create_project(body: ProjectCreate) -> Project:
    manager = pm()
    default_enabled, default_backend = _memory_defaults()
    mem_enabled = body.memory_enabled if body.memory_enabled is not None else default_enabled
    mem_backend = body.memory_backend if body.memory_backend is not None else default_backend

    if body.local_path:
        # "use an existing folder": path is identity, dedups on reopen.
        proj = manager.open_folder(
            path=body.local_path,
            name=body.name,
            memory_enabled=mem_enabled,
            memory_backend=mem_backend,
        )
    else:
        proj = manager.create(
            name=body.name,
            memory_enabled=mem_enabled,
            memory_backend=mem_backend,
            # The runtime writes products directly under the project dir, so the
            # extra `workspace/` subdir is unused clutter — don't create it.
            init_workspace=False,
        )
    if body.description:
        sidecar.merge("projects", proj.id, {"description": body.description})
    return project_to_schema(proj)


def get_project(pid: str) -> Project:
    proj = pm().get(pid)
    if proj is None:
        raise NotFound("project not found")
    return project_to_schema(proj)


def update_project(pid: str, body: ProjectUpdate) -> Project:
    manager = pm()
    proj = manager.get(pid)
    if proj is None:
        raise NotFound("project not found")

    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name
    if body.local_path is not None:
        fields["path"] = body.local_path
    if body.memory_enabled is not None:
        if _is_default(pid) and body.memory_enabled:
            raise BadRequest("default project cannot enable memory")
        fields["memory_enabled"] = body.memory_enabled
    if fields:
        proj = manager.update(pid, **fields)

    side = {
        k: getattr(body, k)
        for k in (
            "description",
            "mcp_auto_attach",
            "skill_auto_attach",
            "permission_mode",
        )
        if getattr(body, k) is not None
    }
    if side:
        sidecar.merge("projects", pid, side)
    if body.permission_mode is not None:
        # Hot-apply to every live runtime of this project so the very next
        # tool call obeys the new mode — no agent rebuild, no turn restart.
        from app.backends.ms_agent.runtime import registry

        registry.set_project_permission_mode(pid, body.permission_mode)
    return project_to_schema(proj)


def delete_project(pid: str) -> None:
    manager = pm()
    proj = manager.get(pid)
    if proj is None:
        raise NotFound("project not found")
    if _is_default(pid):
        raise BadRequest("cannot delete default project")
    manager.delete(pid)  # removes the project dir incl. its sessions
    sidecar.drop("projects", pid)
    sidecar.drop("memory", pid)
