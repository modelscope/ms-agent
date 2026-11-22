from typing import Literal

from fastapi import APIRouter, Header
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
    """Answer to an authorization card (step kind "authorization"): the SSE
    turn is suspended on this request_id until it is resolved here.

    In "always ask" mode the wait has no deadline — the user asked to be
    consulted, so the question stays open until they answer it or the session
    closes. Full access bounds the wait (``FULL_ACCESS_ASK_TIMEOUT_S``), since
    nobody may be watching at all."""

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
    expected_turn_id: str | None = None


@router.post("/interrupt")
async def interrupt_chat(body: ChatInterrupt) -> dict:
    from app.backends.ms_agent.conversations import interrupt

    stopped = await interrupt(body.session_id, body.expected_turn_id)
    return {"stopped": stopped}


@router.post('/inputs')
async def submit_input(body: ChatRequest):
    from app.backends.ms_agent.conversations import submit
    return await submit(body)


@router.get('/sessions/{session_id}/events')
async def session_events(session_id: str, last_event_id: str | None = Header(default=None)):
    from app.backends.ms_agent.conversations import get
    return EventSourceResponse(get(session_id).subscribe(last_event_id), sep='\n')


@router.get('/sessions/{session_id}/inputs')
async def pending_inputs(session_id: str):
    from app.backends.ms_agent.conversations import get
    return get(session_id).state()


class InputEdit(BaseModel):
    revision: int
    request: ChatRequest


@router.patch('/sessions/{session_id}/inputs/{input_id}')
async def edit_input(session_id: str, input_id: str, body: InputEdit):
    from app.backends.ms_agent.conversations import get
    from app.backends.errors import Conflict
    from ms_agent.session.input_controller import InputConflict
    conversation = get(session_id)
    request = body.request.model_dump(exclude={
        'input_id', 'expected_turn_id', 'session_id', 'project_id'})
    try:
        await conversation.controller.edit(input_id, body.revision, request, conversation.prepare)
    except InputConflict as exc:
        raise Conflict(str(exc)) from None
    except ValueError as exc:
        from app.backends.errors import BadRequest
        raise BadRequest(str(exc)) from None
    return conversation.state()


@router.delete('/sessions/{session_id}/inputs/{input_id}')
async def withdraw_input(session_id: str, input_id: str, revision: int):
    from app.backends.ms_agent.conversations import get
    from app.backends.errors import Conflict
    from ms_agent.session.input_controller import InputConflict
    conversation = get(session_id)
    try:
        conversation.controller.withdraw(input_id, revision)
    except InputConflict as exc:
        raise Conflict(str(exc)) from None
    return conversation.state()


@router.post('/sessions/{session_id}/inputs/resume')
async def resume_inputs(session_id: str):
    from app.backends.ms_agent.conversations import get
    from app.backends.errors import Conflict
    from ms_agent.session.input_controller import InputConflict
    conversation = get(session_id)
    try:
        conversation.controller.resume()
    except InputConflict as exc:
        raise Conflict(str(exc)) from None
    conversation.kick()
    return conversation.state()


# NOTE: the former POST /api/chat/cancel (pagehide sendBeacon) was removed.
# pagehide also fires on a page REFRESH, so beacon-cancelling killed turns the
# user expected to survive. Product decision (aligned with the frontend team):
# a running turn is NEVER stopped by clients going away — navigation, refresh
# and a fully closed browser all leave it running to completion in the
# background. Only the explicit Stop (POST /api/chat/interrupt) cancels.
