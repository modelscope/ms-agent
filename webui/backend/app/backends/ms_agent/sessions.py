"""Sessions adapter — SessionManager (+ cross-project find) + sidecar preview."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from app.backends.errors import NotFound
from app.backends.ms_agent import sidecar
from app.backends.ms_agent.common import (
    autoname_session,
    find_session,
    pm,
    resolve_project,
    sm_for,
)
from app.backends.ms_agent.mapping import session_to_schema
from app.core.filetypes import guess_type
from app.schemas.session import (
    Artifact,
    Session,
    SessionCreate,
    SessionFile,
    SessionMessage,
    SessionPart,
    SessionPlan,
    SessionStep,
    SessionTask,
    SessionUpdate,
)


def list_sessions(project_id: str | None = None) -> list[Session]:
    manager = pm()
    if project_id:
        proj = manager.get(project_id)
        projects = [proj] if proj is not None else []
    else:
        projects = manager.list()

    out: list[Session] = []
    for proj in projects:
        for s in sm_for(proj).list():
            # backfill a display title for still-default sessions that have history
            out.append(autoname_session(proj, s))
    out.sort(key=lambda s: s.updated_at, reverse=True)
    return [_with_running(session_to_schema(s)) for s in out]


def _with_running(schema: Session) -> Session:
    """Stamp the live turn-in-flight flag (registry state; lazy import keeps
    mapping.py free of a runtime dependency)."""
    from app.backends.ms_agent.runtime import registry

    schema.running = registry.is_running(schema.id)
    return schema


def create_session(body: SessionCreate) -> Session:
    try:
        project = resolve_project(body.project_id)
    except KeyError:
        project = resolve_project(
            None)  # unknown id -> default (mock is lenient)
    session = sm_for(project).create(name=body.title)
    if body.preview:
        sidecar.merge("sessions", session.id, {"preview": body.preview})
    return session_to_schema(session)


def get_session(sid: str) -> Session:
    found = find_session(sid)
    if not found:
        raise NotFound("session not found")
    _project, session, _sm = found
    return _with_running(session_to_schema(session))


def _history_step(
    tc: dict,
    errored: dict[str, str],
    results: dict[str, str],
    durations: dict[str, int],
    project=None,
) -> SessionStep | None:
    """Map one persisted assistant tool_call to a step card, or None to drop it.

    Reuses the live event mapping so history renders the same step cards. The
    log shape differs from the live event: the tool name is under ``tool_name``
    (or a nested ``function.name``) and ``arguments`` is a raw JSON string. The
    tool result is looked up by call id in ``results`` (and ``errored`` for a
    failed call), so the detail drawer shows the full invocation like a live
    step; ``durations`` supplies the persisted elapsed time (``duration_ms``);
    a failed call is marked ``status="error"``.

    For ``file_read``/``file_write``/``file_edit`` cards, ``meta["exists"]``
    records whether the referenced workspace file is still present so the
    frontend can open it (or render a non-clickable "deleted" card when it's
    gone).
    """
    from app.backends.ms_agent.chat import _as_dict, _tool_step_meta

    fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
    name = tc.get("tool_name") or fn.get("name") or ""
    args = _as_dict(tc.get("arguments", fn.get("arguments")))
    meta = _tool_step_meta(str(name), args)
    if meta is None:
        return None
    kind = str(meta.pop("kind"))
    # Full invocation for the detail drawer (mirrors the live _tool_step).
    meta["tool"] = str(name)
    meta["arguments"] = args
    call_id = str(tc.get("id") or "")
    if call_id and call_id in results:
        meta["result"] = results[call_id]
    if call_id and call_id in durations:
        meta["duration_ms"] = durations[call_id]
    if call_id and call_id in errored:
        meta["status"] = "error"
        meta["error"] = errored[call_id]
        # A DENIED call is already rendered by its persisted permission record
        # (the rejected authorization card) — drop this redundant tool step so
        # history doesn't show two identical "rejected" cards.
        if "denied" in str(errored[call_id]).lower():
            return None
    # NOTE: an errored/interrupted file step used to be re-kinded to `tool_call`
    # here, to get the rich accordion (arguments + error) instead of the
    # simplified "wrote x" one-liner. The file card renders that accordion itself
    # now — keeping the file's glyph and "write file {path}" title — so re-kinding
    # only threw the identity away and replayed "call tool file_system---write_file"
    # where the live stream shows the file.
    if kind in ("file_read", "file_write",
                "file_edit") and project is not None:
        # Multi-file steps carry `paths: [...]`; the display `path` is a
        # comma-joined string that would never resolve. Check each real file
        # and mark existing only when ALL are present (single-file steps just
        # check their one `path`).
        multi = meta.get("paths")
        try:
            if isinstance(multi, list) and multi:
                meta["exists"] = all(
                    (Path(project.path) / str(p)).is_file() for p in multi
                )
            else:
                path = str(meta.get("path") or "")
                if path:
                    meta["exists"] = (Path(project.path) / path).is_file()
        except OSError:
            meta["exists"] = False
    return SessionStep(kind=kind, meta=meta)


def _permission_step(row: dict) -> SessionStep | None:
    """Build a replayed (read-only) authorization card from a persisted
    permission record, or None to drop it. Mirrors the live
    ``chat._permission_step`` meta shape, minus the live-only
    request_id/session_id (a replayed card is resolved, so it renders its
    ``state`` and shows no buttons).

    Asks folded into their tool's own card while live (``_AUTH_INLINE_KINDS``,
    e.g. a shell command) replay the same way, so a rejected command still shows
    its terminal code block. An APPROVED one is dropped: its tool step replayed
    right after says the same thing (that is what the live stream ends up
    showing too, the result card having replaced the ask in place).
    """
    tool = str(row.get("tool_name") or "")
    args = row.get("arguments") if isinstance(row.get("arguments"),
                                              dict) else {}
    preview = json.dumps(args, ensure_ascii=False)
    if len(preview) > 160:
        preview = preview[:160] + "…"
    from app.backends.ms_agent.chat import _inline_auth_meta, _tool_source

    state = str(row.get("state") or "approved")
    meta = _inline_auth_meta(
        {
            "kind": "authorization",
            "state": state,
            "tool_name": tool,
            "arguments": args,
            "desc": f"{tool} {preview}".strip(),
            "source": _tool_source(tool),
        }, tool, args)
    kind = str(meta.pop("kind"))
    if kind != "authorization" and state == "approved":
        return None
    return SessionStep(kind=kind, meta=meta)


def _plan_entries(tc: dict, results: dict[str, str]) -> list | None:
    """Extract the plan (todo) items from a persisted ``todo_list---todo_write``
    call, or None if this call isn't a plan write.

    Prefers the tool RESULT's ``todos`` (the authoritative full plan after the
    tool merges status updates), falling back to the call arguments. This lets
    history rebuild the plan the same way the live ``plan_updated`` event does.
    """
    from app.backends.ms_agent.chat import _as_dict

    fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
    name = str(tc.get("tool_name") or fn.get("name") or "")
    base, _, leaf = name.partition("---")
    if base != "todo_list" or leaf != "todo_write":
        return None
    call_id = str(tc.get("id") or "")
    if call_id in results:
        try:
            data = json.loads(results[call_id])
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict) and isinstance(data.get("todos"), list):
            return data["todos"]
    todos = _as_dict(tc.get("arguments", fn.get("arguments"))).get("todos")
    return todos if isinstance(todos, list) else None


def _plan_part(entries: list) -> SessionPart:
    """Build the single ``tasks`` plan part from todo entries, mapping each
    todo status to the frontend task status (mirrors chat.py::_tasks)."""
    from app.backends.ms_agent.chat import _PLAN_STATUS

    tasks: list[SessionTask] = []
    for i, entry in enumerate(entries):
        entry = entry if isinstance(entry, dict) else {"content": str(entry)}
        tasks.append(
            SessionTask(
                id=str(i),
                label=str(entry.get("content", "")),
                status=_PLAN_STATUS.get(str(entry.get("status", "pending")),
                                        "pending"),
            ))
    return SessionPart(kind="tasks", tasks=tasks)


def _disk_plan(plan_path: str) -> list | None:
    """The todos in a ``plan.json`` — the agent's live plan file, which also
    captures any manual edits — or None if absent/unparseable."""
    try:
        with open(plan_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    todos = data.get("todos") if isinstance(data, dict) else None
    return todos if isinstance(todos, list) else None


def read_plan(session_id: str) -> SessionPlan:
    """The pinned composer plan box reflects the session's live ``plan.json``
    — the plan file written by the todo_list tool and by any manual edits. It
    deliberately ignores the chat/session log.

    Plans are SESSION-scoped: ``build_agent`` points the todo tool at
    ``<session_dir>/plan.json`` so concurrent sessions in one project no longer
    clobber each other's plans. Sessions created before that change fall back
    to the legacy project-shared ``<project.path>/plan.json``. Empty when
    neither exists or the file can't be parsed.

    ``active`` = a turn is in flight AND the plan file was written during it
    (mtime vs the runtime's wall-clock turn origin) — the server-side truth
    the frontend uses to animate "running" rows, stable across reloads and
    tab switch-backs."""
    found = find_session(session_id)
    if not found:
        return SessionPlan()
    project, session, _ = found
    from app.backends.ms_agent.config import session_dir

    plan_path = os.path.join(session_dir(project, session), "plan.json")
    todos = _disk_plan(plan_path)
    if todos is None:  # pre-isolation sessions used a project-shared plan
        plan_path = os.path.join(project.path, "plan.json")
        todos = _disk_plan(plan_path)
    if todos is None:
        return SessionPlan()

    active = False
    try:
        from app.backends.ms_agent.runtime import registry

        if registry.is_running(session_id):
            rt = registry.peek(session_id)
            started_wall = getattr(rt, "turn_started_wall", None)
            if started_wall is not None:
                # 1s slack: the tool may write the file in the same tick the
                # origin is stamped.
                active = os.path.getmtime(plan_path) >= started_wall - 1.0
    except Exception:
        active = False
    return SessionPlan(tasks=_plan_part(todos).tasks, active=active)


def list_messages(sid: str) -> list[SessionMessage]:
    found = find_session(sid)
    if not found:
        raise NotFound("session not found")
    project, session, sm = found
    rows: list[dict] = []
    extra: list[dict] = []
    try:
        log = sm.get_session_log(session)
        rows = log.get_all_messages()
        # Display-only records (excluded from the LLM context) are read
        # separately and merged back into the timeline by seq: error records
        # (API/turn errors) and permission records (restricted-mode auth cards).
        if hasattr(log, "get_errors"):
            extra += log.get_errors()
        if hasattr(log, "get_permissions"):
            extra += log.get_permissions()
        if hasattr(log, "get_skill_invocations"):
            extra += log.get_skill_invocations()
        if hasattr(log, "get_loop_ends"):
            extra += log.get_loop_ends()
    except Exception:
        rows, extra = [], []
    stream = sorted([*rows, *extra], key=lambda r: r.get("seq", 0))
    return _reconstruct(stream, project)


# Marker prefixed to the enqueued prompt by chat._compose_prompt when the user
# attached files. Reconstruction splits it back out so replay shows file cards
# instead of the raw path list.
_ATTACHED_MARKER = "[Attached files]"


def _split_attached(content: str) -> tuple[str, list[str]]:
    """Split a persisted user message into (display_text, attached_paths).

    The attachment block (see chat._compose_prompt) lists ``- <path>`` lines
    after the marker. Everything before the marker is the user's typed text.
    """
    idx = content.find(_ATTACHED_MARKER)
    if idx == -1:
        return content, []
    text = content[:idx].strip()
    paths: list[str] = []
    for line in content[idx:].splitlines():
        line = line.strip()
        if line.startswith("- "):
            p = line[2:].strip()
            if p:
                paths.append(p)
    return text, paths


def _file_kind(name: str) -> str:
    ct = guess_type(name) or ""
    if ct.startswith("image/"):
        return "image"
    if ct.startswith("audio/"):
        return "audio"
    if ct.startswith("video/"):
        return "video"
    return "file"


def _raw_url(pid: str, path: str) -> str:
    enc = "/".join(quote(seg) for seg in path.split("/"))
    return f"/api/projects/{quote(pid)}/workspace/files/{enc}/raw"


def _attached_files(project, paths: list[str]) -> list[SessionFile]:
    root = Path(project.path)
    out: list[SessionFile] = []
    for p in paths:
        size: int | None = None
        try:
            fp = root / p
            exists = fp.is_file()
            if exists:
                size = fp.stat().st_size
        except OSError:
            exists = False
        out.append(
            SessionFile(
                name=p.split("/")[-1],
                path=p,
                url=_raw_url(project.id, p),
                type=_file_kind(p),
                size=size,
                exists=exists,
            ))
    return out


def _reconstruct(rows: list[dict], project=None) -> list[SessionMessage]:
    """Rebuild ordered display messages from the append-only log.

    One logical assistant turn spans several rows (tool-call rows carrying
    placeholder text + a final answer row + interleaved tool results). Collapse
    them into a single assistant bubble whose ``parts`` preserve the real order
    of answer text and the tool/step timeline: an assistant row's persisted
    ``reasoning_content`` becomes a ``thought`` part (in row order, before that
    row's answer/steps); answer-text rows become ``text`` parts; each tool_call
    row becomes its own linear ``step`` part in stream order (no task nesting).
    A failed tool result (``role="tool"`` + ``is_error``) marks its step
    ``status="error"``. A ``_type="error"`` record (API/turn error, excluded
    from model context) becomes its own ``error`` message. Rows re-appended by
    context compaction (``_source="compaction"`` — the squeezed LLM view, incl.
    the synthetic summary row) are skipped: history shows the original
    timeline. ``system`` and plain ``tool`` rows are otherwise dropped.
    """
    from app.backends.ms_agent.chat import is_placeholder_content

    # Failed tool results keyed by call id, so the matching tool_call step can be
    # marked errored (the assistant tool_call row precedes its tool result row).
    errored: dict[str, str] = {
        str(r.get("tool_call_id") or ""): str(r.get("content") or "")
        for r in rows if r.get("role") == "tool" and r.get("is_error")
    }
    # All tool results by call id, so a step can show its full result content.
    results: dict[str, str] = {
        str(r.get("tool_call_id") or ""): str(r.get("content") or "")
        for r in rows if r.get("role") == "tool"
    }
    # Persisted tool elapsed time by call id (display only), for the step card.
    durations: dict[str, int] = {
        str(r.get("tool_call_id") or ""): int(r.get("duration_ms"))
        for r in rows if r.get("role") == "tool"
        and isinstance(r.get("duration_ms"), (int, float))
    }

    # Workspace root + the session's plan-file locations (reported by the todo
    # tool in these rows), for classifying file writes into the changed-files
    # summary: out-of-workspace writes and plan files are not deliverables.
    ws = _ws_root(project)
    plan_paths = plan_paths_in_rows(rows, ws) if ws else None

    messages: list[SessionMessage] = []
    parts: list[SessionPart] = []
    # Tool-round group id: one assistant row's tool_calls array = one round
    # (mirrors the live mapper's `group` stamping on step metas).
    group_seq = 0
    # Skill-invocation marker of a slash/structured skill turn: carries the
    # user's ORIGINAL text + picked skill ids, shown in place of the expanded
    # prompt on the user row that follows (and echoed as segments).
    pending_skill: dict | None = None
    # Restricted-mode authorization records awaiting their matching tool_call
    # step. They persist EAGERLY at ask() time (mid-round), so their seq
    # predates the assistant reasoning/tool_call rows persisted at the round
    # boundary — replaying them at their seq position would wrongly place the
    # auth card before the turn's thought, splitting it from its tool step. We
    # instead buffer them and insert each card immediately before the step it
    # authorized (matched by tool + arguments), so replay order matches live
    # (thought → auth → tool step, adjacent). Unmatched ones flush at turn end.
    pending_perms: list[dict] = []
    # Workspace paths written/edited in the current turn's tool-call loop, for
    # the assistant message's changed-files summary (frontend collapse).
    turn_changed: list[str] = []
    turn_changed_seen: set[str] = set()
    # Wall-clock loop duration from this turn's persisted loop_end marker (the
    # one field not derivable from message rows). None until the marker is seen.
    turn_duration_ms: int | None = None
    # Absolute path of the session plan markdown (loop_end marker's
    # ``plan_file``), set when the turn rewrote the todo list.
    turn_plan_file: str | None = None

    def _perm_key(tool: str, args) -> str:
        # Normalize dict or JSON-string arguments to a canonical form so a
        # permission record matches its tool_call regardless of shape.
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (ValueError, TypeError):
                args = {}
        if not isinstance(args, dict):
            args = {}
        return tool + "\x1f" + json.dumps(
            args, sort_keys=True, ensure_ascii=False)

    def _take_matching_perm(tool: str, args, call_id: str = "") -> dict | None:
        # Prefer an exact tool_call-id match (unambiguous even when a round
        # fires several identical calls in parallel); fall back to
        # (tool, args) FIFO for records that predate call_id (old logs) or when
        # the adapter hadn't assigned an id at ask time.
        if call_id:
            for i, rec in enumerate(pending_perms):
                if str(rec.get("call_id") or "") == call_id:
                    return pending_perms.pop(i)
        # Fallback: (tool, args) FIFO over whatever remains — covers old logs,
        # empty ids, and id-bearing records whose call had no id at match time.
        key = _perm_key(tool, args)
        for i, rec in enumerate(pending_perms):
            if _perm_key(str(rec.get("tool_name") or ""),
                         rec.get("arguments")) == key:
                return pending_perms.pop(i)
        return None

    def flush() -> None:
        nonlocal parts, pending_perms, turn_changed, turn_changed_seen
        nonlocal turn_duration_ms, turn_plan_file
        # Any authorization that never matched a tool step (unusual) still
        # renders, appended in record order so nothing is dropped.
        for rec in pending_perms:
            pstep = _permission_step(rec)
            if pstep is not None:
                parts.append(SessionPart(kind="step", step=pstep))
        pending_perms = []
        content = "\n\n".join(p.text for p in parts
                              if p.kind == "text" and p.text).strip()
        if content or any(p.kind in ("step", "thought", "tasks", "interrupted",
                                     "error") for p in parts):
            messages.append(
                SessionMessage(role="assistant",
                               content=content,
                               parts=parts,
                               changed_files=turn_changed,
                               duration_ms=turn_duration_ms,
                               plan_file=turn_plan_file))
        parts = []
        turn_changed = []
        turn_changed_seen = set()
        turn_duration_ms = None
        turn_plan_file = None

    def append_text(text: str) -> None:
        # Merge consecutive answer rows into the current text block; start a new
        # block if a step was emitted in between (preserving stream order).
        if parts and parts[-1].kind == "text":
            prev = parts[-1].text
            parts[-1].text = f"{prev}\n\n{text}" if prev else text
        else:
            parts.append(SessionPart(kind="text", text=text))

    for row in rows:
        if row.get("_source") == "compaction":
            # Compacted-view re-appends duplicate earlier rows for the LLM
            # window only; replaying them would double the timeline.
            continue
        if row.get("_type") == "loop_end":
            # Persisted loop boundary: carries the wall-clock duration for this
            # turn (its seq lands after the turn's rows, before the next user
            # row, so it applies to the turn being accumulated). changed_files
            # is still derived below (robust); duration and the plan-file
            # location are taken from the marker.
            d = row.get("duration_ms")
            if isinstance(d, (int, float)):
                turn_duration_ms = int(d)
            pf = row.get("plan_file")
            if isinstance(pf, str) and pf:
                turn_plan_file = pf
            continue
        if row.get("_type") == "error":
            # Accumulate into the CURRENT turn instead of flushing it early.
            # Flushing here emitted the error as its own message and closed the
            # turn before the `loop_end` marker (which lands at a later seq) had
            # been read — so the turn's duration was applied to an already-empty
            # part list and dropped, and replay showed no "N s" where the live
            # view had one. Accumulating also matches the live stream, where an
            # error frame is just another part of the running message.
            parts.append(
                SessionPart(
                    kind="error",
                    text=str(row.get("message") or ""),
                    recoverable=bool(row.get("recoverable", False)),
                ))
            continue
        if row.get("_type") == "permission":
            # Buffer until its matching tool_call step is emitted (see
            # pending_perms above); keeps the auth card adjacent to the tool it
            # authorized, matching the live frame order.
            pending_perms.append(row)
            continue
        if row.get("_type") == "skill_invocation":
            # A slash-skill turn persists the EXPANDED prompt as the user row
            # (that is what the model must see); this marker precedes it and
            # carries what the user actually typed + the picked skill ids
            # (and, for configuration-style turns, the segments as sent).
            pending_skill = {
                "original_text":
                str(row.get("original_text") or ""),
                "skill_ids":
                [str(s) for s in (row.get("skill_ids") or []) if s],
                "segments": [
                    s for s in (row.get("segments") or [])
                    if isinstance(s, dict)
                ],
            }
            continue
        role = row.get("role")
        if role == "user":
            flush()
            content = row.get("content")
            if content is not None:
                display = (pending_skill
                           or {}).get("original_text") or str(content)
                skill_ids = (pending_skill or {}).get("skill_ids") or []
                sent_segments = (pending_skill or {}).get("segments") or []
                pending_skill = None
                text, paths = _split_attached(display)
                files = (_attached_files(project, paths)
                         if paths and project is not None else [])
                # Configuration-style echo: prefer the segments AS SENT by the
                # composer (skill id + display name + text); fall back to
                # rebuilding from bare skill ids for older records.
                if sent_segments:
                    segments = sent_segments
                elif skill_ids:
                    segments = [{
                        "type": "skill",
                        "id": sid
                    } for sid in skill_ids] + ([{
                        "type": "text",
                        "text": text.strip()
                    }] if text.strip() else [])
                else:
                    segments = []
                messages.append(
                    SessionMessage(
                        role="user",
                        content=text,
                        files=files,
                        segments=segments,
                    ))
        elif role == "assistant":
            # An interrupted round's unsigned partial reasoning is persisted
            # under a display-only key (replaying it would 400 on Anthropic);
            # it renders as a normal finished thought block.
            reasoning = row.get("reasoning_content") or row.get(
                "interrupted_reasoning")
            if reasoning:
                # One persisted reasoning block per assistant row, placed before
                # that row's answer text / tool steps (stream order); its elapsed
                # time replays as "thought Ns".
                dur = row.get("reasoning_duration")
                parts.append(
                    SessionPart(
                        kind="thought",
                        text=str(reasoning),
                        duration=int(dur) if isinstance(dur,
                                                        (int,
                                                         float)) else None,
                    ))
            tool_calls = row.get("tool_calls")
            if tool_calls:
                # This row's content is the model's mid-turn narration: the
                # live stream showed it, so replay does too — verbatim. Only an
                # empty string (→ empty text part) or framework filler is
                # skipped (same rule as the no-tool-call branch below, so a
                # ``content_placeholder`` row is honored whatever its shape).
                narration = str(row.get("content") or "")
                if narration and not is_placeholder_content(row):
                    append_text(narration)
                # SERVER-SIDE grouping truth: this assistant row's tool_calls
                # array IS one tool round — every step it yields shares one
                # `group` id, so the frontend nests them under one accordion
                # (matching the live mapper's group stamping).
                group_seq += 1
                # Intermediate step; its content is a placeholder, not an answer.
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    # Accumulate this loop's written/edited files (plus
                    # "plan.md" for todo writes) for the turn's changed-files
                    # summary.
                    wpath = _changed_entry(tc, ws, plan_paths)
                    if wpath and wpath not in turn_changed_seen:
                        turn_changed_seen.add(wpath)
                        turn_changed.append(wpath)
                    # A todo_write is plan machinery: append a plan SNAPSHOT
                    # at this point in the timeline (never a step card, and
                    # never refreshed in place) — mirrors the live stream, where
                    # every plan update adds a new frozen block. The composer's
                    # pinned panel is the live/aggregated view.
                    entries = _plan_entries(tc, results)
                    if entries is not None:
                        parts.append(_plan_part(entries))
                        continue
                    # Any other tool call becomes its own linear step part
                    # (``durations`` supplies the persisted tool elapsed time).
                    # Consume the matching restricted-mode ask FIRST (before the
                    # step-None check): a DENIED call drops its step, but the
                    # rejected auth card must still render at the call's original
                    # position (not flushed to the turn end). Pair by call_id
                    # (exact even for parallel identical calls), falling back to
                    # (tool, args) FIFO for old logs / empty ids.
                    tool_name = str(
                        tc.get("tool_name")
                        or (tc.get("function") or {}).get("name") or "")
                    perm = _take_matching_perm(tool_name,
                                               tc.get("arguments"),
                                               call_id=str(tc.get("id") or ""))
                    if perm is not None:
                        pstep = _permission_step(perm)
                        if pstep is not None:
                            pstep.meta["group"] = group_seq
                            parts.append(
                                SessionPart(kind="step", step=pstep))
                    step = _history_step(tc, errored, results, durations,
                                         project)
                    if step is not None:
                        step.meta["group"] = group_seq
                        parts.append(SessionPart(kind="step", step=step))
            else:
                content = row.get("content")
                # A synthetic filler content (the interrupt seal's neutral
                # placeholder) only exists to close the turn for the model; the
                # UI shows the interrupted badge (below) instead of the literal.
                if content and not is_placeholder_content(row):
                    append_text(str(content))
            if row.get("interrupted"):
                # Faithful-interrupt marker: the row carries its partial content
                # verbatim (rendered above); the badge marks the exact stop
                # point so replay matches what the live view showed.
                parts.append(SessionPart(kind="interrupted"))
        # system / plain tool rows are not rendered (tool errors handled above).

    flush()
    return messages


def delete_session(sid: str) -> None:
    from app.backends.ms_agent.runtime import registry

    found = find_session(sid)
    if not found:
        raise NotFound("session not found")
    _project, _session, sm = found
    registry.discard(sid)  # stop any live agent before removing its log
    sm.delete(sid)
    sidecar.drop("sessions", sid)


def update_session(sid: str, body: SessionUpdate) -> Session:
    """Rename a session (update its title)."""
    found = find_session(sid)
    if not found:
        raise NotFound("session not found")
    project, session, _sm = found
    if body.title is not None:
        sm_for(project).update(sid, name=body.title)
        session = sm_for(project).get(sid)
    return session_to_schema(session)


def _artifact_id(path: str) -> str:
    return "art_" + hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]


def _ws_root(project) -> str | None:
    """The project workspace root — the working directory file-tool relative
    paths resolve against (``project.path``; mounted dir for mounted projects,
    the internal project dir otherwise)."""
    try:
        p = str(getattr(project, "path", "") or "")
        return os.path.normpath(p) if p else None
    except Exception:
        return None


def _resolve_tool_path(workspace: str, path: str) -> str:
    """Absolute, normalized location of a file-tool path argument (relative
    paths join the workspace root — the tools' working directory)."""
    p = path if os.path.isabs(path) else os.path.join(workspace, path)
    return os.path.normpath(p)


def _workspace_rel(workspace: str, abspath: str) -> str | None:
    """``abspath`` as a workspace-relative path, or None when it lies OUTSIDE
    the workspace (session dir, ``..`` escapes, absolute paths elsewhere) —
    such writes are session/system state, not workspace deliverables."""
    root = os.path.normpath(workspace)
    if not abspath.startswith(root + os.sep):
        return None
    return os.path.relpath(abspath, root)


_RENDERED_MD_RE = re.compile(r"^OK: rendered plan markdown to (.+)$")


def plan_paths_in_rows(rows: list[dict], workspace: str) -> set[str]:
    """Absolute locations of this session's PLAN files, as reported by the
    todo tool itself — no filename heuristics: a plan named ``xxx_plan.md``
    (or anything else) is recognized because the tool call said so, not
    because of how it is named. Sources:

    - ``todo_write`` results carry ``plan_path`` (the plan json, relative to
      the tool's output dir); its auto-rendered same-stem ``.md`` twin counts
      too.
    - ``todo_render_md`` results name the markdown file they produced (the
      model may point it anywhere, e.g. into the workspace under any name).
    - persisted ``loop_end`` markers carry the resolved ``plan_file``.

    Used to keep plan files out of the file ledgers (changed_files summary,
    session artifacts → the composer's file list)."""
    out: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        pf = row.get("plan_file")
        if row.get("_type") == "loop_end" and isinstance(pf, str) and pf:
            out.add(os.path.normpath(pf))
            continue
        if row.get("role") != "tool":
            continue
        content = str(row.get("content") or "").strip()
        m = _RENDERED_MD_RE.match(content)
        if m:
            out.add(_resolve_tool_path(workspace, m.group(1).strip()))
            continue
        if '"plan_path"' not in content:
            continue
        try:
            data = json.loads(content)
        except (ValueError, TypeError):
            continue
        pp = data.get("plan_path") if isinstance(data, dict) else None
        if isinstance(pp, str) and pp:
            ap = _resolve_tool_path(workspace, pp)
            out.add(ap)
            stem, ext = os.path.splitext(ap)
            if ext == ".json":
                out.add(stem + ".md")
    return out


def latest_rendered_plan_md(rows: list[dict], workspace: str) -> str | None:
    """Absolute path of the LAST markdown the todo tool rendered in ``rows``
    (a ``todo_render_md`` result), or None. The most recently created/updated
    plan artifact is the one the plan chip should point at."""
    latest: str | None = None
    for row in rows:
        if not isinstance(row, dict) or row.get("role") != "tool":
            continue
        m = _RENDERED_MD_RE.match(str(row.get("content") or "").strip())
        if m:
            latest = _resolve_tool_path(workspace, m.group(1).strip())
    return latest


def _written_path(tc: dict) -> str | None:
    """The workspace path a ``file_system---write_file/edit_file`` tool_call
    targets, or None if this call isn't a file write/edit. Shared by the
    artifact ledger and the per-loop changed-files summary."""
    from app.backends.ms_agent.chat import _PATH_KEYS, _as_dict

    if not isinstance(tc, dict):
        return None
    fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
    name = str(tc.get("tool_name") or fn.get("name") or "")
    base, _, leaf = name.partition("---")
    if base != "file_system" or leaf not in ("write_file", "edit_file"):
        return None
    args = _as_dict(tc.get("arguments", fn.get("arguments")))
    return next(
        (args[k]
         for k in _PATH_KEYS if isinstance(args.get(k), str) and args[k]),
        None,
    )


def _is_plan_write(tc: dict) -> bool:
    """True for a todo tool call that created/updated the session plan files
    (``todo_write`` rewrites them; ``todo_render_md`` renders the markdown),
    so the loop's changed-files summary carries the reserved ``plan.md``
    marker (the plan is session state, not a workspace file — its content is
    served by ``GET /sessions/{id}/plan``)."""
    if not isinstance(tc, dict):
        return False
    fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
    name = str(tc.get("tool_name") or fn.get("name") or "")
    return name in ("todo_list---todo_write", "todo_list---todo_render_md")


def _changed_entry(
    tc: dict,
    workspace: str | None = None,
    plan_paths: set[str] | None = None,
) -> str | None:
    """This tool_call's contribution to the changed-files summary: the
    workspace-relative path of a file write/edit, the reserved ``"plan.md"``
    marker for a plan write, else None. With a ``workspace`` root, file
    writes that resolve OUTSIDE it (e.g. the model copying its plan into the
    session dir via ``..`` or an absolute path) or onto a known plan file
    (``plan_paths``) are excluded — they are plan/session state, not
    workspace deliverables."""
    if _is_plan_write(tc):
        return "plan.md"
    path = _written_path(tc)
    if not path:
        return None
    if workspace is None:
        return path
    ap = _resolve_tool_path(workspace, path)
    if plan_paths and ap in plan_paths:
        return None
    return _workspace_rel(workspace, ap)


def changed_files_in_rows(
    rows: list[dict],
    workspace: str | None = None,
    plan_paths: set[str] | None = None,
) -> list[str]:
    """Files changed across the given assistant rows, in first-write order,
    deduped: workspace-relative paths written/edited plus the reserved
    ``plan.md`` marker when the todo plan was rewritten. With a ``workspace``
    root, out-of-workspace writes and plan files (``plan_paths``, derived
    from the rows when omitted) are filtered out. The per-loop equivalent of
    the session-wide artifact ledger — used to summarize a completed
    tool-call loop (frontend collapses the intermediate steps and shows this
    changed-files set)."""
    if workspace is not None and plan_paths is None:
        plan_paths = plan_paths_in_rows(rows, workspace)
    ordered: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row.get("role") != "assistant":
            continue
        for tc in row.get("tool_calls") or []:
            path = _changed_entry(tc, workspace, plan_paths)
            if path and path not in seen:
                seen.add(path)
                ordered.append(path)
    return ordered


def list_artifacts(sid: str) -> list[Artifact]:
    """Per-conversation artifact ledger: every workspace file the agent WROTE or
    EDITED during this session, in first-write order, deduped by path.

    Derived from the immutable, append-only SessionLog tool-call records (not a
    live directory scan), so it reflects what the conversation produced
    regardless of what the user later did to those files: a file the agent wrote
    but the user then deleted stays listed as ``deleted=True`` (the design's
    greyed "deleted" card), and a later user edit does not remove the entry.

    v1 only tracks the ``file_system`` write/edit tools, which carry an explicit
    path argument. Files created indirectly by ``code_executor``/shell are not
    captured here (no reliable path in the call); a workspace-snapshot diff over
    the SDK's ``.ms_agent/snapshots/`` repo is the planned follow-up.
    """
    found = find_session(sid)
    if not found:
        raise NotFound("session not found")
    project, session, sm = found
    try:
        rows = sm.get_session_log(session).get_all_messages()
    except Exception:
        rows = []

    # The ledger only lists WORKSPACE deliverables: writes resolving outside
    # the workspace (e.g. the model copying its plan into the session dir via
    # ``..`` or an absolute path) and the session's plan files (identified by
    # the todo tool's own reports — any configured filename) are excluded, so
    # the composer's file list stays plan-free and workspace-scoped. Entries
    # are normalized workspace-relative paths, first-write order, deduped.
    ws = _ws_root(project) or str(project.path)
    plan_paths = plan_paths_in_rows(rows, ws)
    # Belt and braces: the session's own plan files at the webui default
    # location, in case no todo result made it into the log.
    try:
        from app.backends.ms_agent.config import session_dir

        sdir = session_dir(project, session)
        plan_paths |= {
            os.path.normpath(os.path.join(sdir, n))
            for n in ("plan.json", "plan.md")
        }
    except Exception:
        pass

    ordered: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row.get("role") != "assistant":
            continue
        for tc in row.get("tool_calls") or []:
            rel = _changed_entry(tc, ws, plan_paths)
            if rel and rel != "plan.md" and rel not in seen:
                seen.add(rel)
                ordered.append(rel)

    out: list[Artifact] = []
    for path in ordered:
        abs_path = os.path.join(ws, path)
        try:
            st = os.stat(abs_path)
            size = int(st.st_size)
            updated = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
            deleted = False
        except OSError:
            # Written during the turn but gone now — keep it, marked deleted.
            size = 0
            updated = datetime.now(tz=timezone.utc)
            deleted = True
        out.append(
            Artifact(
                id=_artifact_id(path),
                session_id=sid,
                path=path,
                name=os.path.basename(path.rstrip("/")) or path,
                kind="file",
                size=size,
                updated_at=updated,
                deleted=deleted,
            ))
    return out
