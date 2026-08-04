"""POST /api/chat over Route A: enqueue one user turn, stream its events.

The frontend sends the full message list each turn; the agent owns history via
SessionLog, so we only forward the latest user message. Events map to the
frontend's ChatChunk contract (frontend/app/lib/agentProvider.ts)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator

from app.backends.ms_agent.common import (
    _is_cheap_title,
    _is_default_name,
    autoname_session,
    find_session,
    home,
    resolve_project,
    sm_for,
)
from app.backends.ms_agent import sidecar, titler
from app.backends.ms_agent.runtime import (
    DRIVER_DONE,
    DRIVER_ERROR,
    TURN_END,
    registry,
)
from app.schemas.chat import ChatChunk, ChatRequest

logger = logging.getLogger("app.ms_agent.chat")


def _content_parts(msg) -> tuple[str, list[str]]:
    """Extract ``(plain_text, skill_ids)`` from a message whose ``content`` is
    either a plain string or a configuration-style segment array
    (``[{type: text|skill, ...}]``). Legacy ``msg.skills`` ids are merged in
    for wire compatibility."""
    if msg is None:
        return "", []
    content = msg.content or ""
    if isinstance(content, str):
        text, ids = content.strip(), []
    else:
        text = " ".join(
            s.text for s in content if s.type == "text" and s.text
        ).strip()
        # Candidates for the SDK's find_skill (slug / frontmatter name): the
        # display name the composer sent resolves there; the WebUI asset id
        # (``src::…``) is kept as a fallback candidate.
        ids = []
        for s in content:
            if s.type != "skill":
                continue
            for cand in (s.name, s.id):
                if cand and cand not in ids:
                    ids.append(cand)
    for sid in getattr(msg, "skills", None) or []:  # deprecated field
        if sid and sid not in ids:
            ids.append(sid)
    return text, ids


def _compose_prompt(msg) -> str:
    """Build the prompt enqueued to the agent for one user turn.

    When the user attached files, append a plainly-delimited block listing each
    file's workspace-relative path (``user_files/<name>``). The agent's file
    tools are scoped to the project workspace, so these paths resolve to the
    real uploaded bytes on disk. The block is part of the enqueued prompt, so it
    persists into the SessionLog user message — that record is the durable
    session↔files mapping (and replays as text in history).
    """
    if msg is None:
        return ""
    text, _ = _content_parts(msg)
    files = getattr(msg, "files", None) or []
    if not files:
        return text
    lines = [
        "[Attached files] (paths are relative to the project workspace root; "
        "use the file tools to read them):"
    ]
    for f in files:
        lines.append(f"- {f.path}")
    block = "\n".join(lines)
    return f"{text}\n\n{block}" if text else block


def _resolve_or_create(req: ChatRequest):
    """Return (project, session). Reuse an existing session by id; otherwise
    create one under the requested project (default project when unspecified)."""
    if req.session_id:
        found = find_session(req.session_id)
        if found:
            project, session, _sm = found
            return project, session
    try:
        project = resolve_project(req.project_id)
    except KeyError:
        project = resolve_project(None)  # unknown id -> default project
    session = sm_for(project).create()
    return project, session


def _delta(chunk: ChatChunk) -> dict:
    # Emit a plain SSE `data:` frame (default `message` event). The frontend
    # routes purely on the payload's `type`, so no custom `event:` name is
    # needed; the terminal frame is just a chunk with type=="done".
    return {"data": chunk.model_dump_json()}


def _turn_frame(rt) -> dict:
    """A `turn` frame carrying how long the RUNNING turn has been going.

    The turn origin lives on the runtime (set when the prompt is enqueued), so
    it is the same clock for the original stream and for a later re-attach — a
    client that joins (or reloads) mid-turn learns the real elapsed time
    instead of restarting its counter from zero.
    """
    origin = getattr(rt, "turn_started_at", None)
    elapsed = int((time.monotonic() - origin) * 1000) if origin else 0
    return _delta(ChatChunk(type="turn", meta={"elapsed_ms": elapsed}))


# Re-send the turn age at most this often (seconds) while frames flow, so the
# client's ticking counter is re-based against the server clock (second-level
# drift correction) without flooding the stream.
_TURN_SYNC_INTERVAL = 5.0


# Plan (todo) status -> frontend task status (agentProvider.ts TaskStatus).
_PLAN_STATUS = {"pending": "pending", "in_progress": "running", "completed": "done"}
# Candidate argument keys carrying a file path, for nicer file_read/file_write cards.
_PATH_KEYS = ("path", "file_path", "target_file", "filename", "file")


def _as_dict(args) -> dict:
    """Tool arguments arrive as a dict or a raw JSON string; normalize to a dict."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (ValueError, TypeError):
            return {}
    return args if isinstance(args, dict) else {}


def _stringify(value) -> str:
    """Render a tool result for display: pass strings through, JSON-encode
    dicts/lists, else str()."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(value)


# Framework-generated assistant placeholder contents (SDK-side). They exist only
# to keep a content-less assistant message protocol-valid — NOT model output, so
# they must never surface in the UI. New logs are self-describing (the SDK flags
# synthetic filler with ``content_placeholder``, and no longer fills a tool-call
# turn at all); these literals are the OLD-log fallback. Mirrors
# ms_agent.agent.llm_agent (INTERRUPTED_PLACEHOLDER + the removed tool-call
# placeholder); kept webui-local to avoid importing SDK internals.
_INTERRUPTED_PLACEHOLDER = "[interrupted]"
_TOOLCALL_PLACEHOLDER = "Let me do a tool calling."


def is_placeholder_content(row: dict) -> bool:
    """True when this row's ``content`` is framework filler, not model output.

    Structural first: ``content_placeholder`` (set by the SDK seal and by the
    webui fallback seal) is authoritative and applies to ANY row shape.

    The literal comparison is only a fallback for logs written before that flag
    existed, and is deliberately narrowed by corroborating structure so a
    GENUINE reply that happens to equal a literal is never hidden:

    - ``[interrupted]`` counts only on a row flagged ``interrupted``;
    - ``Let me do a tool calling.`` counts only on a row that carries
      ``tool_calls`` (the only situation the SDK ever injected it).

    Non-string content (multimodal block lists) is never filler — and must not
    be compared against a string set, which would raise TypeError on an
    unhashable value and 500 the whole history endpoint.
    """
    if row.get("content_placeholder"):
        return True
    content = row.get("content")
    if not isinstance(content, str):
        return False
    if content == _INTERRUPTED_PLACEHOLDER:
        return bool(row.get("interrupted"))
    if content == _TOOLCALL_PLACEHOLDER:
        return bool(row.get("tool_calls"))
    return False


# Built-in tool servers (the SDK's own `server---tool` namespaces). Anything
# else with a `---` separator is an MCP server — the UI labels those "call
# MCP" instead of "call tool" (meta.source below).
_BUILTIN_SERVERS = {
    "todo_list", "task_control", "file_system", "skills", "code_executor",
    "web_search", "unified_memory", "agent_tools",
}


def _tool_source(name: str) -> str:
    """``mcp`` for non-builtin `server---tool` names, else ``tool``."""
    base, sep, _ = name.partition("---")
    return "mcp" if (sep and base not in _BUILTIN_SERVERS) else "tool"


def _tool_step_meta(name: str, args: dict) -> dict | None:
    """Map one SDK tool call (`server---tool`) to a frontend `step` meta, or None
    to drop it. Matching is on the full name (server + leaf), never the short
    leaf alone, per the tool taxonomy.

    - todo_list / task_control -> None (plan machinery; shown as the task list).
    - file_system read          -> file_read (with a path).
    - file_system write_file    -> file_write; edit_file -> file_edit (distinct
      cards: a full-content write vs an in-place edit render differently).
    - file_system grep/glob      -> search (a workspace query).
    - skills                     -> skill_load.
    - code_executor shell/py/nb  -> terminal (command / code body).
    - web_search *_search        -> search (a web query); fetch_page -> browser.
    - unified_memory             -> memory (add/replace/remove/read).
    - anything else (MCP, agent_tools, media, ...) -> the generic tool_call card,
      rendered by its unified tool name.
    """
    base, _, leaf = name.partition("---")
    if base in ("todo_list", "task_control"):
        return None
    if base == "file_system":
        if leaf in ("grep", "glob"):
            query = str(args.get("pattern") or args.get("glob") or args.get("path") or "")
            return {"kind": "search", "name": name, "query": query, "scope": "files"}
        path = next(
            (args[k] for k in _PATH_KEYS if isinstance(args.get(k), str) and args[k]),
            "",
        )
        if not path and isinstance(args.get("paths"), list):
            path = ", ".join(str(p) for p in args["paths"][:3] if p)
        if path and leaf == "read_file":
            return {"kind": "file_read", "path": path, "name": name}
        if path and leaf == "write_file":
            return {"kind": "file_write", "path": path, "name": name}
        if path and leaf == "edit_file":
            return {"kind": "file_edit", "path": path, "name": name}
    if base == "skills":
        return {"kind": "skill_load", "name": args.get("skill_id") or leaf or name}
    if base == "code_executor":
        if leaf == "shell_executor":
            return {"kind": "terminal", "name": name, "code": str(args.get("command") or "")}
        if leaf in ("python_executor", "notebook_executor"):
            return {"kind": "terminal", "name": name, "code": str(args.get("code") or "")}
    if base == "web_search":
        if leaf == "fetch_page":
            return {"kind": "browser", "name": name, "url": str(args.get("url") or "")}
        return {"kind": "search", "name": name, "query": str(args.get("query") or ""), "scope": "web"}
    if base == "unified_memory":
        action = str(args.get("action") or ("read" if leaf == "memory_read" else ""))
        return {"kind": "memory", "name": name, "action": action}
    return {"kind": "tool_call", "name": name, "source": _tool_source(name)}


class _TurnMapper:
    """Assemble the frontend's ordered-parts view-model (agentProvider.ts) from
    the SDK's flat semantic event stream. Stateful per turn: streams reasoning as
    incremental `thought` frames (a final frame carries meta.duration to close the
    block). Tool calls emit standalone `step` frames in stream order; a todo plan
    (plan_updated) emits `task` frames rendered as a plain plan list — steps are
    no longer nested under tasks."""

    def __init__(self, session_id: str = "", resolved_permissions: list[dict] | None = None) -> None:
        self._session_id = session_id
        # Pre-resolved permissions (for attach replay only). Each entry has
        # {tool_name, arguments, state}. Consumed in order (FIFO per tool_name).
        self._resolved_perms: list[dict] = list(resolved_permissions or [])
        self._reason_start: float | None = None
        # call_id -> (name, args, group). A tool step is deferred to
        # tool_call_completed (where ok/error is known), but the args + round
        # group live on tool_call_started.
        self._pending: dict[str, tuple[str, dict, int]] = {}
        # Tool-round grouping mirrors the assistant message's tool_calls ARRAY
        # directly: the SDK emits the whole array as consecutive
        # ToolCallStarted events BEFORE executing any of them, so "pending was
        # empty" marks the array's first element — no boundary inference
        # (content/reasoning heuristics) needed.
        self._group_seq = 0
        # True once a todo_write / todo_render_md completed this turn: the
        # session plan files changed, so the loop's changed-files summary
        # includes the reserved "plan.md" marker (todo steps themselves emit
        # no card — this flag is the only trace).
        self.plan_touched = False
        # Raw plan locations the todo tool reported this turn (todo_write's
        # `plan_path`, todo_render_md's target) — resolved at loop end to keep
        # plan files (any configured name) out of the changed-files summary.
        self.plan_reports: list[str] = []
        # The LAST markdown target a todo_render_md produced this turn (raw,
        # workspace-relative). Only a FALLBACK for the loop's `plan_file` — the
        # canonical plan.md todo_write maintains is preferred (see _plan_md_path).
        self.latest_plan_md_report: str | None = None

    def map(self, payload: dict) -> list[ChatChunk]:
        """Translate one AgentEvent dict into zero or more ChatChunks."""
        t = payload.get("type")
        # Event timestamps (stamped by the sink buffer) keep durations truthful
        # when a late viewer replays the buffer: elapsed time is between the
        # ORIGINAL events, not the replay instants.
        ts = payload.get("_ts")
        now = ts if isinstance(ts, (int, float)) else time.monotonic()
        if t == "content_delta":
            return [ChatChunk(type="text", content=payload.get("text", ""))]
        if t == "reasoning_started":
            self._reason_start = now
            return []
        if t == "reasoning_delta":
            # Stream reasoning incrementally; the frontend appends to the open
            # thought block. Start the clock lazily if we missed the start event.
            if self._reason_start is None:
                self._reason_start = now
            text = payload.get("text", "")
            return [ChatChunk(type="thought", content=text)] if text else []
        if t == "reasoning_ended":
            return self._close_thought(now)
        if t == "plan_updated":
            return self._tasks(payload.get("entries", []))
        if t == "tool_call_started":
            # Stash name+args+group by call_id — the completed event lacks
            # arguments. The SDK flushes one round's WHOLE tool_calls array as
            # consecutive started events before running any tool, so an empty
            # pending map here means "first element of a new array" → new group.
            if not self._pending:
                self._group_seq += 1
            call_id = str(payload.get("call_id") or "")
            name = payload.get("name", "") or ""
            args = _as_dict(payload.get("arguments"))
            self._pending[call_id] = (name, args, self._group_seq)
            # Emit a live "running" card NOW so a slow tool (e.g. web_search)
            # shows immediate feedback instead of a blank gap; the completed
            # event's step (same call_id) replaces it in place on the frontend.
            # The card's final shape (ok/error + result) is authored on
            # completion in _tool_step.
            return self._tool_running_step(name, args, self._group_seq, call_id)
        if t == "tool_call_completed":
            return self._tool_step(payload)
        if t == "permission_request":
            return self._permission_step(payload)
        if t == "error":
            return [ChatChunk(type="error", meta={
                "message": payload.get("message", ""),
                "recoverable": bool(payload.get("recoverable", False)),
            })]
        # user_message / turn_started / content_end / context_compacted -> none.
        return []

    def _tool_running_step(self, name: str, args: dict, group: int,
                           call_id: str) -> list[ChatChunk]:
        """A live 'executing' card emitted on tool_call_started. The frontend
        replaces it in place with the completed step (same call_id). Plan
        machinery (todo_list / task_control) renders no card, so skip it here
        too — its _tool_step_meta is None."""
        meta = _tool_step_meta(name, args)
        if meta is None:
            return []
        meta = {**meta, "tool": name, "arguments": args, "group": group,
                "call_id": call_id, "status": "running"}
        return [ChatChunk(type="step", meta=meta)]

    def _tool_step(self, payload: dict) -> list[ChatChunk]:
        """Emit a finished tool call's step card, carrying its full invocation
        (tool name + arguments + result) so the detail drawer can show it, plus
        ok/error status. Plan-machinery tools (todo_list / task_control) skip."""
        call_id = str(payload.get("call_id") or "")
        name, args, group = self._pending.pop(
            call_id,
            (payload.get("name", "") or "", {}, self._group_seq or 1),
        )
        if name in ("todo_list---todo_write", "todo_list---todo_render_md") \
                and not payload.get("error"):
            # The session plan files changed. Record the plan location the tool
            # reported (todo_write's `plan_path`, todo_render_md's target) so
            # loop end can keep plan files — under any configured name — out of
            # the changed-files summary (and, as a fallback, locate `plan_file`).
            self.plan_touched = True
            self._note_plan_report(name, payload.get("result"))
        meta = _tool_step_meta(name, args)
        if meta is None:
            return []
        # Full invocation, so the detail drawer can show arguments + result.
        # call_id lets the frontend replace this call's live "running" card in
        # place (instead of appending a duplicate).
        meta = {**meta, "tool": name, "arguments": args, "group": group,
                "call_id": call_id}
        result = payload.get("result")
        if result is not None:
            meta["result"] = _stringify(result)
        duration_s = payload.get("duration_s")
        if isinstance(duration_s, (int, float)):
            meta["duration_ms"] = int(duration_s * 1000)
        if payload.get("error"):
            meta = {**meta, "status": "error", "error": str(payload.get("error"))}
        return [ChatChunk(type="step", meta=meta)]

    def _note_plan_report(self, name: str, result) -> None:
        """Extract the plan file location a completed todo call reported and
        stash it (raw, as the tool phrased it — resolved against the workspace
        at loop end). ``todo_write`` returns JSON with ``plan_path``;
        ``todo_render_md`` returns ``OK: rendered plan markdown to <path>``."""
        text = _stringify(result) if result is not None else ""
        if not text:
            return
        if name == "todo_list---todo_render_md":
            m = re.match(r"^OK: rendered plan markdown to (.+)$", text.strip())
            if m:
                target = m.group(1).strip()
                self.plan_reports.append(target)
                self.latest_plan_md_report = target
            return
        # todo_write: JSON payload with a relative plan_path (the plan json).
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return
        pp = data.get("plan_path") if isinstance(data, dict) else None
        if isinstance(pp, str) and pp:
            self.plan_reports.append(pp)

    def _permission_step(self, payload: dict) -> list[ChatChunk]:
        """Surface a restricted-mode ask (WebPermissionHandler emit) as an
        authorization card. The turn is suspended on the handler's Future until
        POST /api/chat/permission resolves it (or it times out to deny).

        During attach replay, the session log's resolved state is used so the
        card shows approved/rejected instead of stale pending buttons."""
        tool = str(payload.get("tool_name") or "")
        call_id = str(payload.get("call_id") or "")
        args = _as_dict(payload.get("tool_args"))
        preview = json.dumps(args, ensure_ascii=False)
        if len(preview) > 160:
            preview = preview[:160] + "…"
        # Check if this permission was already resolved (attach replay). Prefer
        # an exact call_id match, else fall back to tool_name FIFO (old buffers).
        state = "pending"
        idx = next(
            (i for i, r in enumerate(self._resolved_perms)
             if call_id and str(r.get("call_id") or "") == call_id),
            None,
        )
        if idx is None:
            idx = next(
                (i for i, r in enumerate(self._resolved_perms)
                 if not str(r.get("call_id") or "") and r.get("tool_name") == tool),
                None,
            )
        if idx is not None:
            state = self._resolved_perms.pop(idx).get("state", "pending")
        # The ask belongs to its tool's round — share that group id so the
        # auth card renders inside the same nested accordion.
        pend = self._pending.get(call_id)
        group = pend[2] if pend else (self._group_seq or 1)
        meta = {
            "kind": "authorization",
            "state": state,
            "request_id": str(payload.get("request_id") or ""),
            "call_id": call_id,
            "session_id": self._session_id,
            "tool_name": tool,
            "arguments": args,
            "desc": f"{tool} {preview}".strip(),
            "group": group,
            "source": _tool_source(tool),
        }
        return [ChatChunk(type="step", meta=meta)]

    def flush(self) -> list[ChatChunk]:
        """Close an open thought block and emit any pending (interrupted) tool calls
        when a turn ends before their tool_call_completed arrived."""
        chunks = self._close_thought(time.monotonic())
        # Emit deferred tool calls that never completed (turn was interrupted).
        for call_id, (name, args, group) in list(self._pending.items()):
            meta = _tool_step_meta(name, args)
            if meta is None:
                continue
            meta["status"] = "error"
            meta["error"] = "[Interrupted: tool execution was cancelled]"
            meta["group"] = group
            # Same call_id as the live "running" card so the frontend flips that
            # card to the interrupted state in place (no duplicate).
            meta["call_id"] = call_id
            chunks.append(ChatChunk(type="step", meta=meta))
        self._pending.clear()
        return chunks

    def _close_thought(self, end: float) -> list[ChatChunk]:
        """Emit a zero-width `thought` frame carrying the elapsed duration, which
        finalizes the current thought block on the frontend. No-op if no reasoning
        was in flight."""
        start, self._reason_start = self._reason_start, None
        if start is None:
            return []
        return [ChatChunk(type="thought", content="",
                          meta={"duration": max(0, round(end - start))})]

    def _tasks(self, entries: list) -> list[ChatChunk]:
        # Re-send the whole plan on every update, one `task` chunk per row with
        # index-stable ids. The frontend folds one burst into a frozen plan
        # SNAPSHOT block appended at that point in the stream; a repeated id
        # signals the next burst, so the stable ids delimit snapshots.
        out: list[ChatChunk] = []
        for i, entry in enumerate(entries):
            entry = entry if isinstance(entry, dict) else {"content": str(entry)}
            out.append(ChatChunk(type="task", meta={
                "id": str(i),
                "label": entry.get("content", ""),
                "status": _PLAN_STATUS.get(entry.get("status", "pending"), "pending"),
            }))
        return out


def _seal_interrupted_turn(rt) -> None:
    """Fallback seal: close the log if an aborted turn somehow left it open.

    The SDK now faithfully persists an interrupted round itself (run_loop's
    cancellation handler seals partial content + synthesized tool results, all
    flagged ``interrupted``), so normally the log already ends on an assistant
    row when this runs. This guard only fires when that persistence could not
    run (cancel before the round started, an older SDK, or a persist failure):
    a dangling ``user``/``tool`` tail would make the rebuilt agent re-answer the
    cancelled turn instead of the user's next message. The placeholder matches
    the SDK's neutral marker — UIs render the ``interrupted`` flag, never the
    literal content.
    """
    agent = getattr(rt, "agent", None)
    log = getattr(agent, "session_log", None)
    if log is None:
        return
    try:
        msgs = log.get_all_messages()
        if msgs and msgs[-1].get("role") in ("user", "tool"):
            log.append({
                "role": "assistant",
                "content": _INTERRUPTED_PLACEHOLDER,
                # Structured marker (mirrors the SDK seal): the content is
                # synthetic filler, so replay renders the interrupted badge and
                # hides the literal — no string-matching needed downstream.
                "content_placeholder": True,
                "interrupted": True,
            })
    except Exception:
        logger.debug("seal interrupted turn skipped", exc_info=True)
    # A cancelled turn never reaches loop_end, so nothing would record its
    # wall-clock duration — on replay the "processing Ns" header had no number
    # to show and fell back to 0s (history carries no turn origin). Record the
    # boundary here with the elapsed time up to the stop, so a reloaded page
    # shows the same duration the live view froze at.
    session_id = getattr(getattr(rt, "session", None), "id", "")
    _persist_loop_end_from_log(rt, session_id)


async def _drain_abandoned_turn(rt, pos: int, session_id: str) -> None:
    """The client left mid-turn WITHOUT an explicit stop (navigated to another
    conversation). Keep this turn running in the background rather than cancel
    it: the SDK driver keeps generating and persists each round to the
    SessionLog, and the sink buffers the turn's events so a viewer can
    re-attach later. This task just waits (from the leaver's cursor) for the
    turn boundary, then releases the lock.

    This is deliberately not a cancel. Leaving a conversation — by navigation,
    refresh, or even closing the browser — must let it finish (sessions run
    concurrently on their own runtimes). The ONLY early stop is the explicit
    POST /api/chat/interrupt. A *next* message to THIS session correctly waits
    on the turn lock.
    """
    try:
        while True:
            payload, pos = await rt.sink.next_event(pos)
            if payload.get("type") in (TURN_END, DRIVER_DONE, DRIVER_ERROR):
                break
        # No live viewer will write the loop_end marker for this turn, so do it
        # here: duration from the shared runtime turn origin, changed files
        # derived from the session log (scoped to this turn).
        _persist_loop_end_from_log(rt, session_id)
    except Exception:  # never let background cleanup crash
        logger.debug("drain abandoned turn ended", exc_info=True)
    finally:
        if rt.turn_lock.locked():
            rt.turn_lock.release()


def _ws_root(rt) -> str | None:
    """The runtime's workspace root (``project.path`` — where file-tool
    relative paths resolve). None when unavailable."""
    try:
        p = str(getattr(getattr(rt, "project", None), "path", "") or "")
        return os.path.normpath(p) if p else None
    except Exception:
        return None


def _plan_md_path(rt, rendered_target: str | None = None) -> str | None:
    """Absolute path of THE session plan markdown — the pointer the plan chip
    labels itself with, kept consistent with the plan ``GET /sessions/{id}/plan``
    actually serves.

    Prefer the CANONICAL configured ``plan_md_filename``: with ``auto_render_md``
    on (the default), ``todo_write`` re-renders this file on EVERY plan change,
    so it always mirrors the live ``plan.json`` the chip's popover reads (webui
    points it at ``<session_dir>/plan.md``; an absolute value wins the join, so
    an unusual configured location is honored too). A ``todo_render_md`` is an
    explicit, optional export the model may aim anywhere under any name — it is
    a copy, NOT necessarily the canonical plan — so its target is only a
    fallback here, used when the configured path can't be resolved (e.g.
    ``auto_render_md`` disabled with no config). None when nothing resolves.

    (The filtering set ``sessions.plan_paths_in_rows`` still collects ALL plan
    locations — including every render target — so custom-named renders stay
    out of the file ledgers regardless of this pointer choice.)"""
    try:
        cfg = getattr(rt.agent, "config", None)
        tool_cfg = getattr(getattr(cfg, "tools", None), "todo_list", None)
        raw = str(getattr(tool_cfg, "plan_md_filename", "") or "plan.md")
        base = str(getattr(cfg, "output_dir", "") or "")
        if base or os.path.isabs(raw):
            return os.path.join(base, raw)
    except Exception:
        pass
    # Fallback: an explicit render target, when the canonical path is unresolvable.
    if rendered_target:
        try:
            ws = _ws_root(rt)
            if ws or os.path.isabs(rendered_target):
                return os.path.normpath(os.path.join(ws or "", rendered_target))
        except Exception:
            pass
    return None


def _persist_loop_end_from_log(rt, session_id: str) -> None:
    """Record the loop_end marker for a turn that finished in the background
    (no live observer). changed_files is derived from the current turn's rows
    in the SessionLog; duration from the runtime turn origin."""
    try:
        log = getattr(rt.agent, "session_log", None)
        if log is None or not hasattr(log, "record_loop_end"):
            return
        from app.backends.ms_agent.sessions import (
            changed_files_in_rows,
            latest_rendered_plan_md,
            plan_paths_in_rows,
        )

        rows = log.get_all_messages()
        # Scope to the last turn: assistant rows after the final user row.
        last_user = max(
            (i for i, r in enumerate(rows) if r.get("role") == "user"),
            default=-1,
        )
        # Idempotency: an explicit Stop drives BOTH the interrupt seal AND the
        # aborted-SSE drain, and each lands here. Write at most one loop_end per
        # turn — skip if this turn already has one (a loop_end whose seq is past
        # the last user row). get_loop_ends() re-reads from disk, so it sees the
        # other path's just-written marker; this fn is synchronous (no await) so
        # the check-then-write can't interleave with the other task.
        last_user_seq = rows[last_user].get("seq", -1) if last_user >= 0 else -1
        if hasattr(log, "get_loop_ends") and any(
            le.get("seq", -1) > last_user_seq for le in log.get_loop_ends()
        ):
            return
        turn_rows = rows[last_user + 1:]
        ws = _ws_root(rt)
        # Filter out-of-workspace writes + plan files (identified by the todo
        # tool's own reports, so any configured plan filename is caught).
        changed = changed_files_in_rows(turn_rows, ws) if ws else \
            changed_files_in_rows(turn_rows)
        origin = getattr(rt, "turn_started_at", None)
        duration_ms = int((time.monotonic() - origin) * 1000) if origin else 0
        payload = {"duration_ms": duration_ms, "changed_files": changed}
        if "plan.md" in changed:
            # Canonical plan.md (todo_write's); the latest render is a fallback.
            rendered = latest_rendered_plan_md(turn_rows, ws) if ws else None
            pf = _plan_md_path(rt, rendered)
            if pf:
                payload["plan_file"] = pf
        log.record_loop_end(payload)
    except Exception:
        logger.debug("loop_end (drain) record skipped", exc_info=True)


# Upper bound on waiting for a session's turn lock. A healthy turn releases it
# in seconds; only a turn wedged on a dead endpoint holds it this long (the LLM
# client itself times out around 300s). On timeout we drop the wedged runtime
# and rebuild, so a stuck turn can't make later requests hang forever.
_LOCK_ACQUIRE_TIMEOUT = 330.0


async def _acquire_live_runtime(project, session):
    """Acquire a runtime turn lock, rebuilding if the driver died while waiting
    or the lock stayed wedged past _LOCK_ACQUIRE_TIMEOUT."""
    while True:
        rt = await registry.get(project, session)
        try:
            await asyncio.wait_for(rt.turn_lock.acquire(), timeout=_LOCK_ACQUIRE_TIMEOUT)
        except asyncio.TimeoutError:
            await registry.close(session.id)  # drop the wedged runtime; rebuild next loop
            continue
        if not rt.run_task.done():
            return rt
        rt.turn_lock.release()


def _catalog_for(rt):
    """The runtime agent's SkillCatalog — the driver's own once prepare_skills
    ran, else one built from the resolved config (timing-independent: a
    freshly-built runtime hasn't reached prepare_skills yet)."""
    agent = getattr(rt, "agent", None)
    if agent is None:
        return None
    catalog = getattr(agent, "_skill_catalog", None)
    if catalog is not None:
        return catalog
    from ms_agent.skill.catalog import SkillCatalog

    skills_config = getattr(getattr(agent, "config", None), "skills", None)
    if not skills_config:
        return None
    catalog = SkillCatalog(config=skills_config)
    catalog.load_from_config(skills_config)
    return catalog


def _sync_runtime_skills(rt, project) -> None:
    """Turn-boundary skill sync for a live session runtime.

    A long-lived agent's catalog is built once at prepare_skills; skills.json
    edits and live-tree drops made after that (UI toggles, newly added or
    deleted skills) would otherwise stay invisible until the runtime is
    rebuilt. Called with the turn lock held (driver idle between turns):
    re-merge the managed skill layer into the agent's config (replayable —
    managed entries are origin-tagged and replaced wholesale) and resync the
    catalog in place. The version bump makes the SDK's per-round
    maybe_refresh_system_prompt() rebuild the system prompt only when the
    skill surface actually changed. Best-effort: on failure the turn runs
    with the previous catalog.
    """
    agent = getattr(rt, "agent", None)
    skill_runtime = getattr(agent, "_skill_runtime", None) if agent else None
    if skill_runtime is None:
        return  # driver not through prepare_skills yet — it reads fresh config
    try:
        from ms_agent.tui.managed_config import merge_skills_into_config

        merge_skills_into_config(agent.config, home(), project.path)
        skill_runtime.sync_with_config(agent.config.skills)
    except Exception:
        logger.debug("turn-boundary skill sync failed", exc_info=True)


def _strip_skill_token(text: str, skill) -> str:
    """Remove the first whitespace-delimited ``/<id>``/``/<name>`` token for
    the invoked skill, so the rest of the message becomes the arguments."""
    import re

    for candidate in (getattr(skill, "skill_id", ""), getattr(skill, "name", "")):
        if not candidate:
            continue
        pattern = re.compile(
            r"(?:(?<=\s)|^)/" + re.escape(candidate) + r"(?=\s|$)",
            re.IGNORECASE,
        )
        stripped, n = pattern.subn(" ", text, count=1)
        if n:
            # Mend the seam only (collapse doubled spaces/tabs); newlines and
            # the rest of the message stay untouched.
            return re.sub(r"[ \t]{2,}", " ", stripped).strip()
    return text.strip()


def _expand_skill_request(rt, prompt: str,
                          skill_ids: list[str]) -> tuple[str, str, dict | None] | None:
    """Two-tier slash-skill expansion (Route A runs no command router, so it
    happens here before enqueuing).

    Tier 1 — structured: the composer sent the picked ``skills`` ids; expand
    the first one with args = the prompt minus its ``/token`` (position-free,
    parse-free). Tier 2 — free text: scan for the first whitespace-delimited
    ``/token`` anywhere in the prompt that matches a catalog skill (covers
    hand-typed and API input; unknown ``/x`` falls through as plain text).

    Returns ``(kind, content, marker)`` where kind ∈ {"submit", "message"} and
    ``marker`` is the display-only skill-invocation record (submit only), or
    None when nothing expanded. Never raises.
    """
    from ms_agent.command.skill_bridge import (
        expand_skill,
        expand_slash_text,
        find_skill,
    )
    from ms_agent.command.types import CommandResultType

    try:
        catalog = _catalog_for(rt)
        if catalog is None:
            return None
        result = None
        invoked = None
        for sid in skill_ids:  # tier 1: first resolvable picked skill wins
            skill = find_skill(catalog, sid)
            if skill is None:
                continue
            invoked = skill
            result = expand_skill(
                catalog, sid, _strip_skill_token(prompt, skill))
            break
        if result is None:
            result = expand_slash_text(catalog, prompt)  # tier 2
            if result is not None:
                # Recover which skill matched (first known token) for the marker.
                import re as _re

                for m in _re.finditer(r"(?:(?<=\s)|^)/([\w.-]+)(?=\s|$)", prompt):
                    skill = find_skill(catalog, m.group(1))
                    if skill is not None:
                        invoked = skill
                        break
    except Exception:  # a broken skill must never break the chat
        logger.debug("skill expand failed; sending text verbatim", exc_info=True)
        return None
    if result is None:
        return None
    if result.type == CommandResultType.SUBMIT_PROMPT:
        # A composer skill pick with no typed text leaves prompt empty; fall
        # back to the slash form so history replay shows a readable bubble.
        shown = prompt or (
            f"/{invoked.skill_id}" if getattr(invoked, "skill_id", "") else prompt
        )
        marker = {
            "original_text": shown,
            "skill_ids": [getattr(invoked, "skill_id", "")] if invoked else [],
        }
        return ("submit", result.content or prompt, marker)
    if result.type == CommandResultType.MESSAGE:
        return ("message", result.content or "", None)
    return None  # MUTATE_STATE / QUIT are not modeled over the SSE turn (v1)


async def _apply_title(project, session_id: str, text: str) -> dict | None:
    """Generate an agent title + topic category for a session's first message and
    persist them (session name + ``category`` sidecar). Returns the applied
    ``{title, category}`` for the ``done`` frame, or None when generation failed
    (the cheap first-line title from ``autoname_session`` then stands)."""
    res = await titler.generate_title_and_category(text)
    if not res:
        return None
    title, category = res
    try:
        sm_for(project).update(session_id, name=title)
    except Exception:  # naming is best-effort; keep the fallback title
        logger.debug("title update failed", exc_info=True)
    try:
        sidecar.merge("sessions", session_id, {"category": category})
    except Exception:
        logger.debug("category persist failed", exc_info=True)
    return {"title": title, "category": category}


async def stream(req: ChatRequest) -> AsyncIterator[dict]:
    project, session = _resolve_or_create(req)
    session_id = session.id

    user_msg = req.message
    prompt = _compose_prompt(user_msg)
    # A bare skill pick (pill only, no text) is a valid submission — the skill
    # expansion below submits the skill body as the turn. Only truly empty
    # input returns.
    typed_text, picked_skill_ids = _content_parts(user_msg)
    if not prompt and not picked_skill_ids:
        done = ChatChunk(
            type="done",
            meta={"session_id": session_id, "project_id": project.id},
        )
        yield {"data": done.model_dump_json()}
        return

    # Name a new session: set a cheap first-line title immediately (so the list
    # updates without waiting), then, for a brand-new session, kick off an
    # agent-generated title + topic category concurrently with the turn. The
    # result is folded into the terminal `done` frame so the frontend refreshes
    # the conversation lists with the summarized title and category icon.
    # A bare skill pick has no typed text — seed with the slash form so the
    # cheap title / titler don't fall back to the expanded wrapper text.
    first_text = (
        typed_text
        or prompt
        or (f"/{picked_skill_ids[0]}" if picked_skill_ids else "")
    )
    # "Needs a real title" covers both the SDK default name AND a cheap
    # first-message slice (the project-page path pre-seeds title=text[:60] at
    # createSession, which otherwise permanently suppressed the LLM titler).
    needs_title = _is_default_name(session.name) or _is_cheap_title(
        session.name, first_text
    )
    autoname_session(project, session, first_text)
    title_task = (
        asyncio.create_task(_apply_title(project, session_id, first_text))
        if needs_title
        else None
    )

    # The session now exists on disk (created by _resolve_or_create, given a
    # cheap first-line title). Announce it immediately so the client refreshes
    # its conversation lists right away — without waiting for the whole turn or
    # the agent title. The `done` frame later carries the summarized title +
    # category for a second refresh and the URL redirect.
    yield _delta(ChatChunk(
        type="session",
        meta={"session_id": session_id, "project_id": project.id},
    ))

    # Acquire the turn lock FIRST, then sync skills and expand slash
    # invocations against the freshly-synced catalog. With the lock held the
    # driver is idle between turns, so the in-place catalog resync cannot race
    # a running generation, and the expansion sees mid-session skill changes
    # (the pre-sync ordering is why a newly added skill is now invocable in
    # the same session). `started` guards the lock across the pre-enqueue
    # yields: an intro-only reply or a client disconnect must release it.
    rt = await _acquire_live_runtime(project, session)
    marker: dict | None = None
    started = False
    try:
        _sync_runtime_skills(rt, project)

        # Skill-update notice (tail-only sync): compare the freshly-synced
        # catalog against what this session was last told (skill_surface.json)
        # and, on drift, prefix this turn's prompt with a <system-reminder>
        # carrying the full current list. The sidecar is committed only after
        # the turn is actually enqueued — an intro-only reply or a failed
        # enqueue re-fires the notice next turn instead of losing it.
        notice: str | None = None
        commit_notice = None
        catalog0 = _catalog_for(rt)
        if catalog0 is not None:
            try:
                from app.backends.ms_agent.skill_notice import pending_notice

                notice, commit_notice = pending_notice(catalog0, project, session)
            except Exception:
                logger.debug("skill notice check failed", exc_info=True)
        user_typed = prompt  # pre-expansion text, for the display marker

        # Slash-skill invocation, two tiers (Route A doesn't route commands,
        # so it happens here): the composer's structured `skills` ids first,
        # else a scan for a whitespace-delimited /token anywhere in the text.
        # Any invocation — with or without args — runs the enriched skill
        # prompt as the turn (a bare /skill submits the skill body so the
        # model reads it and acts); a display-only marker keeps the user's
        # ORIGINAL text for history replay. The "message" branch below stays
        # as a fallback for other CommandResult kinds.
        skill_ids = _content_parts(user_msg)[1]
        if skill_ids or "/" in prompt:
            expanded = _expand_skill_request(rt, prompt, skill_ids)
            if expanded is not None:
                kind, content, marker = expanded
                if kind == "message":
                    if content:
                        yield _delta(ChatChunk(type="text", content=content))
                    done = ChatChunk(
                        type="done",
                        meta={"session_id": session_id, "project_id": project.id},
                    )
                    yield {"data": done.model_dump_json()}
                    return
                prompt = content  # "submit": run the enriched skill prompt as the turn

        if notice:
            # Prepend AFTER expansion so token stripping never sees the
            # notice. The model reads the notice; the UI shows the typed text
            # via the display marker (same mechanism as slash expansion).
            prompt = notice + "\n\n" + prompt
            if marker is None:
                marker = {"original_text": user_typed, "skill_ids": []}

        if marker is not None and isinstance(
            getattr(user_msg, "content", None), list
        ):
            # Persist the configuration-style segments AS SENT (skill id +
            # display name + text) so history replays exactly what the user
            # saw in the composer (pills with readable names, not raw ids).
            marker["segments"] = [s.model_dump() for s in user_msg.content]
        elif marker is None and isinstance(
            getattr(user_msg, "content", None), list
        ) and any(s.type == "skill" for s in user_msg.content):
            # Skill pills were sent but nothing expanded (e.g. the skill was
            # deleted): still persist a display marker so the echo keeps the
            # pills instead of silently dropping them.
            marker = {
                "original_text": user_typed,
                "skill_ids": [],
                "segments": [s.model_dump() for s in user_msg.content],
            }

        completed = False
        rt.sink.new_turn()  # this turn owns the event buffer from here
        await rt.enqueue(prompt, marker=marker)
        # Turn wall-clock origin on the runtime, so whoever observes the turn's
        # end (this live stream OR the background drain) records the same
        # loop_end duration regardless of when the client left.
        rt.turn_started_at = time.monotonic()
        # Wall-clock twin of the origin, for comparisons against file mtimes
        # (e.g. "was plan.json written during THIS turn" in sessions.read_plan).
        rt.turn_started_wall = time.time()
        rt.watchers += 1  # a live SSE consumer is streaming this turn
        started = True
        if notice and commit_notice is not None:
            commit_notice()  # the model has now been told — persist the surface
    finally:
        if not started and rt.turn_lock.locked():
            rt.turn_lock.release()
    usage = None
    error_sent = False
    mapper = _TurnMapper(session_id)
    pos = 0
    # This turn = one tool-call loop. Track wall-clock + files written/edited so
    # the terminal `done` frame can carry a loop summary (frontend collapses the
    # intermediate steps into a "done · Ns" header listing what changed). The
    # history-replay counterpart is SessionMessage.changed_files.
    loop_start = time.monotonic()
    changed_live: list[str] = []
    changed_seen: set[str] = set()

    ws = _ws_root(rt)

    def _collect_changed(chunks: list) -> None:
        # Keep RAW write/edit paths (as the tool phrased them); classification
        # into workspace-relative deliverables happens at _changed_files() time,
        # once all of this turn's plan reports are known.
        for c in chunks:
            meta = getattr(c, "meta", None) or {}
            if c.type == "step" and meta.get("kind") in ("file_write", "file_edit"):
                p = str(meta.get("path") or "")
                if p and p not in changed_seen:
                    changed_seen.add(p)
                    changed_live.append(p)

    def _changed_files() -> list[str]:
        # Workspace deliverables written/edited this loop, plus the reserved
        # "plan.md" marker when the todo plan changed. A write is a deliverable
        # only if it resolves INSIDE the workspace and isn't a plan file — the
        # model may copy its plan into the session dir (via ``..``/absolute) or
        # render it under any name; those are plan/session state, surfaced by
        # the plan chip (content via GET /sessions/{id}/plan), not file cards.
        from app.backends.ms_agent.sessions import (
            _resolve_tool_path,
            _workspace_rel,
        )

        files: list[str] = []
        if ws:
            plan_abs = {
                _resolve_tool_path(ws, r) for r in mapper.plan_reports
            }
            for p in changed_live:
                ap = _resolve_tool_path(ws, p)
                if ap in plan_abs:
                    continue
                rel = _workspace_rel(ws, ap)
                if rel is not None:
                    files.append(rel)
        else:
            files = list(changed_live)
        if mapper.plan_touched and "plan.md" not in files:
            files.append("plan.md")
        return files

    def _loop_duration_ms() -> int:
        # Prefer the runtime turn origin (shared with the background drain), so
        # live and replay report the same duration; fall back to this stream's
        # observation start.
        origin = getattr(rt, "turn_started_at", None) or loop_start
        return int((time.monotonic() - origin) * 1000)

    def _loop_meta() -> dict:
        # One summary shape for both the `done` frame and the persisted
        # loop_end marker. When the turn touched the todo list, `plan_file`
        # carries the plan markdown's ABSOLUTE path (session dir under webui
        # config) so the frontend can key the plan chip without an
        # exists-in-workspace check ("plan.md" in changed_files is the marker,
        # plan_file the location; content via GET /sessions/{id}/plan).
        meta = {
            "changed_files": _changed_files(),
            "duration_ms": _loop_duration_ms(),
        }
        if mapper.plan_touched:
            # The canonical plan.md todo_write maintains (consistent with
            # GET /plan); the latest todo_render_md target is only a fallback.
            pf = _plan_md_path(rt, mapper.latest_plan_md_report)
            if pf:
                meta["plan_file"] = pf
        return meta

    def _persist_loop_end() -> None:
        # Durable loop boundary so history replay can reproduce the "done · Ns"
        # summary (duration is not derivable from message rows). Best-effort;
        # written once per turn by whoever observes its end.
        try:
            log = getattr(rt.agent, "session_log", None)
            if log is not None and hasattr(log, "record_loop_end"):
                log.record_loop_end(_loop_meta())
        except Exception:
            logger.debug("loop_end record skipped", exc_info=True)

    async def _title_meta() -> dict:
        """Await the concurrent titling task (if any) and return its meta for the
        `done` frame. Best-effort: an error/timeout just omits title+category."""
        if title_task is None:
            return {}
        try:
            res = await title_task
        except Exception:
            return {}
        return {"title": res["title"], "category": res["category"]} if res else {}

    try:
        # Turn age first: the client bases its "processing Ns" counter on the
        # server clock from frame one (and re-bases on the periodic re-send).
        yield _turn_frame(rt)
        last_turn_sync = time.monotonic()
        while True:
            payload, pos = await rt.sink.next_event(pos)
            t = payload.get("type")

            if t in (TURN_END, DRIVER_DONE):
                flushed = mapper.flush()
                _collect_changed(flushed)
                for chunk in flushed:
                    yield _delta(chunk)
                _persist_loop_end()  # durable loop boundary (before the done frame)
                done = ChatChunk(
                    type="done",
                    meta={
                        "session_id": session_id,
                        "project_id": project.id,
                        "usage": usage,
                        **_loop_meta(),
                        **(await _title_meta()),
                    },
                )
                completed = True
                yield {"data": done.model_dump_json()}
                return
            if t == DRIVER_ERROR:
                completed = True
                if not error_sent:
                    yield _delta(ChatChunk(type="error", meta={
                        "message": payload.get("message", ""),
                        "recoverable": bool(payload.get("recoverable", False)),
                    }))
                _persist_loop_end()
                done = ChatChunk(
                    type="done",
                    meta={
                        "session_id": session_id,
                        "project_id": project.id,
                        **_loop_meta(),
                        **(await _title_meta()),
                    },
                )
                yield {"data": done.model_dump_json()}
                return
            if t == "turn_completed":
                usage = payload.get("usage")  # per-round; kept for the done frame
                continue

            if t == "error":
                error_sent = True
            mapped = mapper.map(payload)
            _collect_changed(mapped)
            for chunk in mapped:
                yield _delta(chunk)
            if time.monotonic() - last_turn_sync >= _TURN_SYNC_INTERVAL:
                yield _turn_frame(rt)  # re-base the client's counter
                last_turn_sync = time.monotonic()
    finally:
        rt.watchers -= 1  # this live consumer is gone (finished or left)
        if completed:
            if rt.turn_lock.locked():
                rt.turn_lock.release()
        else:
            # Client left mid-turn without an explicit stop (navigated away,
            # refreshed, or closed the browser): keep the turn running in the
            # background and release the lock at the turn boundary, so the
            # conversation finishes and persists — and a viewer can re-attach
            # via POST /api/chat/attach. Only POST /api/chat/interrupt cancels.
            asyncio.create_task(_drain_abandoned_turn(rt, pos, session_id))


async def attach(session_id: str) -> AsyncIterator[dict]:
    """Re-attach a viewer to a session's in-flight turn (SSE).

    Replays the current turn's buffered events from the start (full catch-up:
    thoughts with their real elapsed times, steps, text so far) and then
    follows the live tail until the turn boundary — the same ChatChunk protocol
    as POST /api/chat, so the frontend renders it identically. When no turn is
    in flight, emits just a `done` frame (the viewer falls back to history).
    """
    rt = registry.peek(session_id)
    if rt is None or not registry.is_running(session_id):
        done = ChatChunk(type="done", meta={"session_id": session_id})
        yield {"data": done.model_dump_json()}
        return

    rt.watchers += 1  # a live viewer is streaming this turn again
    usage = None
    # Pre-scan the event buffer so replayed authorization cards show their REAL
    # state instead of stale pending buttons. Truth sources (not heuristics):
    # - the live handler's `_pending` futures: a request still awaiting the
    #   user replays as pending (buttons work — the Future is alive);
    # - everything else was decided; the decision's approve/reject state comes
    #   from the persisted permission records (written at resolve time).
    # The old "any event after the ask means approved" inference broke the
    # common case of an APPROVED slow tool: no event follows while it runs, so
    # a refresh replayed dead pending buttons whose clicks could only fail
    # (the Future was long resolved → the card flipped to "rejected").
    resolved_perms: list[dict] = []
    try:
        buf = list(rt.sink._events)
        perm_events = [
            ev for ev in buf if ev.get('type') == 'permission_request'
        ]
        if perm_events:
            handler = getattr(rt, 'permission_handler', None)
            pending_ids = {
                rid
                for rid, fut in (getattr(handler, '_pending', None) or {}).items()
                if not fut.done()
            }
            records: list[dict] = []
            try:
                found = find_session(session_id)
                if found:
                    _proj, _sess, sm = found
                    log = sm.get_session_log(_sess)
                    if hasattr(log, 'get_permissions'):
                        records = list(log.get_permissions())
            except Exception:
                records = []
            for ev in perm_events:
                rid = str(ev.get('request_id') or '')
                if rid and rid in pending_ids:
                    continue  # genuinely awaiting the user's decision
                call_id = str(ev.get('call_id') or '')
                tool = str(ev.get('tool_name') or '')
                rec = next(
                    (r for r in records
                     if call_id and str(r.get('call_id') or '') == call_id),
                    None,
                ) or next(
                    (r for r in records if r.get('tool_name') == tool),
                    None,
                )
                resolved_perms.append({
                    'tool_name': tool,
                    'call_id': call_id,
                    # A decided ask with no record yet (persistence raced) can
                    # only have been approved — a denial ends the call at once.
                    'state': str((rec or {}).get('state') or 'approved'),
                })
    except Exception:
        pass
    mapper = _TurnMapper(session_id, resolved_permissions=resolved_perms)
    pos = 0
    try:
        # The rejoining client (a reload, or a second viewer) has no idea when
        # this turn started — tell it, before replaying anything, so its
        # "processing Ns" counter continues instead of restarting at zero.
        yield _turn_frame(rt)
        last_turn_sync = time.monotonic()
        while True:
            payload, pos = await rt.sink.next_event(pos)
            t = payload.get("type")
            if t in (TURN_END, DRIVER_DONE, DRIVER_ERROR):
                for chunk in mapper.flush():
                    yield _delta(chunk)
                if t == DRIVER_ERROR:
                    yield _delta(ChatChunk(type="error", meta={
                        "message": payload.get("message", ""),
                        "recoverable": bool(payload.get("recoverable", False)),
                    }))
                done = ChatChunk(
                    type="done", meta={"session_id": session_id, "usage": usage}
                )
                yield {"data": done.model_dump_json()}
                return
            if t == "turn_completed":
                usage = payload.get("usage")
                continue
            for chunk in mapper.map(payload):
                yield _delta(chunk)
            if time.monotonic() - last_turn_sync >= _TURN_SYNC_INTERVAL:
                yield _turn_frame(rt)  # re-base the client's counter
                last_turn_sync = time.monotonic()
    finally:
        rt.watchers -= 1
