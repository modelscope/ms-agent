from fastapi import APIRouter

from app.core.envelope import EnvelopeRoute
from app.schemas.agent_settings import AgentSettings

router = APIRouter(prefix="/api/agent-settings", tags=["agent-settings"],
                   route_class=EnvelopeRoute)


@router.get("")
def get_settings() -> AgentSettings:
    from app.backends.ms_agent import agent_settings

    return agent_settings.get_settings()


@router.put("")
def update_settings(body: AgentSettings) -> AgentSettings:
    from app.backends.ms_agent import agent_settings

    return agent_settings.update_settings(body)
