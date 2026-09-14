"""Profile adapter — file-backed (PROFILE.md is the single source of truth).

Layout of PROFILE.md (managed by the SDK's workspace_files):

- header: frontmatter + a guidance comment (never shown, never injected)
- "# About Me" block: holds the managed ``- Call me: X`` line (the
  “Agent 如何称呼您” input edits exactly this line)
- free region: everything else (the “更多自我介绍” textarea edits this)

Legacy locations are migrated once on first access and then retired:
- webui_meta.json ``profile.agent_calls_user`` -> the Call me line
- the old plain-text profile.md is rebuilt by the SDK itself.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ms_agent.utils.file_lock import locked

from app.backends.ms_agent import sidecar
from app.backends.ms_agent.common import home  # noqa: F401  (pins MS_AGENT_HOME)
from app.schemas.profile import Profile, ProfileUpsert

_NAME = "PROFILE.md"


def _wf():
    from ms_agent.prompting import workspace_files

    return workspace_files


def _migrate_sidecar_call_me(wf, text: str) -> str:
    """One-time move of the legacy sidecar field into the file, then retire it.

    The schema default used to be "User" — that is boilerplate, not a user
    choice, so it is dropped rather than migrated.
    """
    legacy = sidecar.get("profile", "agent_calls_user", None)
    if legacy is None:
        return text
    if legacy and legacy != "User" and not wf.get_call_me(text):
        text = wf.set_call_me(text, str(legacy))
        wf.write_home_file(_NAME, text)
    sidecar.drop("profile", "agent_calls_user")
    return text


@locked(lambda *args, **kwargs: Path(home()) / "webui_meta.json")
@locked(lambda *args, **kwargs: Path(home()) / ".prompt-files")
def get_profile() -> Profile:
    wf = _wf()
    text = wf.read_home_file(_NAME)
    text = _migrate_sidecar_call_me(wf, text)
    return Profile(
        agent_calls_user=wf.get_call_me(text),
        description=wf.get_free_region(text).strip(),
        updated_at=datetime.now(timezone.utc),
    )


@locked(lambda *args, **kwargs: Path(home()) / "webui_meta.json")
@locked(lambda *args, **kwargs: Path(home()) / ".prompt-files")
def update_profile(body: ProfileUpsert) -> Profile:
    wf = _wf()
    text = wf.read_home_file(_NAME)
    text = _migrate_sidecar_call_me(wf, text)
    if body.agent_calls_user is not None:
        text = wf.set_call_me(text, body.agent_calls_user)
    if body.description is not None:
        desc = body.description.strip()
        text = wf.set_free_region(text, desc + "\n" if desc else "")
    wf.write_home_file(_NAME, text)
    return get_profile()
