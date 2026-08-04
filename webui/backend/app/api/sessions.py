from fastapi import APIRouter, HTTPException

from app.core import store
from app.core.envelope import EnvelopeRoute
from app.core.settings import settings
from app.schemas.session import (
    Artifact, Session, SessionCreate, SessionMessage, SessionPlan, SessionUpdate
)

router = APIRouter(prefix="/api", tags=["sessions"], route_class=EnvelopeRoute)


def _ms() -> bool:
    return settings.agent_backend == "ms_agent"


@router.get("/sessions")
def list_sessions(project_id: str | None = None) -> list[Session]:
    if _ms():
        from app.backends.ms_agent import sessions

        return sessions.list_sessions(project_id)
    rows = list(store.sessions.values())
    if project_id is not None:
        rows = [s for s in rows if s.get("project_id") == project_id]
    rows.sort(key=lambda s: s["updated_at"], reverse=True)
    return [Session.model_validate(s) for s in rows]


@router.post("/sessions", status_code=201)
def create_session(body: SessionCreate) -> Session:
    if _ms():
        from app.backends.ms_agent import sessions

        return sessions.create_session(body)
    sid = store.new_id("s-")
    row = {
        "id": sid,
        "title": body.title,
        "project_id": body.project_id or store.DEFAULT_PROJECT_ID,
        "updated_at": store.now(),
        "preview": body.preview,
    }
    store.sessions[sid] = row
    return Session.model_validate(row)


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> Session:
    if _ms():
        from app.backends.ms_agent import sessions

        return sessions.get_session(session_id)
    row = store.sessions.get(session_id)
    if not row:
        raise HTTPException(404, "session not found")
    return Session.model_validate(row)


@router.get("/sessions/{session_id}/messages")
def list_session_messages(session_id: str) -> list[SessionMessage]:
    if _ms():
        from app.backends.ms_agent import sessions

        return sessions.list_messages(session_id)
    if session_id not in store.sessions:
        raise HTTPException(404, "session not found")
    return []


@router.get("/sessions/{session_id}/plan")
def get_session_plan(session_id: str) -> SessionPlan:
    """The latest plan.json for the session, plus whether it belongs to the
    CURRENT running turn (``active`` — the server-side truth the composer uses
    to animate running rows). Always reflects the live plan file (tool writes
    + manual edits) and ignores the chat/session log."""
    if _ms():
        from app.backends.ms_agent import sessions

        return sessions.read_plan(session_id)
    return SessionPlan()


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str) -> None:
    if _ms():
        from app.backends.ms_agent import sessions

        return sessions.delete_session(session_id)
    if session_id not in store.sessions:
        raise HTTPException(404, "session not found")
    del store.sessions[session_id]
    store.artifacts.pop(session_id, None)


@router.patch("/sessions/{session_id}")
def update_session(session_id: str, body: SessionUpdate) -> Session:
    """Rename a session (update its title)."""
    if _ms():
        from app.backends.ms_agent import sessions

        return sessions.update_session(session_id, body)
    row = store.sessions.get(session_id)
    if not row:
        raise HTTPException(404, "session not found")
    if body.title is not None:
        row["title"] = body.title
    return Session.model_validate(row)


@router.get("/sessions/{session_id}/artifacts")
def list_artifacts(session_id: str) -> list[Artifact]:
    if _ms():
        from app.backends.ms_agent import sessions

        return sessions.list_artifacts(session_id)
    rows = store.artifacts.get(session_id, [])
    return [Artifact.model_validate(a) for a in rows]
