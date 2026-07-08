# Copyright (c) ModelScope Contributors. All rights reserved.
"""WebUI-facing contract validation.

The TUI is the first consumer of the ``ms_agent.ui`` seams; a WebUI backend is
the second. These tests pin the two pieces a WebUI relies on that the TUI
doesn't itself exercise via rendering: the serialized event stream (what gets
forwarded over a socket) and the async permission round-trip.
"""
import asyncio
import json

from ms_agent.permission.handler import (PermissionAction, PermissionResponse,
                                         WebPermissionHandler)
from ms_agent.ui.events import (ContentDelta, JsonlEventSink,
                                PermissionRequested, RecordingSink,
                                TeeEventSink, ToolCallStarted)


# ── event fan-out + serialization ─────────────────────────────────────────


def test_tee_fans_out_to_all_sinks():
    a, b = RecordingSink(), RecordingSink()
    tee = TeeEventSink(a, b, None)  # None sink is skipped
    tee.emit(ContentDelta('hi'))
    assert a.text() == 'hi' and b.text() == 'hi'


def test_jsonl_sink_writes_wire_payloads(tmp_path):
    path = tmp_path / 'events.jsonl'
    sink = JsonlEventSink(str(path))
    sink.emit(ContentDelta('hello'))
    sink.emit(ToolCallStarted(call_id='c1', name='shell', arguments={'cmd': 'ls'}))
    sink.close()
    lines = [json.loads(l) for l in path.read_text().splitlines()]
    assert lines[0] == {'type': 'content_delta', 'text': 'hello'}
    assert lines[1]['type'] == 'tool_call_started'
    assert lines[1]['call_id'] == 'c1'
    assert lines[1]['arguments'] == {'cmd': 'ls'}


# ── async permission round-trip (WebPermissionHandler) ────────────────────


class _Emitter:
    def __init__(self):
        self.events = []

    def emit(self, event: dict) -> None:
        self.events.append(event)


def test_web_permission_roundtrip():
    async def run():
        em = _Emitter()
        handler = WebPermissionHandler(em, timeout=5.0)
        task = asyncio.create_task(
            handler.ask('web_search---exa', {'q': 'x'}, 'needs approval'))
        await asyncio.sleep(0.01)  # let ask() emit the request

        assert len(em.events) == 1
        ev = em.events[0]
        assert ev['type'] == 'permission_request'
        assert ev['tool_name'] == 'web_search---exa'
        # The emitted dict must carry every field the PermissionRequested event
        # models, so a WebUI can render from either representation.
        for field in ('request_id', 'tool_name', 'tool_args', 'context',
                      'options'):
            assert field in ev
        assert set(PermissionRequested().to_dict()) - {'type'} <= set(ev)

        handler.resolve(
            ev['request_id'],
            PermissionResponse(action=PermissionAction.ALLOW_ONCE))
        resp = await task
        assert resp.action == PermissionAction.ALLOW_ONCE

    asyncio.run(run())


def test_web_permission_times_out_to_deny():
    async def run():
        handler = WebPermissionHandler(_Emitter(), timeout=0.05)
        resp = await handler.ask('shell', {'cmd': 'rm'}, '')
        assert resp.action == PermissionAction.DENY

    asyncio.run(run())
