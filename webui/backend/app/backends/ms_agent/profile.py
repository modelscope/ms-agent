"""Profile adapter — description via ProfileManager (profile.md), the structured
agent_calls_user field via sidecar."""
from __future__ import annotations

from datetime import datetime, timezone

from app.backends.ms_agent import sidecar
from app.backends.ms_agent.common import home
from app.schemas.profile import Profile, ProfileUpsert


def _pm():
    from ms_agent.personalization import ProfileManager

    return ProfileManager(global_dir=home())


def get_profile() -> Profile:
    return Profile(
        agent_calls_user=sidecar.get("profile", "agent_calls_user", "User"),
        description=_pm().read(),
        updated_at=datetime.now(timezone.utc),
    )


def update_profile(body: ProfileUpsert) -> Profile:
    if body.description is not None:
        _pm().write(body.description)
    if body.agent_calls_user is not None:
        sidecar.put("profile", "agent_calls_user", body.agent_calls_user)
    return get_profile()
