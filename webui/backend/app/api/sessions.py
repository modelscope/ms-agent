from fastapi import APIRouter, HTTPException

from app.core.envelope import EnvelopeRoute
from app.schemas.session import (
    Artifact, Session, SessionCreate, SessionMessage, SessionPlan, SessionUpdate
)

router = APIRouter(prefix="/api", tags=["sessions"], route_class=EnvelopeRoute)


@router.get("/sessions")
def list_sessions(project_id: str | None = None) -> list[Session]:
    from app.backends.ms_agent import sessions

    return sessions.list_sessions(project_id)


@router.post("/sessions", status_code=201)
def create_session(body: SessionCreate) -> Session:
    from app.backends.ms_agent import sessions

    return sessions.create_session(body)


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> Session:
    from app.backends.ms_agent import sessions

    return sessions.get_session(session_id)


@router.get("/sessions/{session_id}/messages")
def list_session_messages(session_id: str) -> list[SessionMessage]:
    from app.backends.ms_agent import sessions

    return sessions.list_messages(session_id)


@router.get("/sessions/{session_id}/plan")
def get_session_plan(session_id: str) -> SessionPlan:
    """The latest plan.json for the session, plus whether it belongs to the
    CURRENT running turn (``active`` — the server-side truth the composer uses
    to animate running rows). Always reflects the live plan file (tool writes
    + manual edits) and ignores the chat/session log."""
    from app.backends.ms_agent import sessions

    return sessions.read_plan(session_id)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str) -> None:
    from app.backends.ms_agent import sessions

    return sessions.delete_session(session_id)


@router.patch("/sessions/{session_id}")
def update_session(session_id: str, body: SessionUpdate) -> Session:
    """Rename a session (update its title)."""
    from app.backends.ms_agent import sessions

    return sessions.update_session(session_id, body)


@router.get("/sessions/{session_id}/artifacts")
def list_artifacts(session_id: str) -> list[Artifact]:
    from app.backends.ms_agent import sessions

    return sessions.list_artifacts(session_id)
