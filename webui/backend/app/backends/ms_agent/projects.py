"""Projects adapter — ProjectManager + sidecar (description / auto-attach)."""
from __future__ import annotations

from app.backends.errors import BadRequest, NotFound
from app.backends.ms_agent import sidecar
from app.backends.ms_agent.common import home, pm
from app.backends.ms_agent.mapping import _memory_backend, project_to_schema
from app.schemas.project import (
    MEMORY_MODEL_FIELDS,
    Project,
    ProjectCreate,
    ProjectUpdate,
)


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
    projects = pm().list()
    # Plain creation order: the default project is an ordinary project here, so
    # it takes whatever position its own created_at gives it.
    projects.sort(key=lambda p: p.created_at)
    return [project_to_schema(p) for p in projects]


def _memory_models_from(body, defaults: dict) -> dict:
    """The project's memory-model group: the body's values when the group was
    sent, else the global defaults — materialized ONCE here so later changes
    to the global defaults never touch this project."""
    sent = bool(set(MEMORY_MODEL_FIELDS) & body.model_fields_set)
    if sent:
        mode = body.memory_embed_mode
    else:
        mode = defaults.get("embed_mode")
    return {
        "llm_provider_id": body.memory_llm_provider_id if sent else defaults.get("llm_provider_id"),
        "llm_model": body.memory_llm_model if sent else defaults.get("llm_model"),
        "embed_mode": mode if mode in ("provider", "local") else "provider",
        "embed_provider_id": body.memory_embed_provider_id if sent else defaults.get("embed_provider_id"),
        "embed_model": body.memory_embed_model if sent else defaults.get("embed_model"),
        "recall_top_k": body.memory_recall_top_k if sent else defaults.get("recall_top_k"),
    }


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
    side: dict = {
        "memory_models": _memory_models_from(
            body, sidecar.get("agent_settings", "memory_models", {}) or {})
    }
    if body.description:
        side["description"] = body.description
    if mem_enabled:
        # Created with memory on: its storage is live, so freeze the backend
        # from the start (same rule as enabling it later).
        side["memory_backend_locked"] = True
    sidecar.merge("projects", proj.id, side)
    return project_to_schema(proj)


def get_project(pid: str) -> Project:
    proj = pm().get(pid)
    if proj is None:
        raise NotFound("project not found")
    return project_to_schema(proj)


def _backend_locked(proj) -> bool:
    """Has this project ever had memory saved as enabled?

    The memory backend decides the on-disk storage layout, so once storage is
    live the choice is frozen — switching it would orphan what is already
    stored. Currently-enabled counts as locked even without the sidecar flag,
    which covers projects created before the flag was introduced.
    """
    meta = sidecar.get("projects", proj.id, {}) or {}
    return bool(meta.get("memory_backend_locked", False)
                or proj.memory_enabled)


def update_project(pid: str, body: ProjectUpdate) -> Project:
    manager = pm()
    proj = manager.get(pid)
    if proj is None:
        raise NotFound("project not found")

    locked = _backend_locked(proj)
    if (body.memory_backend is not None
            and body.memory_backend != _memory_backend(proj.memory_backend)
            and locked):
        raise BadRequest(
            "memory backend cannot be changed once memory has been enabled")

    # The project directory is its identity and holds all of its data. The SDK's
    # update() only rewrites the `path` field — it does not move anything on
    # disk — so accepting a change here would leave the project pointing at a
    # directory that has none of its sessions/workspace/memory. Re-sending the
    # unchanged value is fine (the edit form submits the whole shape).
    if (body.local_path is not None
            and body.local_path != (proj.path or "")):
        raise BadRequest("project path cannot be changed after creation")

    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name
    if body.memory_enabled is not None:
        fields["memory_enabled"] = body.memory_enabled
    if body.memory_backend is not None and not locked:
        fields["memory_backend"] = body.memory_backend
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
    # Memory-model group replaces as a whole when any of it was sent (the
    # modal owns the section and always sends all five together).
    if set(MEMORY_MODEL_FIELDS) & body.model_fields_set:
        mode = body.memory_embed_mode
        side["memory_models"] = {
            "llm_provider_id": body.memory_llm_provider_id,
            "llm_model": body.memory_llm_model,
            "embed_mode": mode if mode in ("provider", "local") else "provider",
            "embed_provider_id": body.memory_embed_provider_id,
            "embed_model": body.memory_embed_model,
            "recall_top_k": body.memory_recall_top_k,
        }
    # Enabling memory freezes the backend from here on — record it so the lock
    # survives the user turning memory back off.
    if body.memory_enabled:
        side["memory_backend_locked"] = True
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
