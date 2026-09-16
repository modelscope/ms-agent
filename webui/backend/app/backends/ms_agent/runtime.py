"""Per-session live-agent registry (Route A).

Each SDK session owns one long-lived ``LLMAgent`` whose ``run(None)`` loop runs
in a background task, pulling prompts from an input queue and emitting structured
events to a sink. A POST enqueues one user turn and drains the sink until the
turn completes. One turn per session at a time (``turn_lock``).
"""
from __future__ import annotations

import asyncio
import logging
import os
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

    A queue item is either the prompt string, or ``(prompt, marker)`` /
    ``(prompt, marker, attachments)``. ``marker`` is a display-only
    skill-invocation record, written here — immediately before the SDK appends
    the (expanded) user row — so its seq precedes that row's, letting history
    replay show the user's original text instead of the expanded skill prompt.
    ``attachments`` are the turn's image references, handed to the SDK through
    the optional ``take_attachments`` hook rather than through ``read_prompt``'s
    ``str`` return: widening that return type would ripple through every
    InputSource implementation and every caller. ``log_getter`` is lazy because
    the session log is created when the agent's run loop starts."""

    def __init__(self, queue: "asyncio.Queue", sink: "QueueEventSink",
                 log_getter=None) -> None:
        self._queue = queue
        self._sink = sink
        self._log_getter = log_getter
        self._first = True
        # Attachments for the prompt most recently returned by read_prompt.
        # Consumed (and cleared) by take_attachments immediately after, so a
        # later turn can never inherit them.
        self._pending_attachments: list[dict] = []

    async def read_prompt(self, prompt: str = ">>> ") -> str:
        if self._first:
            self._first = False
        else:
            self._sink.push({"type": TURN_END})
        item = await self._queue.get()
        if isinstance(item, tuple):
            text, marker, *rest = item
            attachments = rest[0] if rest else None
        else:
            text, marker, attachments = item, None, None
        self._pending_attachments = list(attachments or [])
        if marker and self._log_getter is not None:
            try:
                log = self._log_getter()
                if log is not None and hasattr(log, "record_skill_invocation"):
                    log.record_skill_invocation(marker)
            except Exception:  # display-only; never block the turn
                logger.debug("skill invocation marker skipped", exc_info=True)
        return text

    def take_attachments(self) -> list[dict]:
        """Optional InputSource hook: the parts belonging to the last prompt.

        "Take" rather than "get": the SDK calls this once per submission right
        after read_prompt, and the source must not hand the same images to a
        later turn.
        """
        attachments, self._pending_attachments = self._pending_attachments, []
        return attachments


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
    real elapsed time instead of the replay instant.
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


#: How long a full-access session waits for an answer before giving up on it.
#: Long enough to survive a meeting, short enough that a session started and
#: walked away from does not sit on its turn forever. Only reachable in that
#: mode: the sole thing still asking there is network egress (curl/ssh/…), so
#: the wait is rare by construction.
FULL_ACCESS_ASK_TIMEOUT_S = float(os.environ.get("MSA_ASK_TIMEOUT", 25 * 60))


def _mcp_fingerprint(project) -> str:
    """Identity of the RESOLVED mcp config (global + project files, pre-health).

    Deliberately the raw resolution, not the health-filtered set the agent was
    built with: health verdicts flap, and a fingerprint that includes them
    would rebuild agents because a remote endpoint blinked. Config edits are
    the thing this tracks — whoever made them and through whatever channel.
    """
    import hashlib
    import json

    try:
        from ms_agent.tui.managed_config import resolve_mcp_config

        from app.backends.ms_agent.common import home

        raw = resolve_mcp_config(home(), project.path, None) or {}
        return hashlib.sha1(
            json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()
    except Exception:  # noqa: BLE001 — a fingerprint failure must not block chat
        return ""


def _settings_fingerprint(project, model_snapshot=None) -> str:
    """Detect imports and file edits before reusing a session's frozen config."""
    import hashlib
    from pathlib import Path

    from app.backends.ms_agent.common import home
    from ms_agent.config.resolver import _project_internal_file

    paths = [] if model_snapshot is not None else [Path(home()) / "settings.json"]
    paths.extend(_project_internal_file(project.path, name)
                 for name in ("config.yaml", "settings.local.json"))
    paths.extend(root / name for root in (Path(home()), Path(project.path))
                 for name in ("AGENTS.md", "SOUL.md", "PROFILE.md"))
    digest = hashlib.sha256()
    if model_snapshot is not None:
        import json
        digest.update(json.dumps(model_snapshot.settings, sort_keys=True).encode())
        # Session display fields change on every turn and do not configure the agent.
        meta = {k: v for k, v in model_snapshot.metadata.items()
                if k in ("providers", "models", "agent_settings", "projects")}
        digest.update(json.dumps(meta, sort_keys=True).encode())
    for path in paths:
        try:
            content = path.read_bytes()
        except (FileNotFoundError, NotADirectoryError):
            content = b""
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _ask_timeout_for(permission_mode: str | None) -> float | None:
    """``None`` — wait indefinitely — whenever the user chose to be asked.

    Expiring an approval answers it as a refusal, which is both the wrong
    answer and an unrecoverable one: the user comes back to "rejected" with no
    way to tell that nobody ever rejected anything. Someone who selected
    "always ask" is telling us they intend to answer, so we wait. Full access
    is the opposite statement, and there a bound is what keeps an unattended
    session from parking on a question no one will read.
    """
    if (permission_mode or "").strip().lower() in ("auto", "full", "full_access"):
        return FULL_ACCESS_ASK_TIMEOUT_S
    return None


# The SDK's WebPermissionHandler stamps this feedback on the ONE path that denies
# with nobody having decided: its ask() hitting the timeout (permission/handler.py).
# Nothing else here ever sets feedback — resolve_permission() builds its
# PermissionResponse from the action alone — so the string is what tells an
# expired ask apart from a human's "Reject". Compared exactly on purpose: if the
# SDK ever rewords it, a timeout degrades to a plain rejection (how it has always
# looked), whereas a looser test risks labelling a deliberate refusal a timeout.
_TIMEOUT_FEEDBACK = "Permission request timed out"


def _persisting_permission_handler(sink, session_log_getter, timeout=None):
    """WebPermissionHandler that also persists each resolved authorization to the
    session log (``record_permission``), so history can replay the card in its
    approved/rejected state. The record is display-only (filtered out of the LLM
    context by SessionLog). ``session_log_getter`` is called lazily at ask() time
    because the log is created when the agent's run loop starts (after this
    handler is built).

    It also ANNOUNCES a refusal (``permission_resolved``): the SDK's ask() returns
    DENY silently on timeout, so without this the only hint reaching live viewers
    is the gated call's errored result — the card sat there offering buttons for a
    decision that had already been made for it.

    A refusal nobody made carries ``reason: "timeout"`` — both on the wire and in
    the persisted record, so a reload keeps it — because "rejected" alone reads as
    a deliberate decision, and which one it was is exactly what tells the user
    whether to just approve the retry."""
    from ms_agent.permission.handler import (
        PermissionAction,
        WebPermissionHandler,
    )

    class _PersistingWebPermissionHandler(WebPermissionHandler):
        async def ask(self, tool_name, tool_args, context, suggestions=None,
                      call_id=""):
            response = await super().ask(
                tool_name, tool_args, context, suggestions, call_id=call_id)
            denied = response.action == PermissionAction.DENY
            timed_out = denied and str(
                response.feedback or "") == _TIMEOUT_FEEDBACK
            try:
                log = session_log_getter()
                if log is not None and hasattr(log, "record_permission"):
                    # Persist the gating tool_call's id so history replay pairs
                    # this decision to the exact call — robust when a round
                    # fires several identical tool calls in parallel (args alone
                    # can't disambiguate). Empty when the adapter hadn't assigned
                    # an id yet; reconstruct then falls back to arg matching.
                    record = {
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "state": "rejected" if denied else "approved",
                        "call_id": str(call_id or ""),
                    }
                    if timed_out:
                        record["reason"] = "timeout"
                    log.record_permission(record)
            except Exception:  # never let persistence break the turn
                logger.debug("permission record skipped", exc_info=True)
            if denied:
                # Announce the refusal NOW. Covers both ways one happens: the
                # full-access timeout (no client action at all) and a deny in
                # ANOTHER tab. Carries no request_id — the decision is final, so
                # the card must render its rejected state, not live buttons. The
                # frontend merges it onto the ask by call_id.
                event = {
                    "type": "permission_resolved",
                    "call_id": str(call_id or ""),
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "state": "rejected",
                }
                if timed_out:
                    event["reason"] = "timeout"
                sink.push(event)
            return response

    return _PersistingWebPermissionHandler(
        _PermissionEmitter(sink), timeout=timeout)


class SessionRuntime:
    def __init__(self, project, session, mcp_config: dict | None = None, model_snapshot=None) -> None:
        from app.backends.ms_agent import model_link

        self.project = project
        self.session = session
        self.model_key = model_snapshot.key if model_snapshot is not None else model_link.active_model()
        # Config identity at build time; get() compares it per turn so edits
        # made outside the management routes still reach the next turn.
        self.mcp_fingerprint = _mcp_fingerprint(project)
        self.settings_fingerprint = _settings_fingerprint(project, model_snapshot)
        # Set when this agent's configuration was superseded while it was
        # mid-turn (a memory-model edit, a store rebuild): it finishes the turn
        # it is in, and the NEXT one gets a freshly built agent. Without it a
        # busy session kept serving the old config until the idle TTL — which is
        # exactly "I saved it and nothing happened".
        self.needs_rebuild = False
        self.input_queue: "asyncio.Queue[str]" = asyncio.Queue()
        self.sink = QueueEventSink()
        self.input_source = WebInputSource(
            self.input_queue, self.sink,
            log_getter=lambda: getattr(self.agent, "session_log", None),
        )
        self.turn_lock = asyncio.Lock()
        # The user message that opened the CURRENT turn, as the composer showed
        # it (pre-expansion text plus any configuration segments), or None
        # between turns. Handed to re-attaching viewers on the `turn` frame,
        # because mid-turn that row may not exist anywhere else yet: the SDK
        # appends it to the session log only when the driver picks the prompt up
        # (1-2s in, longer on a cold build), and the asker's own optimistic
        # bubble dies with its component on the first navigation away. A viewer
        # landing in that window used to render a history WITHOUT the question
        # while the turn streamed an answer to it.
        self.turn_user: dict | None = None
        # Count of live SSE viewers (the original /api/chat stream plus any
        # /api/chat/attach viewers). Diagnostic state: a background-continued
        # turn has zero watchers. Nothing cancels a turn based on this — only
        # the explicit Stop button ends a turn early.
        self.watchers = 0
        # Asks suspend on this handler until the frontend answers via
        # POST /api/chat/permission; the decision is persisted for replay. The
        # getter reads the log lazily — the log is created when the agent's run
        # loop starts, after this line.
        self.permission_handler = _persisting_permission_handler(
            self.sink,
            lambda: getattr(self.agent, "session_log", None),
            timeout=_ask_timeout_for(getattr(project, "permission_mode", None)),
        )
        self.agent = build_agent(
            project,
            session,
            event_sink=self.sink,
            input_source=self.input_source,
            mcp_config=mcp_config,
            permission_handler=self.permission_handler,
            model_snapshot=model_snapshot,
        )
        # Last user-driven activity (monotonic). The idle sweeper evicts
        # runtimes that sat untouched past the TTL — an idle vector project
        # otherwise pins its embedded qdrant lock and its in-RAM vectors until
        # the server restarts.
        self.last_active: float = time.monotonic()
        self.run_task: asyncio.Task = asyncio.create_task(self._drive())

    def touch(self) -> None:
        self.last_active = time.monotonic()

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

    async def enqueue(self,
                      text: str,
                      marker: dict | None = None,
                      attachments: list[dict] | None = None) -> None:
        self.touch()
        # Plain string when there is nothing extra, so simple consumers/tests
        # stay unchanged; a 3-tuple only when this turn carries attachments.
        if attachments:
            await self.input_queue.put((text, marker, attachments))
        elif marker:
            await self.input_queue.put((text, marker))
        else:
            await self.input_queue.put(text)

    async def aclose(self) -> None:
        # Answer anything still waiting on a person BEFORE cancelling the run
        # task. An ask with no deadline (every "always ask" session) suspends
        # its turn until something resolves it, and a suspended turn is exactly
        # what cancellation has to interrupt — resolving first lets the turn
        # unwind on its own instead of being torn out mid-await.
        try:
            cancelled = self.permission_handler.cancel_pending(
                "Session closed before this was answered.")
            if cancelled:
                logger.info(
                    "closed %d unanswered permission request(s) for session %s",
                    cancelled, self.session.id)
        except Exception:
            logger.debug("pending permission cleanup skipped", exc_info=True)

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

    # Idle eviction: a runtime untouched this long is torn down, and when it
    # was its project's last live runtime the project's shared memory store is
    # closed too (releasing the embedded qdrant file lock + resident vectors).
    # Env-overridable for ops / tests (seconds and count). Read at USE time,
    # not at class definition — this module may be imported before
    # app.core.settings has published the .env into os.environ.
    @property
    def IDLE_TTL_S(self) -> int:
        return int(os.environ.get("MSA_RUNTIME_IDLE_TTL", 30 * 60))

    @property
    def SWEEP_INTERVAL_S(self) -> int:
        return int(os.environ.get("MSA_RUNTIME_SWEEP_INTERVAL", 60))

    # Soft cap on simultaneously live runtimes: beyond it the oldest IDLE ones
    # are evicted early (in-flight turns are never touched).
    @property
    def MAX_RUNTIMES(self) -> int:
        return int(os.environ.get("MSA_RUNTIME_MAX", 8))

    def __init__(self) -> None:
        self._runtimes: dict[str, SessionRuntime] = {}
        # Sessions whose turn has been ACCEPTED but whose runtime is not holding
        # turn_lock yet, mapped to their project id. Building a cold runtime
        # (resolve MCP, spawn servers, build the agent) takes SECONDS and the
        # lock is taken at the END of it, so every running-state reader saw
        # "idle" for a turn that was already underway — measured at 6.1s on a
        # cold session. A client navigating away and back inside that window
        # opened no attach at all and rendered the session as finished.
        self._starting: dict[str, str] = {}
        self._create_lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sweeper: asyncio.Task | None = None

    # -- running state -------------------------------------------------------

    def peek(self, session_id: str) -> "SessionRuntime | None":
        """The live runtime, if any — without building one (for attach)."""
        rt = self._runtimes.get(session_id)
        if rt is not None:
            rt.touch()
        return rt

    def peek_exact(self, session_id: str) -> "SessionRuntime | None":
        """The mapped runtime without touching it — for identity checks, where
        refreshing the idle timer would be a side effect."""
        return self._runtimes.get(session_id)

    def mark_starting(self, session_id: str, project_id: str) -> None:
        """Declare a turn accepted for this session, before its runtime exists.

        Closes the window described on `_starting`: from here on presence,
        `session.running` and attach all report the turn, so a viewer that
        leaves and comes back rejoins it instead of seeing an idle session.
        """
        self._starting[session_id] = project_id

    def clear_starting(self, session_id: str) -> None:
        """Hand running-state back to `turn_lock`. Called once the enqueue has
        landed (the lock is held, so the transition is seamless) or the turn
        failed to start (nothing is running, which is what readers should see).
        """
        self._starting.pop(session_id, None)

    def is_starting(self, session_id: str) -> bool:
        """Turn accepted, runtime not ready to be observed yet — attach has to
        WAIT for the buffer instead of concluding there is nothing to replay."""
        return session_id in self._starting

    def is_generating(self, session_id: str) -> bool:
        """Turn handed to the driver and producing events — the stricter half of
        `is_running`, which also covers the accepted-but-still-building window.

        This is the question "does the event buffer hold THIS turn", which is
        what decides whether a trailing assistant row on disk is a partial copy
        of something a live viewer also replays, and whether `turn_started_wall`
        belongs to the current turn. Inside `_starting` neither is true: the
        buffer is empty and the trailing row is the PREVIOUS turn, complete —
        answering `is_running` there would make an attached viewer drop a
        finished answer and mis-date the plan file.
        """
        rt = self._runtimes.get(session_id)
        return (
            rt is not None
            and rt.turn_lock.locked()
            and not rt.run_task.done()
        )

    def is_running(self, session_id: str) -> bool:
        """Whether the session has a turn in flight (live or background)."""
        if session_id in self._starting:
            return True
        return self.is_generating(session_id)

    def running_sessions(self) -> list[str]:
        ids = [sid for sid in list(self._runtimes) if self.is_running(sid)]
        # A starting session usually has no runtime mapped yet (that is the
        # point), so it would be missed by the scan above.
        ids.extend(
            sid for sid in list(self._starting) if sid not in self._runtimes)
        return ids

    def project_is_running(self, project_id: str) -> bool:
        """Whether any of this project's sessions has a turn in flight."""
        if project_id in set(self._starting.values()):
            return True
        return any(
            getattr(rt.project, "id", None) == project_id
            and rt.turn_lock.locked()
            for rt in list(self._runtimes.values()))

    async def get(self, project, session) -> SessionRuntime:
        """Return a live runtime for the session, (re)building if the driver has
        exited (e.g. after an error) or the active model changed (in-conversation
        model switch) so a fresh agent restores from SessionLog with the new model."""
        from app.backends.ms_agent import model_link
        from app.backends.ms_agent.common import home
        from app.backends.ms_agent.tool_settings import ensure_tool_settings

        async with self._create_lock:
            self._loop = asyncio.get_running_loop()  # for cross-thread toggles
            self._ensure_sweeper()
            rt = self._runtimes.get(session.id)
            # External import services write the file directly. Complete its
            # global defaults before fingerprinting so this write does not
            # cause another rebuild on the following turn.
            await asyncio.to_thread(ensure_tool_settings, home())
            from app.backends.ms_agent.session_models import prepare

            session, model_snapshot = await asyncio.to_thread(prepare, project, session)
            # Rebuild on a model switch or a superseded config, but never
            # mid-turn: an in-flight turn holds turn_lock, so defer the swap to
            # the next idle turn to avoid cancelling it. The MCP fingerprint
            # covers config edits the management routes never see — the agent
            # repairing its own mcp.json with a file edit, a user hand-editing
            # one — which previously took effect only for NEW sessions: the
            # session where the fix happened kept its frozen tool set.
            current_fp = _mcp_fingerprint(project)
            current_settings = _settings_fingerprint(project, model_snapshot)
            superseded = (
                rt is not None
                and not rt.turn_lock.locked()
                and (rt.model_key != model_snapshot.key
                     or rt.needs_rebuild
                     or rt.settings_fingerprint != current_settings
                     # Both sides non-empty: a fingerprint FAILURE ("") must
                     # neither force nor mask a rebuild.
                     or bool(current_fp and rt.mcp_fingerprint
                             and rt.mcp_fingerprint != current_fp))
            )
            if rt is not None and not rt.run_task.done() and not superseded:
                rt.touch()
                return rt
            if rt is not None:
                await rt.aclose()
            rt = SessionRuntime(project, session, await self._resolve_mcp(project), model_snapshot=model_snapshot)
            self._runtimes[session.id] = rt
            return rt

    # -- idle eviction -------------------------------------------------------

    def _ensure_sweeper(self) -> None:
        if self._sweeper is None or self._sweeper.done():
            self._sweeper = asyncio.get_running_loop().create_task(
                self._sweep_loop())

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(self.SWEEP_INTERVAL_S)
            try:
                await self._sweep_once()
            except Exception:  # noqa: BLE001 - the sweeper must survive
                logger.warning("runtime sweep failed", exc_info=True)

    async def _sweep_once(self) -> None:
        now = time.monotonic()
        idle = [
            rt for rt in list(self._runtimes.values())
            if not rt.turn_lock.locked()  # never touch an in-flight turn
        ]
        expired = {
            rt.session.id
            for rt in idle if now - rt.last_active > self.IDLE_TTL_S
        }
        # Over the cap: also evict the oldest idle ones beyond it.
        overflow = len(self._runtimes) - self.MAX_RUNTIMES
        if overflow > 0:
            for rt in sorted(idle, key=lambda r: r.last_active)[:overflow]:
                expired.add(rt.session.id)
        for sid in expired:
            await self._evict(sid)

    async def _evict(self, session_id: str) -> None:
        async with self._create_lock:
            rt = self._runtimes.get(session_id)
            if rt is None or rt.turn_lock.locked():
                return  # a turn started while we decided; leave it alone
            self._runtimes.pop(session_id, None)
        logger.info("evicting idle runtime for session %s", session_id)
        await rt.aclose()  # cancels the driver; cleanup flushes pending ingest
        await self._release_project_memory(rt.project)

    async def _release_project_memory(self, project) -> None:
        """Close the project's shared memory store once its LAST runtime is
        gone — that is what actually releases the embedded qdrant file lock
        (per-agent cleanup deliberately never closes shared instances)."""
        if project is None:  # partial runtimes (tests) have no project
            return
        pid = getattr(project, "id", None)
        if pid is not None and any(
                getattr(rt.project, "id", None) == pid
                for rt in self._runtimes.values()):
            return  # a sibling session still needs the store
        try:
            from ms_agent.memory.memory_manager import SharedMemoryManager
            from ms_agent.project.paths import memory_dir

            close = getattr(SharedMemoryManager, "close_matching", None)
            if close is None:  # older SDK without the helper
                return
            closed = await close(str(memory_dir(project.path)))
            if closed:
                logger.info("released shared memory for project %s", pid)
        except Exception:  # noqa: BLE001 - eviction is best-effort
            logger.warning("shared memory release failed for %s", pid,
                           exc_info=True)

    async def _resolve_mcp(self, project) -> dict:
        """Resolve enabled MCP servers and probe them (connect+initialize), so an
        unreachable/invalid server is dropped before it can break the chat turn."""
        from ms_agent.tui.managed_config import resolve_mcp_config

        from app.backends.ms_agent import mcp_health
        from app.backends.ms_agent.common import home

        raw = (resolve_mcp_config(home(), project.path, None) or {}).get("mcpServers", {})
        healthy, _dropped = await mcp_health.filter_healthy(raw)
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
        # A live agent froze its tool set at build time, and webui agents carry
        # no MCPRuntime, so the live toggle below is a no-op for them. Without
        # this mark, "applies on the next session build" never arrives for a
        # session that stays alive: a server switched off in management kept
        # answering tool calls in every open conversation. The mark makes the
        # NEXT turn rebuild from the persisted config (same supersede semantics
        # as a model switch); the turn already in flight finishes as it was.
        for rt in list(self._runtimes.values()):
            rt.needs_rebuild = True
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

    async def _discard_project(self, project_id: str) -> int:
        mine = [
            rt for rt in list(self._runtimes.values())
            if getattr(rt.project, "id", None) == project_id
        ]
        dropped = 0
        for rt in mine:
            # Whether a runtime is busy is decided INSIDE the create lock, right
            # before removing it: a turn can start between any two awaits here,
            # and dropping it then cancels an answer mid-generation.
            async with self._create_lock:
                if self._runtimes.get(rt.session.id) is not rt:
                    continue  # already replaced/evicted while we waited
                if rt.turn_lock.locked():
                    # Cannot drop an in-flight turn — mark it so the NEXT one
                    # gets a rebuilt agent instead of reusing this config.
                    rt.needs_rebuild = True
                    continue
                self._runtimes.pop(rt.session.id, None)
            await rt.aclose()  # flushes pending ingest before tearing down
            await self._release_project_memory(rt.project)
            dropped += 1
        return dropped

    def discard_project(self, project_id: str) -> int:
        """Drop a project's idle runtimes so the next turn rebuilds the agent.

        Sync entry, for management routes running in the threadpool. Needed
        because an agent freezes its whole configuration at build time: without
        this, editing a project's memory models (or toggling memory) would keep
        serving the old ones for as long as a runtime stays alive — up to the
        idle TTL. A session with a turn in flight cannot be dropped, so it is
        flagged instead and rebuilt on its next turn.
        Returns how many runtimes were dropped (flagged ones are not counted).
        """
        loop = self._loop
        if loop is None or not self._runtimes:
            return 0  # nothing live; the next build reads the new config anyway
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._discard_project(project_id), loop)
            return future.result(timeout=20)
        except Exception:  # noqa: BLE001 - persistence already succeeded
            logger.warning("discarding runtimes for project %s failed",
                           project_id, exc_info=True)
            return 0

    def mark_all_stale(self) -> int:
        """Flag every live runtime so its NEXT turn rebuilds with fresh config.

        For settings that are not scoped to one project — a model's advanced
        params, a provider's generation defaults — where any live session might
        be using the edited model. An agent freezes its configuration at build
        time, so without this an open conversation keeps sending the old
        thinking parameters until it is evicted; the user changes the tier,
        sees no difference, and reasonably concludes the setting is broken.

        Deliberately only FLAGS: unlike ``discard_project`` this tears nothing
        down and cannot interrupt a turn in flight — ``get()`` already defers
        the swap to the next idle moment. Sync entry, for management routes.
        Returns how many runtimes were flagged.
        """
        flagged = 0
        for rt in list(self._runtimes.values()):
            rt.needs_rebuild = True
            flagged += 1
        return flagged

    def resolve_permission(self, session_id: str, request_id: str, action: str) -> bool:
        """Answer a pending restricted-mode ask on the session's live runtime.

        Returns False when there is no live runtime or the request is unknown /
        already resolved (e.g. it timed out to deny)."""
        rt = self._runtimes.get(session_id)
        handler = getattr(rt, "permission_handler", None) if rt else None
        if handler is None:
            return False
        # Asked through the handler's own API rather than by reading its
        # pending map: what that map stores is the handler's business, and
        # depending on its shape here once turned a field being added to it
        # into a 500 on every approval click.
        if not handler.is_awaiting(request_id):
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
        # Every removal path must consider releasing the project's shared
        # memory — a runtime popped here never reaches the idle sweeper, and
        # without this the store's qdrant lock outlives its last runtime.
        await self._release_project_memory(getattr(rt, "project", None))
        return True

    async def close(self, session_id: str) -> None:
        async with self._create_lock:
            rt = self._runtimes.pop(session_id, None)
        if rt is not None:
            await rt.aclose()
            await self._release_project_memory(getattr(rt, "project", None))

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
