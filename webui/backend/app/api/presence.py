"""Running-state poll for the app shell.

The frontend polls here every ~10s. The response carries the ids of sessions
with a turn in flight, which drives the sidebar "running" spinners, triggers
the live re-attach when the user opens a running session, and lets the client
reload lists/history the moment a background turn finishes.

This is NOT a liveness contract: by product decision (aligned with the
frontend team), a running turn is never stopped because clients went away —
navigation, refresh and even a fully closed browser all leave it running to
completion in the background. Only the explicit Stop button
(POST /api/chat/interrupt) cancels a turn.
"""
from fastapi import APIRouter

from app.core.envelope import EnvelopeRoute
from app.core.settings import settings

router = APIRouter(prefix="/api", tags=["presence"], route_class=EnvelopeRoute)


@router.post("/presence")
async def presence() -> dict:
    if settings.agent_backend == "ms_agent":
        from app.backends.ms_agent.runtime import registry

        return {"running": registry.running_sessions()}
    # mock backend has no live runtimes.
    return {"running": []}
