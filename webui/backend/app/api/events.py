"""Server-sent stream of change notices for the app shell.

The frontend opens one long-lived GET /api/events (EventSource) per tab. Every
notice published on the in-process `event_bus` — one per successful management
write — is forwarded here as an SSE `change` event, so a mutation made by ANY
caller (including an external script) refreshes every open page immediately.

Not enveloped: this is a stream, so the router deliberately omits EnvelopeRoute
(which buffers and re-wraps JSON bodies).
"""
import json

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.core.events import event_bus

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events")
async def events():
    # `@ant-design/x-sdk` is not involved here (native EventSource consumes this),
    # but keep LF frame separation consistent with the chat stream. sse-starlette
    # sends periodic pings on its own, which both keep the connection alive and
    # detect a dropped client so the subscriber generator is cancelled.
    async def stream():
        yield {"event": "ready"}
        async for event in event_bus.subscribe():
            yield {"event": "change", "data": json.dumps(event)}

    return EventSourceResponse(stream(), sep="\n")
