from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.backends import get_backend
from app.core.envelope import EnvelopeRoute
from app.schemas.chat import ChatRequest

router = APIRouter(prefix="/api/chat", tags=["chat"], route_class=EnvelopeRoute)


@router.post("")
async def chat(req: ChatRequest):
    # @ant-design/x-sdk's XStream splits SSE frames on "\n\n". sse-starlette
    # defaults to CRLF, which causes the browser client to merge frames and drop
    # intermediate deltas. Emit LF-separated events for this WebUI contract.
    return EventSourceResponse(get_backend().chat_stream(req), sep="\n")


class ChatAttach(BaseModel):
    """Re-attach a viewer to a session's in-flight turn: replays the turn's
    events so far (catch-up) and follows the live tail — same ChatChunk SSE as
    POST /api/chat. Used when the user navigates back to a session whose turn
    kept running in the background. Emits just `done` when nothing is running."""

    session_id: str


@router.post("/attach")
async def chat_attach(body: ChatAttach):
    return EventSourceResponse(
        get_backend().chat_attach(body.session_id), sep="\n"
    )


class PermissionResolve(BaseModel):
    """Answer to a restricted-mode authorization card (step kind
    "authorization"): the SSE turn is suspended on this request_id until it is
    resolved here or the backend times out to deny."""

    session_id: str
    request_id: str
    action: Literal["allow_once", "allow_always", "deny"]


@router.post("/permission")
async def resolve_permission(body: PermissionResolve) -> dict:
    from app.backends.ms_agent.runtime import registry

    resolved = registry.resolve_permission(
        body.session_id, body.request_id, body.action
    )
    return {"resolved": resolved}


class ChatInterrupt(BaseModel):
    """Explicit stop of a session's in-flight turn (the composer Stop button).

    This is distinct from merely closing the SSE (navigating away): a bare
    disconnect keeps the turn running in the background, so leaving a
    conversation does not stop it and other sessions run concurrently. Only this
    call cancels the turn and seals it with an interrupted marker."""

    session_id: str


@router.post("/interrupt")
async def interrupt_chat(body: ChatInterrupt) -> dict:
    from app.backends.ms_agent.runtime import registry

    stopped = await registry.interrupt(body.session_id)
    return {"stopped": stopped}


# NOTE: the former POST /api/chat/cancel (pagehide sendBeacon) was removed.
# pagehide also fires on a page REFRESH, so beacon-cancelling killed turns the
# user expected to survive. Product decision (aligned with the frontend team):
# a running turn is NEVER stopped by clients going away — navigation, refresh
# and a fully closed browser all leave it running to completion in the
# background. Only the explicit Stop (POST /api/chat/interrupt) cancels.
