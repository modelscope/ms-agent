"""Instructions adapter — file-backed.

- global  -> ~/.ms_agent/AGENTS.md            (the seeded file keeps its
             guidance header; the UI edits only the user region below it)
- project -> <project>/.ms_agent/AGENTS.md    (the framework-private slot,
             whole-file edit)

The PROJECT ROOT ``AGENTS.md`` is deliberately hands-off for the UI: AI-native
repos commit their own root AGENTS.md for coding agents, and a settings box
silently rewriting a git-tracked team file is exactly the kind of surprise we
must not cause. The SDK still READS the root file (shared slot, injected
before the private slot) — it just is never written from here.

Legacy locations are migrated once on first access and then cleared:
- settings.json personalization.global_instruction -> global AGENTS.md
- project.json ``instruction``            -> <project>/.ms_agent/AGENTS.md
The SDK reads the files first and only falls back to the legacy fields while
the files are still empty, so behavior is continuous during the migration.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from contextlib import ExitStack, contextmanager

from ms_agent.utils.atomic_file import atomic_write_text
from ms_agent.utils.file_lock import file_lock, locked

from app.backends.errors import BadRequest
from app.backends.ms_agent.common import home, pm
from app.backends.ms_agent.settings_store import settings_lock
from app.schemas.instruction import Instruction, InstructionUpsert

_NAME = "AGENTS.md"


def _wf():
    from ms_agent.prompting import workspace_files

    return workspace_files


def _ps():
    from ms_agent.personalization import PersonalizationSettings

    return PersonalizationSettings(global_dir=home())


def _parse_scope(scope: str) -> tuple[str, str | None]:
    if scope == "global":
        return "global", None
    if scope.startswith("project:"):
        pid = scope.split(":", 1)[1]
        if pm().get(pid) is None:
            raise BadRequest("Project not found.")
        return "project", pid
    raise BadRequest("Invalid location.")


# ── global scope: region edit under the seeded header ───────────────────────


@locked(lambda wf: Path(home()) / "settings.json")
@locked(lambda wf: Path(home()) / ".prompt-files")
def _global_read(wf) -> tuple[str, str]:
    """(full text, user region) of the global AGENTS.md after migration."""
    text = wf.read_home_file(_NAME)
    user_region = wf.get_free_region(text)
    if not user_region.strip():
        # One-time migration: move the legacy settings field into the file.
        with settings_lock():
            ps = _ps()
            cur = ps.load()
            legacy = (cur.global_instruction or "").strip()
            if legacy:
                text = wf.set_free_region(text, legacy + "\n")
                wf.write_home_file(_NAME, text)
                user_region = wf.get_free_region(text)
                from ms_agent.personalization import PersonalizationConfig

                ps.save(
                    PersonalizationConfig(
                        global_instruction="",
                        memory_enabled=cur.memory_enabled,
                        memory_backend=cur.memory_backend,
                    ))
    return text, user_region


@locked(lambda wf, content: Path(home()) / "settings.json")
@locked(lambda wf, content: Path(home()) / ".prompt-files")
def _global_write(wf, content: str) -> None:
    text = wf.read_home_file(_NAME)
    body = content.strip()
    text = wf.set_free_region(text, body + "\n" if body else "")
    wf.write_home_file(_NAME, text)


# ── project scope: plain whole-file edit of the PRIVATE slot ────────────────


def _project_file(pid: str) -> Path:
    from ms_agent.project.paths import local_internal_dir

    return Path(local_internal_dir(pm().get(pid).path)) / _NAME


@locked(lambda pid, *args: Path(home()) / "projects")
@locked(lambda pid, *args: _project_file(pid))
def _project_read(pid: str) -> str:
    path = _project_file(pid)
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        content = ""
    if not content.strip():
        legacy = (pm().get(pid).instruction or "").strip()
        if legacy:
            content = legacy + "\n"
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, content)
            pm().update(pid, instruction="")
    return content


@locked(lambda pid, *args: Path(home()) / "projects")
@locked(lambda pid, *args: _project_file(pid))
def _project_write(pid: str, content: str) -> None:
    path = _project_file(pid)
    body = content.strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, body + "\n" if body else "")


# ── API surface (unchanged shapes) ───────────────────────────────────────────


def get_instruction(scope: str) -> Instruction:
    kind, pid = _parse_scope(scope)
    if kind == "global":
        _, user_region = _global_read(_wf())
        content = user_region.strip()
    else:
        content = _project_read(pid).strip()
    return Instruction(
        scope=scope, content=content, updated_at=datetime.now(timezone.utc))


def upsert_instruction(scope: str, body: InstructionUpsert) -> Instruction:
    kind, pid = _parse_scope(scope)
    if kind == "global":
        wf = _wf()
        _global_read(wf)  # run migration first so we never clobber legacy text
        _global_write(wf, body.content)
    else:
        _project_read(pid)
        _project_write(pid, body.content)
    return Instruction(
        scope=scope, content=body.content.strip(),
        updated_at=datetime.now(timezone.utc))
