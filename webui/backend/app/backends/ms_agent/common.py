"""Shared SDK access helpers: home dir, project/session resolution.

All ms_agent-backed adapters go through here so the global home and the
project/session lookups stay consistent (and honor MS_AGENT_HOME).
"""
from __future__ import annotations

import os

from app.core.settings import settings


def home() -> str:
    """The SDK global home (~/.ms_agent unless MS_AGENT_HOME is set)."""
    from ms_agent.project.paths import global_home

    return str(global_home())


def apply_home_env() -> None:
    """Bridge settings.ms_agent_home -> MS_AGENT_HOME so the SDK's global_home()
    resolves to the WebUI home from any entry point. An explicitly-set
    MS_AGENT_HOME (shell export / test isolation) always wins."""
    if settings.ms_agent_home and not os.environ.get("MS_AGENT_HOME"):
        os.environ["MS_AGENT_HOME"] = os.path.expanduser(settings.ms_agent_home)


# Apply on import. This module is the single entry point for every ms_agent
# adapter, so merely importing it (server, CLI, script, test) pins MS_AGENT_HOME
# before any global_home() read — no more silent fallback to ~/.ms_agent when a
# script/CLI skips the app's boot path.
apply_home_env()


def pm():
    from ms_agent.project import ProjectManager

    return ProjectManager(base_dir=home())


def sm_for(project):
    from ms_agent.project import SessionManager

    return SessionManager(project)


def resolve_project(project_id: str | None):
    """Return the Project for an id, falling back to the default project.

    Raises KeyError if a non-null id does not exist.
    """
    manager = pm()
    if not project_id:
        return manager.get_default_project()
    proj = manager.get(project_id)
    if proj is None:
        raise KeyError(f"project not found: {project_id}")
    return proj


def _is_default_name(name: str) -> bool:
    """SessionManager.create() names sessions 'Session <6hex>' by default."""
    return not name or name.startswith("Session ")


def _is_cheap_title(name: str, first_text: str) -> bool:
    """True when ``name`` is just a leading slice of the first message — a
    placeholder, not a real title. Both cheap-title writers produce prefixes:
    the frontend seeds ``text.slice(0, 60)`` at createSession (the project-page
    first-message path) and ``autoname_session`` uses line1[:40]. Without this
    check those sessions never get an LLM title (``_is_default_name`` sees a
    non-default name and skips the titler)."""
    name = (name or "").strip()
    if not name:
        return True
    head = (first_text or "").strip()
    if not head:
        return False
    return head.startswith(name) or head.splitlines()[0].startswith(name)


def _title_from_text(text: str) -> str:
    return text.strip().splitlines()[0][:40] if text and text.strip() else ""


def _first_user_line(project, session) -> str:
    """Cheap: first line of the first user message in the session log."""
    import json

    from ms_agent.project.paths import global_projects_root

    path = (global_projects_root() / project.id / "sessions" / session.id
            / f"{session.session_key}.jsonl")
    if not path.exists():
        return ""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("role") == "user" and msg.get("content"):
                    return _title_from_text(str(msg["content"]))
    except OSError:
        return ""
    return ""


def autoname_session(project, session, text: str | None = None):
    """Name a still-default session after its first user message (like ChatGPT /
    the TUI). Uses `text` when given (chat's new message), else derives from the
    session log. Returns the (possibly updated) session."""
    if not _is_default_name(session.name):
        return session
    title = _title_from_text(text) if text else _first_user_line(project, session)
    if not title:
        return session
    try:
        return sm_for(project).update(session.id, name=title)
    except Exception:
        return session


def find_session(session_id: str):
    """Locate a session by id across all projects.

    Sessions live at ~/.ms_agent/projects/<pid>/sessions/<sid>/session.json.
    Returns (Project, Session, SessionManager) or None.
    """
    from ms_agent.project.paths import global_projects_root

    root = global_projects_root()
    if not root.exists():
        return None
    manager = pm()
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        meta = entry / "sessions" / session_id / "session.json"
        if not meta.exists():
            continue
        project = manager.get(entry.name)
        if project is None:
            continue
        sm = sm_for(project)
        session = sm.get(session_id)
        if session is not None:
            return project, session, sm
    return None
