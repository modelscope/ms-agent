"""Projects adapter — ProjectManager + sidecar (description / auto-attach)."""
from __future__ import annotations

from pathlib import Path
from ms_agent.utils.file_lock import locked

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


@locked(lambda *args, **kwargs: Path(home()) / "projects")
def create_project(body: ProjectCreate) -> Project:
    manager = pm()
    default_enabled, default_backend = _memory_defaults()
    mem_enabled = body.memory_enabled if body.memory_enabled is not None else default_enabled
    mem_backend = body.memory_backend if body.memory_backend is not None else default_backend

    if body.local_path:
        from ms_agent.project.paths import project_key

        existing = manager.get(project_key(str(Path(body.local_path).expanduser().resolve())))
        if existing is not None:
            return project_to_schema(existing)
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
        raise NotFound("Project not found.")
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


@locked(lambda *args, **kwargs: Path(home()) / "projects")
@locked(lambda *args, **kwargs: Path(home()) / "webui_meta.json")
def _save_project_update(pid: str, body: ProjectUpdate) -> tuple[Project, bool]:
    manager = pm()
    proj = manager.get(pid)
    if proj is None:
        raise NotFound("Project not found.")

    locked = _backend_locked(proj)
    if (body.memory_backend is not None
            and body.memory_backend != _memory_backend(proj.memory_backend)
            and locked):
        raise BadRequest(
            "The memory type cannot be changed once memory has been enabled.")

    # The project directory is its identity and holds all of its data. The SDK's
    # update() only rewrites the `path` field — it does not move anything on
    # disk — so accepting a change here would leave the project pointing at a
    # directory that has none of its sessions/workspace/memory. Re-sending the
    # unchanged value is fine (the edit form submits the whole shape).
    if (body.local_path is not None
            and body.local_path != (proj.path or "")):
        raise BadRequest("The project location cannot be changed after creation.")

    was_enabled = bool(proj.memory_enabled)
    prev_models = (sidecar.get("projects", pid, {}) or {}).get("memory_models")

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
    if set(MEMORY_MODEL_FIELDS) & body.model_fields_set:
        models = dict(prev_models or {})
        for key in MEMORY_MODEL_FIELDS:
            if key in body.model_fields_set:
                models[key.removeprefix("memory_")] = getattr(body, key)
        if models.get("embed_mode") not in ("provider", "local"):
            models["embed_mode"] = "provider"
        side["memory_models"] = models
    # Enabling memory freezes the backend from here on — record it so the lock
    # survives the user turning memory back off.
    if body.memory_enabled:
        side["memory_backend_locked"] = True
    if side:
        sidecar.merge("projects", pid, side)
    memory_changed = (
        (body.memory_enabled is not None
         and bool(body.memory_enabled) != was_enabled)
        or "memory_backend" in fields
        or ("memory_models" in side and side["memory_models"] != prev_models))
    return project_to_schema(proj), memory_changed


def update_project(pid: str, body: ProjectUpdate) -> Project:
    saved, memory_changed = _save_project_update(pid, body)
    from app.backends.ms_agent.runtime import registry

    if body.permission_mode is not None:
        registry.set_project_permission_mode(pid, body.permission_mode)
    if memory_changed:
        registry.discard_project(pid)
    return saved


@locked(lambda *args, **kwargs: Path(home()) / "projects")
def delete_project(pid: str) -> None:
    manager = pm()
    proj = manager.get(pid)
    if proj is None:
        raise NotFound("Project not found.")
    if _is_default(pid):
        raise BadRequest("The default project cannot be deleted.")
    manager.delete(pid)  # removes the project dir incl. its sessions
    sidecar.drop("projects", pid)
    sidecar.drop("memory", pid)
