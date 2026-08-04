"""Per-session live-agent registry (Route A).

Each SDK session owns one long-lived ``LLMAgent`` whose ``run(None)`` loop runs
in a background task, pulling prompts from an input queue and emitting structured
events to a sink. A POST enqueues one user turn and drains the sink until the
turn completes. One turn per session at a time (``turn_lock``).
"""
from __future__ import annotations

import asyncio
import logging
import time

from app.backends.ms_agent.config import build_agent

logger = logging.getLogger("app.ms_agent.runtime")

# Turn lifecycle (product decision, aligned with the frontend team): a running
# turn is NEVER stopped by a client going away — navigation, refresh AND a
# fully closed browser all leave it running to completion in the background
# (the SessionLog persists the answer; the viewer re-attaches or reloads it
# later). The ONLY thing that cancels a turn is the explicit Stop button
# (POST /api/chat/interrupt). POST /api/presence remains as a running-state
# poll that drives the sidebar spinners / re-attach, not a liveness contract.

# Internal sentinels pushed onto the turn queue (not AgentEvents):
#   TURN_END     — the agent called read_prompt, i.e. the current turn's answer
#                  is fully streamed and it is waiting for the next input. This
#                  is the reliable Route-A turn delimiter (turn_completed fires
#                  per-round and is mistimed — it emits only after the *next*
#                  input arrives, see llm_agent.py:1591 vs :1617).
#   DRIVER_*     — the agent loop stopped (error / EOF / cancellation).
TURN_END = "__turn_end__"
DRIVER_ERROR = "__driver_error__"
DRIVER_DONE = "__driver_done__"


class WebInputSource:
    """InputSource whose read_prompt blocks on a queue fed by POST /api/chat.

    The first read is the initial prompt (session start / resume next-turn) and
    marks no boundary; every later read means the previous turn finished, so it
    pushes a TURN_END sentinel to the active turn queue before blocking.

    A queue item is either the prompt string, or ``(prompt, marker)`` where
    ``marker`` is a display-only skill-invocation record. The marker is written
    here — immediately before the SDK appends the (expanded) user row — so its
    seq precedes that row's, letting history replay show the user's original
    text instead of the expanded skill prompt. ``log_getter`` is lazy because
    the session log is created when the agent's run loop starts."""

    def __init__(self, queue: "asyncio.Queue", sink: "QueueEventSink",
                 log_getter=None) -> None:
        self._queue = queue
        self._sink = sink
        self._log_getter = log_getter
        self._first = True

    async def read_prompt(self, prompt: str = ">>> ") -> str:
        if self._first:
            self._first = False
        else:
            self._sink.push({"type": TURN_END})
        item = await self._queue.get()
        text, marker = item if isinstance(item, tuple) else (item, None)
        if marker and self._log_getter is not None:
            try:
                log = self._log_getter()
                if log is not None and hasattr(log, "record_skill_invocation"):
                    log.record_skill_invocation(marker)
            except Exception:  # display-only; never block the turn
                logger.debug("skill invocation marker skipped", exc_info=True)
        return text


class QueueEventSink:
    """AgentEventSink as a broadcast log of the CURRENT turn's events.

    push() appends to an in-memory list (cheap — it is on the token hot path)
    and pulses an Event; any number of consumers read cursor-style via
    next_event(). This is what makes late re-attach possible: a viewer who
    navigates back to a running session replays the buffer from index 0 (full
    catch-up of the in-flight turn) and then follows the live tail, while the
    original consumer/drain keeps its own cursor. new_turn() resets the buffer
    at each turn start (the previous turn's consumers have all seen their
    terminal marker by then — the turn_lock guarantees turns don't overlap).

    Events are stamped with a monotonic ``_ts`` so replayed reasoning keeps its
    真实 elapsed time instead of the replay instant.
    """

    def __init__(self) -> None:
        self._events: list[dict] = []
        self._pulse = asyncio.Event()  # single persistent event: set on append/swap

    def new_turn(self) -> None:
        # Fresh list (not clear()) so a straggler consumer from the previous
        # turn detects the swap (its captured list stops being current) instead
        # of replaying the new turn; the pulse wakes such stragglers.
        self._events = []
        self._pulse.set()

    def push(self, payload: dict) -> None:
        self._events.append({**payload, "_ts": time.monotonic()})
        self._pulse.set()

    async def next_event(self, pos: int) -> tuple[dict, int]:
        """The event at cursor ``pos`` (waiting for it if not produced yet).

        Returns a synthesized TURN_END when the buffer was swapped by
        new_turn() — the consumer belongs to a finished turn and must wind
        down. Multi-consumer safe: every waiter re-checks after each pulse."""
        events = self._events
        while pos >= len(events):
            if events is not self._events:
                return {"type": TURN_END}, pos
            self._pulse.clear()
            if pos < len(events) or events is not self._events:
                continue
            await self._pulse.wait()
        return events[pos], pos + 1

    @property
    def size(self) -> int:
        return len(self._events)

    def emit(self, event) -> None:  # ms_agent.ui.events.AgentEventSink
        try:
            self.push(event.to_dict())
        except Exception:  # never let a renderer error break the agent loop
            logger.debug("event emit dropped", exc_info=True)


class _PermissionEmitter:
    """WebPermissionHandler EventEmitter: forwards its raw `permission_request`
    dict straight onto the turn queue (it is not an AgentEvent, so it must not
    go through QueueEventSink.emit's to_dict())."""

    def __init__(self, sink: "QueueEventSink") -> None:
        self._sink = sink

    def emit(self, event: dict) -> None:
        self._sink.push(event)


def _persisting_permission_handler(sink, session_log_getter):
    """WebPermissionHandler that also persists each resolved authorization to the
    session log (``record_permission``), so history can replay the card in its
    approved/rejected state. The record is display-only (filtered out of the LLM
    context by SessionLog). ``session_log_getter`` is called lazily at ask() time
    because the log is created when the agent's run loop starts (after this
    handler is built)."""
    from ms_agent.permission.handler import (
        PermissionAction,
        WebPermissionHandler,
    )

    class _PersistingWebPermissionHandler(WebPermissionHandler):
        async def ask(self, tool_name, tool_args, context, suggestions=None,
                      call_id=""):
            response = await super().ask(
                tool_name, tool_args, context, suggestions, call_id=call_id)
            try:
                log = session_log_getter()
                if log is not None and hasattr(log, "record_permission"):
                    state = (
                        "rejected"
                        if response.action == PermissionAction.DENY
                        else "approved"
                    )
                    # Persist the gating tool_call's id so history replay pairs
                    # this decision to the exact call — robust when a round
                    # fires several identical tool calls in parallel (args alone
                    # can't disambiguate). Empty when the adapter hadn't assigned
                    # an id yet; reconstruct then falls back to arg matching.
                    log.record_permission({
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "state": state,
                        "call_id": str(call_id or ""),
                    })
            except Exception:  # never let persistence break the turn
                logger.debug("permission record skipped", exc_info=True)
            return response

    return _PersistingWebPermissionHandler(_PermissionEmitter(sink))


class SessionRuntime:
    def __init__(self, project, session, mcp_config: dict | None = None) -> None:
        from app.backends.ms_agent import model_link

        self.project = project
        self.session = session
        # (provider, model) baked into this agent — the resolver reads it from
        # settings.json.llm, so a later model switch is detected by comparing
        # against active_model() and triggers a rebuild (see RuntimeRegistry.get).
        self.model_key = model_link.active_model()
        self.input_queue: "asyncio.Queue[str]" = asyncio.Queue()
        self.sink = QueueEventSink()
        self.input_source = WebInputSource(
            self.input_queue, self.sink,
            log_getter=lambda: getattr(self.agent, "session_log", None),
        )
        self.turn_lock = asyncio.Lock()
        # Count of live SSE viewers (the original /api/chat stream plus any
        # /api/chat/attach viewers). Diagnostic state: a background-continued
        # turn has zero watchers. Nothing cancels a turn based on this — only
        # the explicit Stop button ends a turn early.
        self.watchers = 0
        # Restricted-mode asks suspend on this handler until the frontend
        # answers via POST /api/chat/permission (deny after its timeout); the
        # decision is persisted for replay. The getter reads the log lazily —
        # it is created when the agent's run loop starts, after this line.
        self.permission_handler = _persisting_permission_handler(
            self.sink, lambda: getattr(self.agent, "session_log", None)
        )
        self.agent = build_agent(
            project,
            session,
            event_sink=self.sink,
            input_source=self.input_source,
            mcp_config=mcp_config,
            permission_handler=self.permission_handler,
        )
        self.run_task: asyncio.Task = asyncio.create_task(self._drive())

    async def _drive(self) -> None:
        try:
            gen = await self.agent.run(None, stream=True)
            async for _ in gen:
                pass
        except (EOFError, asyncio.CancelledError):
            self.sink.push({"type": DRIVER_DONE})
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the server
            logger.warning("agent loop error", exc_info=True)
            self.sink.push({"type": DRIVER_ERROR, "message": f"{type(exc).__name__}: {exc}"})
        else:
            self.sink.push({"type": DRIVER_DONE})

    async def enqueue(self, text: str, marker: dict | None = None) -> None:
        # Plain string when no marker, so simple consumers/tests stay unchanged.
        await self.input_queue.put((text, marker) if marker else text)

    async def aclose(self) -> None:
        if not self.run_task.done():
            self.run_task.cancel()
            try:
                await self.run_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await self.agent.cleanup_tools()
        except Exception:
            logger.debug("agent cleanup skipped", exc_info=True)


class RuntimeRegistry:
    """In-process registry — the whole chat runtime is single-process state.

    Live agents, their event queues, turn locks and pending permission Futures
    all live in this process's memory. Running uvicorn with multiple workers
    would scatter requests across processes that cannot see each other's
    runtimes (a /api/chat/permission answer landing on the wrong worker can
    never resolve the ask). Keep `--workers 1` (uvicorn's default); the
    multi-worker upgrade path is sticky session routing or a dedicated
    agent-runner process."""

    def __init__(self) -> None:
        self._runtimes: dict[str, SessionRuntime] = {}
        self._create_lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- running state -------------------------------------------------------

    def peek(self, session_id: str) -> "SessionRuntime | None":
        """The live runtime, if any — without building one (for attach)."""
        return self._runtimes.get(session_id)

    def is_running(self, session_id: str) -> bool:
        """Whether the session has a turn in flight (live or background)."""
        rt = self._runtimes.get(session_id)
        return (
            rt is not None
            and rt.turn_lock.locked()
            and not rt.run_task.done()
        )

    def running_sessions(self) -> list[str]:
        return [sid for sid in list(self._runtimes) if self.is_running(sid)]

    async def get(self, project, session) -> SessionRuntime:
        """Return a live runtime for the session, (re)building if the driver has
        exited (e.g. after an error) or the active model changed (in-conversation
        model switch) so a fresh agent restores from SessionLog with the new model."""
        from app.backends.ms_agent import model_link

        async with self._create_lock:
            self._loop = asyncio.get_running_loop()  # for cross-thread toggles
            rt = self._runtimes.get(session.id)
            # Rebuild on model switch, but never mid-turn: an in-flight turn holds
            # turn_lock, so defer the swap to the next idle turn to avoid cancelling it.
            model_changed = (
                rt is not None
                and not rt.turn_lock.locked()
                and rt.model_key != model_link.active_model()
            )
            if rt is not None and not rt.run_task.done() and not model_changed:
                return rt
            if rt is not None:
                await rt.aclose()
            rt = SessionRuntime(project, session, await self._resolve_mcp(project))
            self._runtimes[session.id] = rt
            return rt

    async def _resolve_mcp(self, project) -> dict:
        """Resolve enabled MCP servers and probe them (connect+initialize), so an
        unreachable/invalid server is dropped before it can break the chat turn."""
        from ms_agent.tui.managed_config import resolve_mcp_config

        from app.backends.ms_agent import mcp_health
        from app.backends.ms_agent.common import home

        raw = (resolve_mcp_config(home(), project.path, None) or {}).get("mcpServers", {})
        healthy = await mcp_health.filter_healthy(raw)
        return {"mcpServers": healthy} if healthy else {}

    async def _apply_mcp_toggle(self, name: str, enabled: bool) -> None:
        for rt in list(self._runtimes.values()):
            mcp_rt = getattr(rt.agent, "mcp_runtime", None)
            if mcp_rt is None or mcp_rt.get_server(name) is None:
                continue
            try:
                if enabled:
                    await mcp_rt.enable_server(name)
                else:
                    await mcp_rt.disable_server(name)
            except Exception:
                logger.warning("live MCP toggle failed: %s", name, exc_info=True)

    def toggle_mcp(self, name: str, enabled: bool) -> None:
        """Sync entry (for sync management routes running in the threadpool):
        connect/disconnect a server on any live session that manages it.
        Best-effort and non-fatal — persistence is the source of truth."""
        loop = self._loop
        if loop is None or not self._runtimes:
            return  # no live session to affect; change applies on next build
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._apply_mcp_toggle(name, enabled), loop
            )
            future.result(timeout=15)
        except Exception:
            logger.warning("scheduling live MCP toggle failed: %s", name, exc_info=True)

    def resolve_permission(self, session_id: str, request_id: str, action: str) -> bool:
        """Answer a pending restricted-mode ask on the session's live runtime.

        Returns False when there is no live runtime or the request is unknown /
        already resolved (e.g. it timed out to deny)."""
        rt = self._runtimes.get(session_id)
        handler = getattr(rt, "permission_handler", None) if rt else None
        if handler is None:
            return False
        future = handler._pending.get(request_id)
        if future is None or future.done():
            return False
        from ms_agent.permission.handler import PermissionAction, PermissionResponse

        try:
            handler.resolve(request_id, PermissionResponse(action=PermissionAction(action)))
        except ValueError:
            return False
        return True

    def set_project_permission_mode(self, project_id: str, mode: str) -> int:
        """Hot-apply a project's permission mode to its LIVE runtimes.

        The SDK's ``set_permission_mode`` swaps the enforcer's frozen config in
        place, so the next tool call obeys the new mode without rebuilding the
        agent (an in-flight turn is unaffected until its next call). Runtimes
        built later pick the mode up from the project sidecar at build time.
        Returns how many runtimes were updated.
        """
        n = 0
        for rt in self._runtimes.values():
            if getattr(rt.project, "id", None) != project_id:
                continue
            agent = getattr(rt, "agent", None)
            if agent is None or not hasattr(agent, "set_permission_mode"):
                continue
            try:
                agent.set_permission_mode(mode)
                n += 1
            except Exception:  # never let a mode toggle break a live session
                logger.debug("permission mode hot-apply skipped", exc_info=True)
        return n

    async def interrupt(self, session_id: str) -> bool:
        """Explicit stop (POST /api/chat/interrupt): discard the live runtime so
        the in-flight SDK generation is cancelled now, then seal the log so the
        rebuilt agent answers the NEXT message, not the interrupted one. Returns
        False when there is no live runtime for the session.

        This is the *only* path that cancels a turn. A plain client disconnect
        (navigating away) does not come here — it drains in the background and
        the conversation keeps running (see chat._drain_abandoned_turn)."""
        from app.backends.ms_agent.chat import _seal_interrupted_turn

        # Hold _create_lock across the WHOLE stop (pop + cancel + seal), not just
        # the pop. Otherwise a next-message get() for this same session could
        # build a SECOND runtime on the same SessionLog while we are still
        # sealing — the new runtime then clobbers the interrupted turn's history
        # (reproduced: the whole interrupted turn vanished from the log). With
        # the lock held, that get() waits and rebuilds from the sealed log.
        async with self._create_lock:
            rt = self._runtimes.pop(session_id, None)
            if rt is None:
                return False
            await rt.aclose()  # cancels the driver (SDK interrupt closes upstream)
            try:
                _seal_interrupted_turn(rt)
            except Exception:  # never let sealing crash the stop
                logger.debug("seal on interrupt skipped", exc_info=True)
        return True

    async def close(self, session_id: str) -> None:
        async with self._create_lock:
            rt = self._runtimes.pop(session_id, None)
        if rt is not None:
            await rt.aclose()

    def discard(self, session_id: str) -> None:
        """Sync best-effort stop (for use from sync routes, e.g. session delete):
        schedule the driver close on its owning event loop."""
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                if asyncio.get_running_loop() is loop:
                    loop.create_task(self.close(session_id))
                    return
            except RuntimeError:
                pass
            try:
                future = asyncio.run_coroutine_threadsafe(self.close(session_id), loop)
                future.result(timeout=15)
                return
            except Exception:
                logger.warning("scheduling runtime discard failed: %s", session_id, exc_info=True)

        rt = self._runtimes.pop(session_id, None)
        if rt is not None and not rt.run_task.done():
            try:
                rt.run_task.cancel()
            except RuntimeError:
                logger.debug("runtime discard skipped for stopped loop", exc_info=True)

    async def close_all(self) -> None:
        for sid in list(self._runtimes):
            await self.close(sid)


registry = RuntimeRegistry()
