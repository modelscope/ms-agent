from fastapi import APIRouter

from app.core import store
from app.core.envelope import EnvelopeRoute
from app.core.settings import settings
from app.schemas.profile import Profile, ProfileUpsert

router = APIRouter(prefix="/api/profile", tags=["profile"],
                   route_class=EnvelopeRoute)


def _ms() -> bool:
    return settings.agent_backend == "ms_agent"


def _read() -> Profile:
    return Profile.model_validate(store.profile)


@router.get("")
def get_profile() -> Profile:
    if _ms():
        from app.backends.ms_agent import profile

        return profile.get_profile()
    return _read()


@router.put("")
def update_profile(body: ProfileUpsert) -> Profile:
    if _ms():
        from app.backends.ms_agent import profile

        return profile.update_profile(body)
    if body.agent_calls_user is not None:
        store.profile["agent_calls_user"] = body.agent_calls_user
    if body.description is not None:
        store.profile["description"] = body.description
    store.profile["updated_at"] = store.now()
    return _read()
