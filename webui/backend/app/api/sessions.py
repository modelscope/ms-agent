from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import Response

from app.core.envelope import EnvelopeRoute
from app.schemas.session import (
    Artifact, Session, SessionCreate, SessionMessage, SessionPlan, SessionUpdate, SessionModelUpdate
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


@router.get("/sessions/{session_id}/export")
def export_session(
    session_id: str,
    format: Literal["markdown", "html"] = "html",
    detail: Literal["full", "compact", "user-only"] = "full",
) -> Response:
    """Download the reconstructed conversation as Markdown or standalone HTML."""
    from app.backends.ms_agent import session_export

    exported = session_export.build_session_export(session_id, format, detail)
    disposition = (
        f'attachment; filename="{exported.ascii_filename}"; '
        f"filename*=UTF-8''{quote(exported.filename, safe='')}"
    )
    return Response(
        content=exported.content,
        media_type=exported.media_type,
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


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


@router.post("/sessions/{session_id}/read", status_code=204)
def mark_session_read(session_id: str) -> None:
    """Acknowledge a background turn's result: clears the unread dot the sidebar
    shows for a session that finished with nobody watching. A POST rather than a
    side effect of GET /messages, which also runs on SSR and on every route
    revalidation — reading data must not silently retire a notification."""
    from app.backends.ms_agent import sessions

    return sessions.mark_session_read(session_id)


@router.get("/sessions/{session_id}/artifacts")
def list_artifacts(session_id: str) -> list[Artifact]:
    from app.backends.ms_agent import sessions

    return sessions.list_artifacts(session_id)


@router.patch("/sessions/{session_id}/model")
def update_session_model(session_id: str, body: SessionModelUpdate) -> dict:
    from app.backends.ms_agent import sessions

    return sessions.update_session_model(session_id, body.model_id)
