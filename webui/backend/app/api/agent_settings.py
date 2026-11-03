from fastapi import APIRouter

from app.core.envelope import EnvelopeRoute
from app.schemas.agent_settings import AgentSettings, DecisionConnectionTest

router = APIRouter(prefix="/api/agent-settings", tags=["agent-settings"],
                   route_class=EnvelopeRoute)


@router.get("")
def get_settings() -> AgentSettings:
    from app.backends.ms_agent import agent_settings

    return agent_settings.get_settings()


@router.patch("")
@router.put("")
def update_settings(body: AgentSettings) -> AgentSettings:
    from app.backends.ms_agent import agent_settings

    return agent_settings.update_settings(body)


@router.post("/decision/test")
async def test_decision_connection(body: DecisionConnectionTest) -> dict:
    from app.backends.ms_agent import agent_settings
    return await agent_settings.test_decision_connection(body.provider, body.model)
