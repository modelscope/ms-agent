from datetime import datetime

from pydantic import BaseModel, Field


class Session(BaseModel):
    id: str
    title: str
    project_id: str | None = None
    updated_at: datetime
    preview: str = ""
    # True while this session has a turn in flight (live or continuing in the
    # background after its viewer navigated away) — drives the sidebar spinner.
    running: bool = False
    # Agent-assigned topic category (see ms_agent/titler.CATEGORIES); "" when the
    # session hasn't been classified yet. Drives the recent-list topic icon.
    category: str = ""


class SessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    project_id: str | None = None
    preview: str = ""


class SessionUpdate(BaseModel):
    title: str | None = None


class SessionStep(BaseModel):
    """A reconstructed step card (mirrors agentProvider.ts::AgentStep)."""

    kind: str
    meta: dict = Field(default_factory=dict)


class SessionTask(BaseModel):
    """A reconstructed plan (todo) item — label + status. Execution steps are no
    longer nested here; they are their own ``step`` parts (agentProvider.ts)."""

    id: str
    label: str
    status: str = "done"


class SessionPlan(BaseModel):
    """The session's live plan file plus whether it belongs to the CURRENT
    running turn. ``active`` is the server-side truth for "a task is actually
    being worked on right now": the turn is in flight AND plan.json was
    (re)written during it — a stale in_progress row from an earlier turn stays
    inactive, and a rejoining client (reload or tab switch-back) gets the same
    answer without having to observe the stream first."""

    tasks: list[SessionTask] = []
    active: bool = False


class SessionPart(BaseModel):
    """One ordered block of a reconstructed assistant turn (mirrors
    agentProvider.ts::AgentPart). ``kind`` routes the fields used:

    - text:    ``text`` holds a markdown answer block
    - thought: ``text`` holds a persisted reasoning block; ``duration`` is its
               elapsed seconds (persisted, so replay shows "thought Ns")
    - tasks:   ``tasks`` holds the plan items (labels + status) as plain text
    - step:    ``step`` holds one tool-call card, rendered inline in stream
               order (a tool step carries ``meta.duration_ms``; an authorization
               step carries ``meta.state`` = approved|rejected for replay)
    - error:   ``text`` holds an API/turn error message; ``recoverable`` says
               whether it re-entered model context (turn/API errors do not)

    A failed tool step carries ``status="error"`` (+ ``error``) in its meta.
    """

    kind: str
    text: str = ""
    duration: int | None = None
    tasks: list[SessionTask] = Field(default_factory=list)
    step: SessionStep | None = None
    recoverable: bool = True


class SessionFile(BaseModel):
    """A file the user attached to a turn, reconstructed on history replay from
    the persisted paths. ``exists`` is False when the workspace file has since
    been deleted, so the frontend can show a generic card + "deleted" note."""

    name: str
    path: str  # workspace-relative, e.g. "user_files/report.pdf"
    url: str | None = None  # raw byte URL (frontend preview only)
    type: str | None = None  # 'file' | 'image' | 'audio' | 'video'
    size: int | None = None  # bytes (None when the file no longer exists)
    exists: bool = True


class SessionMessage(BaseModel):
    role: str
    content: str
    # Ordered turn view-model rebuilt from the session log so history echoes the
    # same interleaving of answer text and the task/step timeline as a live turn.
    # ``content`` stays populated (joined text) for plain/fallback consumers.
    parts: list[SessionPart] = Field(default_factory=list)
    # Files the user attached to this turn (user messages only), reconstructed
    # from the persisted ``[Attached files]`` block so replay shows file cards.
    files: list[SessionFile] = Field(default_factory=list)
    # Workspace paths the agent wrote/edited during THIS turn's tool-call loop
    # (assistant messages only), so the frontend can collapse the intermediate
    # steps into a "done" summary listing what changed — the history-replay
    # counterpart of the live ``done`` frame's ``changed_files`` meta.
    changed_files: list[str] = Field(default_factory=list)
    # Wall-clock duration of the turn's tool-call loop, from the persisted
    # ``loop_end`` marker (not derivable from message rows). None for turns
    # predating the marker; the frontend then omits the "done · Ns" timing.
    duration_ms: int | None = None
    # Absolute path of the session plan markdown when THIS turn rewrote the
    # todo list (loop_end marker's ``plan_file``; pairs with the "plan.md"
    # entry in ``changed_files``). The plan lives in the SESSION dir, not the
    # workspace — render its chip via the plan components with content from
    # ``GET /sessions/{id}/plan``, never via a workspace-exists check.
    plan_file: str | None = None
    # Configuration-style content echo (user messages only): the same segment
    # array shape the composer sends (``[{type: text|skill, ...}]``), rebuilt
    # from the skill-invocation marker so the frontend re-renders skill pills.
    segments: list[dict] = Field(default_factory=list)


class Artifact(BaseModel):
    id: str
    session_id: str
    path: str
    # Basename for display; ``kind`` stays "file" (the frontend derives an icon
    # from the extension/name).
    name: str = ""
    kind: str = "file"
    size: int = 0
    updated_at: datetime
    # True when the agent wrote/edited this file during the session but it no
    # longer exists on disk (user deleted it, or a later step removed it). The
    # ledger keeps the entry — history is not erased by later user actions — and
    # the frontend renders it greyed ("已删除").
    deleted: bool = False
    preview: str | None = None
