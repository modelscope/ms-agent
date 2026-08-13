from fastapi import APIRouter

from app.core.envelope import EnvelopeRoute
from app.schemas.profile import Profile, ProfileUpsert

router = APIRouter(prefix="/api/profile", tags=["profile"],
                   route_class=EnvelopeRoute)


@router.get("")
def get_profile() -> Profile:
    from app.backends.ms_agent import profile

    return profile.get_profile()


@router.put("")
def update_profile(body: ProfileUpsert) -> Profile:
    from app.backends.ms_agent import profile

    return profile.update_profile(body)
