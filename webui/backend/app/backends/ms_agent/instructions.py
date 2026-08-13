"""Instructions adapter — global via PersonalizationSettings.global_instruction,
project via Project.instruction (ProjectManager)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.backends.errors import BadRequest
from app.backends.ms_agent.common import home, pm
from app.backends.ms_agent.settings_store import settings_lock
from app.schemas.instruction import Instruction, InstructionUpsert


def _ps():
    from ms_agent.personalization import PersonalizationSettings

    return PersonalizationSettings(global_dir=home())


def _parse_scope(scope: str) -> tuple[str, str | None]:
    if scope == "global":
        return "global", None
    if scope.startswith("project:"):
        pid = scope.split(":", 1)[1]
        if pm().get(pid) is None:
            raise BadRequest(f"unknown project: {pid}")
        return "project", pid
    raise BadRequest(f"invalid scope: {scope!r}")


def get_instruction(scope: str) -> Instruction:
    kind, pid = _parse_scope(scope)
    if kind == "global":
        with settings_lock():
            content = _ps().load().global_instruction
    else:
        content = pm().get(pid).instruction or ""
    return Instruction(scope=scope, content=content, updated_at=datetime.now(timezone.utc))


def upsert_instruction(scope: str, body: InstructionUpsert) -> Instruction:
    from ms_agent.personalization import PersonalizationConfig

    kind, pid = _parse_scope(scope)
    if kind == "global":
        with settings_lock():
            ps = _ps()
            cur = ps.load()
            ps.save(
                PersonalizationConfig(
                    global_instruction=body.content,
                    memory_enabled=cur.memory_enabled,
                    memory_backend=cur.memory_backend,
                )
            )
    else:
        pm().update(pid, instruction=body.content)
    return Instruction(scope=scope, content=body.content, updated_at=datetime.now(timezone.utc))
