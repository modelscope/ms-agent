"""Skill-update notices — tail-only skill sync for a session's model context.

The system prompt's skill list is a session-start snapshot and is never
rewritten (``skills.update_notice`` keeps the head byte-stable, so the
provider prefix cache survives skill changes). Instead, when the effective
skill surface changes — add/remove, enable/disable, description edit, or any
file change inside a skill's directory (SKILL.md, references/, scripts/, …) —
the next turn's user message is prefixed with a ``<system-reminder>`` notice
carrying the FULL current list. The static prompt section tells the model the
latest notice is authoritative.

The per-session sidecar ``skill_surface.json`` (beside plan.json) records what
the model was last told. It is only committed AFTER the turn is actually
enqueued — a failed/intro-only turn leaves it untouched so the notice re-fires
next time (safe over-notify, never silent-drop).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

from app.backends.ms_agent.config import session_dir, session_has_history

logger = logging.getLogger("app.ms_agent.skill_notice")

_SURFACE_FILE = "skill_surface.json"


# -- surface -------------------------------------------------------------------


def _files_sig(skill_path: str) -> str:
    """Cheap whole-directory signature: sorted (relpath, mtime_ns, size) over
    every non-hidden file under the skill root — SKILL.md, references/,
    scripts/, assets all included. Content is never read."""
    h = hashlib.sha256()
    try:
        for root, dirs, files in os.walk(skill_path):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for name in sorted(files):
                if name.startswith("."):
                    continue
                p = os.path.join(root, name)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                rel = os.path.relpath(p, skill_path)
                h.update(f"{rel}|{st.st_mtime_ns}|{st.st_size}\n".encode())
    except OSError:
        pass
    return h.hexdigest()[:16]


def build_surface(catalog) -> dict:
    """{skill_id: {name, sig, files}} for the ENABLED skills — the exact set
    the model is (to be) told about."""
    surface: dict = {}
    for sid, skill in (catalog.get_enabled_skills() or {}).items():
        name = getattr(skill, "name", sid) or sid
        desc = getattr(skill, "description", "") or ""
        surface[sid] = {
            "name": name,
            "sig": hashlib.sha256(
                f"{name}\x1f{desc}".encode()).hexdigest()[:16],
            "files": _files_sig(str(getattr(skill, "skill_path", "") or "")),
        }
    return surface


def _surface_path(project, session) -> str:
    return os.path.join(session_dir(project, session), _SURFACE_FILE)


def _load_surface(path: str) -> dict | None:
    """The persisted surface, or None when this session has never been told
    one (missing/corrupt file)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        skills = data.get("skills")
        return skills if isinstance(skills, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _save_surface(path: str, surface: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    payload = {
        "skills": surface,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# -- notice --------------------------------------------------------------------


def _render_notice(catalog, old: dict | None, new: dict) -> str:
    summary = ""
    try:
        summary = catalog.get_skills_summary() or ""
    except Exception:
        pass
    if not summary:
        summary = "(no skills are currently available)"

    lines: list[str] = ["<system-reminder>"]
    if old is None:
        # First sync of a session that predates the sidecar: the head list
        # may be stale and the drift is unknowable — announce the full truth.
        lines.append(
            "Skill inventory may have changed since this session started. "
            "CURRENT full list (authoritative; supersedes the system "
            "prompt's list and any earlier notice):")
    else:
        lines.append(
            "Skill inventory updated. CURRENT full list (supersedes the "
            "system prompt's list and any earlier notice):")
    lines.append(summary)

    if old is not None:
        added = sorted(sid for sid in new if sid not in old)
        removed = sorted(old[sid].get("name", sid)
                         for sid in old if sid not in new)
        updated = sorted(new[sid].get("name", sid)
                         for sid in new if sid in old and new[sid] != old[sid])
        if added:
            names = ", ".join(new[sid].get("name", sid) for sid in added)
            lines.append(f"Newly added since last known state: {names}")
        if removed:
            lines.append(
                "Removed or disabled since last known state: "
                + ", ".join(removed))
        if updated:
            lines.append(
                "Content updated since last known state: "
                + ", ".join(updated)
                + " — any previously loaded copy (including files under the "
                  "skill's directory such as references/ or scripts/) is "
                  "stale; re-read it via skill_view / re-open the files "
                  "before relying on it.")
    lines.append("Do not mention this notice to the user.")
    lines.append("</system-reminder>")
    return "\n".join(lines)


def pending_notice(catalog, project, session):
    """Compare the current skill surface with what this session was last told.

    Returns ``(notice_text | None, commit)``. ``commit()`` persists the new
    surface and MUST be called only after the turn carrying the notice was
    actually enqueued (or immediately for the silent brand-new-session init,
    where notice_text is None).
    """
    path = _surface_path(project, session)
    old = _load_surface(path)
    new = build_surface(catalog)

    def commit() -> None:
        try:
            _save_surface(path, new)
        except OSError:
            logger.warning("skill surface save failed", exc_info=True)

    if old is None:
        if not session_has_history(project, session):
            # Brand-new session: the head is built from the current catalog
            # this very turn — nothing to announce, just start tracking.
            commit()
            return None, lambda: None
        return _render_notice(catalog, None, new), commit

    if old == new:
        return None, lambda: None
    return _render_notice(catalog, old, new), commit
