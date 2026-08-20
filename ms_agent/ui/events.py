# Copyright (c) ModelScope Contributors. All rights reserved.
"""UI-agnostic structured event model for agent output.

This module is the **contract** every front-end (TUI, future WebUI backend,
ACP translator) consumes. The agent emits :class:`AgentEvent` instances to an
:class:`AgentEventSink`; each event is an immutable, trivially-serializable
dataclass whose ``to_dict()`` *is* the wire format (WebSocket / SSE payload).

Design rules (keep this module dependency-free — pure stdlib only):

* **Semantic, not pixels** — events ship meaning (``ToolCallStarted``), never
  rendered text. A renderer decides how to draw them.
* **Open/closed** — add a new event by adding a frozen dataclass; the
  ``emit(event)`` protocol never changes.
* **Single source of truth** — the ``EVENT_TYPE`` string is the discriminator
  a WebUI front-end mirrors; do not rename lightly.

The vocabulary maps 1:1 onto ACP ``session_update`` types (see
``ms_agent/acp/translator.py``) and covers the two gaps ACP leaves
(``UserMessage`` echo, command catalog), so the same stream can drive ACP,
a WebUI, and the TUI without a second protocol.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar, List, Optional, Protocol, runtime_checkable

# ── value objects ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UsageInfo:
    """Token accounting carried on turn completion (drives the status bar)."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0


@dataclass(frozen=True)
class PlanEntry:
    """One item of a plan/todo list (from the todo / split_task tools)."""
    content: str
    status: str = 'pending'  # pending | in_progress | completed


# ── event base ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentEvent:
    """Base class for all agent events. Immutable and serializable.

    ``EVENT_TYPE`` is a class-level discriminator (not a dataclass field), so
    it is excluded from ``asdict`` but injected by :meth:`to_dict`.
    """
    EVENT_TYPE: ClassVar[str] = 'agent_event'

    @property
    def type(self) -> str:
        return self.EVENT_TYPE

    def to_dict(self) -> dict:
        """Return the serializable wire form: ``{'type': ..., **fields}``."""
        return {'type': self.EVENT_TYPE, **asdict(self)}


# ── turn lifecycle ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TurnStarted(AgentEvent):
    """A user turn began (one user input → one or more assistant steps)."""
    EVENT_TYPE: ClassVar[str] = 'turn_started'
    turn_id: str = ''
    source: str = 'tui'  # cli | tui | webui


@dataclass(frozen=True)
class UserMessage(AgentEvent):
    """Echo of the user's submitted text (ACP's missing user_message_chunk)."""
    EVENT_TYPE: ClassVar[str] = 'user_message'
    turn_id: str = ''
    text: str = ''


@dataclass(frozen=True)
class TurnCompleted(AgentEvent):
    """The assistant finished responding to the current turn."""
    EVENT_TYPE: ClassVar[str] = 'turn_completed'
    turn_id: str = ''
    usage: Optional[UsageInfo] = None


# ── assistant output ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ContentDelta(AgentEvent):
    """An incremental chunk of assistant message content."""
    EVENT_TYPE: ClassVar[str] = 'content_delta'
    text: str = ''


@dataclass(frozen=True)
class ContentEnd(AgentEvent):
    """The assistant content stream for the current message finished.

    A renderer uses this to finalize a streaming bubble (e.g. re-render the
    accumulated text as Markdown).
    """
    EVENT_TYPE: ClassVar[str] = 'content_end'


@dataclass(frozen=True)
class ReasoningStarted(AgentEvent):
    """The model began emitting reasoning / thinking tokens."""
    EVENT_TYPE: ClassVar[str] = 'reasoning_started'


@dataclass(frozen=True)
class ReasoningDelta(AgentEvent):
    """An incremental chunk of reasoning / thinking content."""
    EVENT_TYPE: ClassVar[str] = 'reasoning_delta'
    text: str = ''


@dataclass(frozen=True)
class ReasoningEnded(AgentEvent):
    """The reasoning / thinking stream finished."""
    EVENT_TYPE: ClassVar[str] = 'reasoning_ended'


# ── tools ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolCallComposing(AgentEvent):
    """The model is still WRITING a tool call; nothing runs yet.

    Between the last ``content_delta`` and the first ``tool_call_started`` the
    model streams the call's arguments, and until this event existed that window
    produced no events at all. It is imperceptible for a small call and very
    visible for a large one: measured at ~67 s of blank UI for one round that
    wrote five long files, because every file's whole body travels inside the
    arguments.

    The tool NAME arrives before its arguments do, so this can say what is being
    prepared. ``arguments_len`` is the bytes accumulated so far — enough to show
    progress, and deliberately not the payload itself, which is often huge and
    is delivered in full by ``tool_call_started`` anyway.
    """
    EVENT_TYPE: ClassVar[str] = 'tool_call_composing'
    index: int = 0
    name: str = ''
    arguments_len: int = 0


@dataclass(frozen=True)
class ToolCallStarted(AgentEvent):
    """A tool call is about to execute."""
    EVENT_TYPE: ClassVar[str] = 'tool_call_started'
    call_id: str = ''
    name: str = ''
    arguments: Any = None  # dict or raw JSON string


@dataclass(frozen=True)
class ToolCallCompleted(AgentEvent):
    """A tool call finished (successfully or with an error)."""
    EVENT_TYPE: ClassVar[str] = 'tool_call_completed'
    call_id: str = ''
    name: str = ''
    result: str = ''
    error: Optional[str] = None
    duration_s: Optional[float] = None


# ── plan / todo ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlanUpdated(AgentEvent):
    """The agent's plan / todo list changed."""
    EVENT_TYPE: ClassVar[str] = 'plan_updated'
    entries: List[PlanEntry] = field(default_factory=list)


# ── permission (human-in-the-loop) ────────────────────────────────────────


@dataclass(frozen=True)
class PermissionRequested(AgentEvent):
    """A tool needs user authorization (mirrors WebPermissionHandler emit)."""
    EVENT_TYPE: ClassVar[str] = 'permission_requested'
    request_id: str = ''
    tool_name: str = ''
    tool_args: Any = None
    context: str = ''
    options: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PermissionResolved(AgentEvent):
    """A pending permission request was answered."""
    EVENT_TYPE: ClassVar[str] = 'permission_resolved'
    request_id: str = ''
    action: str = ''  # e.g. allow_once | deny | allow_always


# ── context / system notices ──────────────────────────────────────────────


@dataclass(frozen=True)
class ContextCompacted(AgentEvent):
    """Non-destructive context compaction ran (long-conversation upkeep)."""
    EVENT_TYPE: ClassVar[str] = 'context_compacted'
    before_tokens: int = 0
    after_tokens: int = 0


@dataclass(frozen=True)
class Notice(AgentEvent):
    """A user-facing informational notice."""
    EVENT_TYPE: ClassVar[str] = 'notice'
    level: str = 'info'  # info | success | warning
    text: str = ''


@dataclass(frozen=True)
class ErrorRaised(AgentEvent):
    """An error surfaced during the run."""
    EVENT_TYPE: ClassVar[str] = 'error'
    message: str = ''
    recoverable: bool = True


# ── sink protocol + reference implementations ─────────────────────────────


@runtime_checkable
class AgentEventSink(Protocol):
    """The seam the agent emits to. A front-end implements ``emit``.

    Implementations must be cheap and non-blocking — ``emit`` is called on the
    hot path of token streaming. Rendering/formatting is the sink's business.
    """

    def emit(self, event: AgentEvent) -> None:
        ...


class RecordingSink:
    """Collects every emitted event. Used by tests and the ``--emit-events``
    debug dump; also handy as a base for buffering front-ends."""

    def __init__(self) -> None:
        self.events: List[AgentEvent] = []

    def emit(self, event: AgentEvent) -> None:
        self.events.append(event)

    def types(self) -> List[str]:
        return [e.type for e in self.events]

    def of_type(self, event_type: str) -> List[AgentEvent]:
        return [e for e in self.events if e.type == event_type]

    def text(self) -> str:
        """Concatenated assistant content — a quick assertion helper."""
        return ''.join(
            e.text for e in self.events if isinstance(e, ContentDelta))


class TeeEventSink:
    """Fans an event out to several sinks (e.g. render + record to disk)."""

    def __init__(self, *sinks: AgentEventSink) -> None:
        self._sinks = [s for s in sinks if s is not None]

    def emit(self, event: AgentEvent) -> None:
        for sink in self._sinks:
            sink.emit(event)


class JsonlEventSink:
    """Writes each event as one JSON line — a dump of the exact wire payloads a
    WebUI backend would forward. Use it to inspect and validate that the event
    contract carries everything a front-end needs.
    """

    def __init__(self, path) -> None:
        import json
        self._json = json
        self._own = isinstance(path, str)
        self._f = open(path, 'a', encoding='utf-8') if self._own else path

    def emit(self, event: AgentEvent) -> None:
        self._f.write(
            self._json.dumps(event.to_dict(), ensure_ascii=False) + '\n')
        self._f.flush()

    def close(self) -> None:
        if self._own:
            try:
                self._f.close()
            except Exception:
                pass
