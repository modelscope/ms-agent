from fastapi import APIRouter

from app.core import store
from app.core.envelope import EnvelopeRoute
from app.core.settings import settings
from app.schemas.agent_settings import AgentSettings

router = APIRouter(prefix="/api/agent-settings", tags=["agent-settings"],
                   route_class=EnvelopeRoute)


def _ms() -> bool:
    return settings.agent_backend == "ms_agent"


def _read() -> AgentSettings:
    s = store.agent_settings
    return AgentSettings(
        default_provider_id=s.get("default_provider_id"),
        default_model_id=s.get("default_model_id"),
        default_memory_enabled=s.get("default_memory_enabled", True),
        default_memory_backend=s.get("default_memory_backend", "file"),
        global_mcp_auto_attach=s.get("global_mcp_auto_attach", True),
        global_skill_auto_attach=s.get("global_skill_auto_attach", True),
    )


@router.get("")
def get_settings() -> AgentSettings:
    if _ms():
        from app.backends.ms_agent import agent_settings

        return agent_settings.get_settings()
    return _read()


@router.put("")
def update_settings(body: AgentSettings) -> AgentSettings:
    if _ms():
        from app.backends.ms_agent import agent_settings

        return agent_settings.update_settings(body)
    # Full replacement is fine — singleton row.
    store.agent_settings.update(body.model_dump())
    return _read()
