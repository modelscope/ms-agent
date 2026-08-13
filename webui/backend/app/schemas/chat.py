from typing import Literal

from pydantic import BaseModel, Field


class ChatFile(BaseModel):
    """A file the user attached to a turn. Uploaded to the project workspace
    under ``user_files/`` before the chat request is sent, so ``path`` is the
    workspace-relative location the agent reads with its file tools; ``url`` is
    the raw HTTP link used only by the frontend to preview the file."""

    name: str
    path: str  # workspace-relative, e.g. "user_files/report.pdf"
    url: str | None = None  # raw byte URL (frontend preview only)
    size: int | None = None
    # 'file' | 'image' | 'audio' | 'video' — drives the user-bubble card render.
    type: str | None = None


class ContentSegment(BaseModel):
    """One segment of a configuration-style message content array.

    - ``{"type": "text", "text": "..."}`` — plain typed text;
    - ``{"type": "skill", "id": "writer"}`` — a skill invocation picked in the
      composer. The backend expands the first skill via the SDK bridge; the
      same shape is echoed back by session history so the frontend can
      re-render the skill pill.
    """

    type: Literal["text", "skill"]
    text: str = ""  # type == "text"
    id: str = ""  # type == "skill"
    name: str = ""  # type == "skill": display name the user saw (e.g. slug)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    # Configuration-style content: a plain string, or an ordered segment array
    # (text + inline skill invocations — no separate skills field needed).
    content: str | list[ContentSegment] = ""
    files: list[ChatFile] = Field(default_factory=list)
    # Deprecated: legacy structured skill ids. Prefer inline
    # ``{"type": "skill"}`` segments in ``content``.
    skills: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    session_id: str | None = None
    project_id: str | None = None
    # The CURRENT turn's user message. Conversation context is NOT taken from
    # the request — the ms-agent SessionLog on disk is the source of truth.
    message: ChatMessage | None = None


class ChatChunk(BaseModel):
    """One streamed SSE frame; `type` routes frontend rendering. Mirrors
    frontend/app/lib/agentProvider.ts::AgentChunk (task/step view-model).

    - text:    markdown token appended to the assistant body
    - thought: one reasoning block (meta.duration → the "thinking Ns" header)
    - task:    declares/updates a todo task (meta: id, label, status)
    - step:    a step card nested under a task (meta: kind, task_id?, status?)
    - session: emitted once at turn start when the session exists (meta:
               session_id, project_id) so the client can refresh its lists
               immediately, before the turn (and title) complete
    - turn:    server-authoritative age of the RUNNING turn (meta: elapsed_ms).
               Sent first on every stream (including a re-attach, whose client
               has no idea when the turn actually started) and re-sent
               periodically, so the "processing Ns" counter survives a refresh
               and can't drift from the server clock.
    - error:   a turn/API error (meta: message, recoverable); display-only
    - done:    stream terminator (meta: session_id, project_id, title?, category?)
    """

    type: Literal[
        "text", "thought", "task", "step", "session", "turn", "error", "done"
    ]
    content: str = ""
    meta: dict = Field(default_factory=dict)
