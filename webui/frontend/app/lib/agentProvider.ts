import {
  AbstractChatProvider,
  type TransformMessage,
  type XRequestOptions,
} from "@ant-design/x-sdk";
import { dispatchWorkspaceChanged } from "~/lib/events";

/**
 * Wire shape of a single SSE frame from POST /api/chat.
 * Must stay in sync with backend/app/schemas/chat.py::ChatChunk.
 */
export interface AgentChunk {
  type: "text" | "thought" | "task" | "step" | "session" | "turn" | "error" | "done";
  content: string;
  meta?: Record<string, unknown>;
}

/**
 * A file the user attached to a turn. Uploaded to the project workspace under
 * `user_files/` before the request is sent (see Composer), so `path` is the
 * workspace-relative location the agent reads; `url` is the raw byte link the
 * frontend uses to preview it. Mirrors backend ChatFile.
 */
export interface ChatFileRef {
  name: string;
  path: string;
  url?: string;
  size?: number;
  type?: "file" | "image" | "audio" | "video";
  // False when reconstructed from history and the workspace file has since been
  // deleted — the bubble then shows a generic card + "deleted" note. Live
  // uploads leave this undefined (treated as present).
  exists?: boolean;
}

/** Request body sent to the backend. */
/** One segment of a configuration-style message content array. Skills are
 * inline segments (no separate field); the backend parses the array and the
 * session history echoes the same shape back for re-rendering. */
export type MessageSegment =
  | { type: "text"; text: string }
  | { type: "skill"; id: string; name?: string };

export interface AgentInput {
  session_id?: string | null;
  project_id?: string | null;
  /** The CURRENT turn's user message. Conversation context is NOT sent — the
   * backend's ms-agent SessionLog (on disk) is the source of truth. */
  message: {
    role: "user" | "assistant" | "system";
    /** Plain text, or a configuration-style segment array (text + inline
     * skill invocations picked in the composer). */
    content: string | MessageSegment[];
    files?: ChatFileRef[];
  };
}

/**
 * XRequest's default SSE parser yields `{ event, data }` per frame, where
 * `data` is the raw string value of the SSE `data:` field. It must be
 * JSON-parsed to recover one `AgentChunk` (see `transformMessage`).
 */
export type AgentOutput = { event?: string; data?: string | AgentChunk };

/** Kind of a step card rendered inline in stream order. `tasks` is not a tool
 * step: it's the todo plan, reusing the step→right-rail plumbing so its card
 * opens the plan detail in the same squeezable rail. */
export type StepKind =
  | "terminal"
  | "tool_call"
  | "skill_load"
  | "skill_list"
  | "skill_manage"
  | "file_read"
  | "file_write"
  | "file_edit"
  | "search"
  | "memory"
  | "browser"
  | "artifact"
  | "authorization"
  | "tasks";

/** A single tool-call step card, rendered inline in stream order. */
export interface AgentStep {
  kind: StepKind;
  meta: Record<string, unknown>;
}

export type TaskStatus = "done" | "running" | "pending" | "waiting";

/** One plan (todo) item — plain label + status. Execution steps are no longer
 * nested here; they render as their own linear `step` parts. */
export interface AgentTask {
  id: string;
  label: string;
  status: TaskStatus;
}

/**
 * One ordered block of a rendered assistant message. Blocks appear in true
 * stream order: consecutive text deltas grow one text block, a thought or task
 * arriving in between closes the current text block so following text starts a
 * new one. This preserves interleaving that a flat content string would lose.
 */
export type AgentPart =
  | { kind: "text"; text: string }
  // `startedAt` (epoch ms) is stamped when a live thought block opens so the UI
  // can tick a live "thinking Ns" counter until `done`; `duration` is the final
  // elapsed seconds (from the closing frame, or persisted on replay).
  | { kind: "thought"; text: string; startedAt?: number; duration?: number; done?: boolean }
  | { kind: "tasks"; tasks: AgentTask[] }
  | { kind: "step"; step: AgentStep }
  // A turn/API failure surfaced as its own alert card (not body text), so it
  // reads as a system-level failure. `recoverable` mirrors whether the error
  // re-entered the model context (turn/API errors: false).
  | { kind: "error"; text: string; recoverable?: boolean }
  // Marks the exact point where the turn was interrupted (Stop button).
  // Rendered as a muted badge; the partial content before it is real
  // streamed/persisted content, never fabricated text.
  | { kind: "interrupted" };

/** Rich assistant message; user messages reuse the same shape with content only. */
export interface AgentMessage {
  role: "user" | "assistant" | "system";
  /**
   * Canonical plain text: the user's message, or (for assistant) the joined
   * text blocks. Kept for request serialization and as a render fallback when
   * `parts` is absent. Rich assistant rendering uses `parts`.
   */
  content: string;
  /** Ordered rich content blocks (assistant messages). */
  parts?: AgentPart[];
  /** Epoch ms of this turn's start. Server-authoritative: derived from the
   * `turn` frame's `elapsed_ms` (sent first on every stream, so a reload /
   * re-attach continues the counter instead of restarting it, and re-sent
   * periodically to correct drift). Falls back to the first frame's arrival
   * time if a stream predates the frame. */
  turnStartedAt?: number;
  /** Wall-clock duration of the turn's tool-call loop, in ms: from the live
   * `done` frame's `duration_ms`, or the persisted `loop_end` marker on
   * replay. Undefined for turns predating the marker (timing then omitted). */
  loopDurationMs?: number;
  /** Workspace paths the agent wrote/edited during THIS turn's loop — the
   * turn's deliverables, rendered as file cards after the summary. From the
   * live `done` frame's `changed_files` / SessionMessage.changed_files. */
  changedFiles?: string[];
  /** Absolute path of the session plan markdown when THIS turn rewrote the
   * todo list (pairs with the reserved "plan.md" changed_files entry). The
   * plan lives in the SESSION dir, not the workspace — it renders as a plan
   * chip whose content comes from `GET /sessions/{id}/plan`. */
  planFile?: string;
  /** Files the user attached to this turn (user messages only). */
  files?: ChatFileRef[];
  /** Configuration-style content echo (user messages only): the segment array
   * as sent/replayed, so the bubble re-renders skill pills. */
  segments?: MessageSegment[];
}

export class AgentChatProvider extends AbstractChatProvider<
  AgentMessage,
  AgentInput,
  AgentOutput
> {
  /**
   * Called with the backend session id carried by the terminal `done` frame.
   * Lets a new-chat turn (sent with a null session_id) learn the id the backend
   * created, so subsequent turns reuse the same session (no splitting) and the
   * Stop button can target it via POST /api/chat/interrupt. `projectId` (also in
   * the frame) lets the caller route to the created session's URL.
   */
  onSessionId?: (sessionId: string, projectId?: string) => void

  /**
   * Called on the early `session` frame emitted at turn start, the moment the
   * backend has created the session (before the turn or title complete). Lets
   * the caller refresh its conversation lists immediately so the new session
   * appears right away with its cheap first-line title.
   */
  onSessionStart?: (sessionId: string, projectId?: string) => void

  /**
   * Called when the terminal `done` frame carries an agent-generated title (and
   * topic category) for a first message. Lets the chat panel revalidate the
   * route loaders so the sidebar + recent-conversations lists refresh with the
   * summarized title and category icon.
   */
  onSessionMeta?: (meta: {
    sessionId: string
    title?: string
    category?: string
  }) => void

  transformParams(
    requestParams: Partial<AgentInput>,
    options: XRequestOptions<AgentInput, AgentOutput, AgentMessage>,
  ): AgentInput {
    return {
      ...(options?.params || {}),
      session_id: requestParams.session_id ?? null,
      project_id: requestParams.project_id ?? null,
      message: requestParams.message ?? { role: "user", content: "" },
    };
  }

  transformLocalMessage(requestParams: Partial<AgentInput>): AgentMessage {
    // useXChat appends this as the user-side bubble, carrying attached files
    // so the bubble can render the uploaded-file cards. A configuration-style
    // content array keeps its segments for rich echo (skill pills + text).
    const msg = requestParams.message;
    const content = msg?.content ?? "";
    if (Array.isArray(content)) {
      const text = content
        .filter((s): s is { type: "text"; text: string } => s.type === "text")
        .map((s) => s.text)
        .join(" ")
        .trim();
      return { role: "user", content: text, files: msg?.files, segments: content };
    }
    return {
      role: "user",
      content,
      files: msg?.files,
    };
  }

  transformMessage(
    info: TransformMessage<AgentMessage, AgentOutput>,
  ): AgentMessage {
    const { originMessage, chunk } = info;
    const base: AgentMessage = originMessage
      ? { ...originMessage }
      : { role: "assistant", content: "" };

    const c = parseChunk(chunk?.data);
    if (!c) return base;

    const meta = c.meta ?? {};

    if (c.type === "session") {
      // Early frame: the session now exists on the server. Surface its id so
      // the caller can refresh its lists immediately. No visible content.
      const sid = typeof meta.session_id === "string" ? meta.session_id : "";
      const projectId =
        typeof meta.project_id === "string" ? meta.project_id : undefined;
      if (sid) this.onSessionStart?.(sid, projectId);
      return base;
    }
    if (c.type === "done") {
      const sid = typeof meta.session_id === "string" ? meta.session_id : "";
      const projectId =
        typeof meta.project_id === "string" ? meta.project_id : undefined;
      if (sid) this.onSessionId?.(sid, projectId);
      const title = typeof meta.title === "string" ? meta.title : undefined;
      if (title) {
        const category =
          typeof meta.category === "string" ? meta.category : undefined;
        this.onSessionMeta?.({ sessionId: sid, title, category });
      }
      // The loop boundary (SDK loop_end): its wall-clock duration is what the
      // turn header shows once processing is done; changed_files are the
      // turn's deliverables (file cards after the summary).
      const durationMs =
        typeof meta.duration_ms === "number" ? meta.duration_ms : undefined;
      const changed = Array.isArray(meta.changed_files)
        ? (meta.changed_files as unknown[]).filter(
            (p): p is string => typeof p === "string" && !!p,
          )
        : undefined;
      const planFile =
        typeof meta.plan_file === "string" && meta.plan_file
          ? meta.plan_file
          : undefined;
      let out = base;
      if (durationMs != null) out = { ...out, loopDurationMs: durationMs };
      if (changed?.length) out = { ...out, changedFiles: changed };
      if (planFile) out = { ...out, planFile };
      return out;
    }
    // Content-bearing frames fold in via the shared reducer (also used by the
    // attach reader, so live turns and rejoined turns render identically).
    return applyChunk(base, c);
  }
}

/**
 * Fold one streamed AgentChunk into an assistant message (immutably). Shared
 * by the useXChat provider (live turns) and the attach reader (re-joining a
 * background turn), so both render identically. `done` is a no-op here —
 * terminal handling is the caller's business.
 */
export function applyChunk(base: AgentMessage, c: AgentChunk): AgentMessage {
  const parts: AgentPart[] = base.parts ? [...base.parts] : [];
  const meta = c.meta ?? {};
  // Stamp the turn's wall-clock origin on its first frame so the header can
  // tick a live "processing Ns" counter (the final number comes from the
  // server's loop_end duration).
  if (base.turnStartedAt == null) base = { ...base, turnStartedAt: Date.now() };

  switch (c.type) {
    case "turn": {
      // Server-reported age of the running turn: re-base the local counter so
      // it survives a reload (re-attach) and can't drift from the server.
      const elapsed = meta.elapsed_ms;
      return typeof elapsed === "number"
        ? { ...base, turnStartedAt: Date.now() - elapsed }
        : base;
    }
    case "text":
      appendTextPart(parts, c.content);
      // Keep `content` in sync for serialization / fallback rendering.
      return { ...base, content: (base.content || "") + c.content, parts };
    case "thought":
      appendThoughtPart(parts, c.content, meta);
      return { ...base, parts };
    case "task":
      appendTaskSnapshot(parts, meta);
      return { ...base, parts };
    case "step":
      appendStepPart(parts, meta);
      return { ...base, parts };
    case "error": {
      // Its own alert card (ErrorCard) rather than body text — a turn/API
      // failure is not part of the reply. `content` still gets the message so
      // the plain-text fallback (and copy) keep working.
      const msg = String(meta.message ?? "");
      parts.push({
        kind: "error",
        text: msg,
        recoverable: Boolean(meta.recoverable ?? false),
      });
      return { ...base, content: (base.content || "") + `\n${msg}`, parts };
    }
    default:
      return base;
  }
}

/** Append streamed text to the open text block, or start a new one. */
function appendTextPart(parts: AgentPart[], text: string): void {
  const last = parts[parts.length - 1];
  if (last && last.kind === "text") {
    parts[parts.length - 1] = { kind: "text", text: last.text + text };
  } else {
    parts.push({ kind: "text", text });
  }
}

/**
 * Append streamed reasoning to the open thought block, or start a new one. A
 * chunk carrying `meta.duration` finalizes the block (sets duration + done), so
 * a later thought (after an intervening block) starts fresh.
 */
function appendThoughtPart(
  parts: AgentPart[],
  text: string,
  meta: Record<string, unknown>,
): void {
  const duration = typeof meta.duration === "number" ? meta.duration : undefined;
  const last = parts[parts.length - 1];
  if (last && last.kind === "thought" && !last.done) {
    parts[parts.length - 1] = {
      kind: "thought",
      text: last.text + text,
      startedAt: last.startedAt,
      duration: duration ?? last.duration,
      done: duration != null ? true : last.done,
    };
  } else {
    // A new live thought block: stamp its start so the UI can tick a counter.
    parts.push({
      kind: "thought",
      text,
      startedAt: Date.now(),
      duration,
      done: duration != null,
    });
  }
}

/** Append a plan SNAPSHOT block. The backend re-sends the whole plan (one
 * `task` chunk per row) on every update, so a burst of chunks = one snapshot.
 * Each update appends a NEW block at its position in the stream, giving the
 * conversation a frozen timeline of plan states (the composer's pinned panel
 * is the live one). A repeated row id means the next full re-send started →
 * begin a fresh snapshot. */
function appendTaskSnapshot(
  parts: AgentPart[],
  meta: Record<string, unknown>,
): void {
  const id = String(meta.id ?? "");
  const last = parts[parts.length - 1];
  if (last?.kind === "tasks" && !last.tasks.some((t) => t.id === id)) {
    // Same burst: keep filling the snapshot being built at the tail.
    parts[parts.length - 1] = {
      kind: "tasks",
      tasks: upsertTask(last.tasks, meta),
    };
    return;
  }
  parts.push({ kind: "tasks", tasks: upsertTask(undefined, meta) });
}

/** Append a tool-call step as its own ordered block, rendered inline in stream
 * order (no task nesting).
 *
 * When the incoming step is the RESULT of a tool that previously asked for
 * authorization (a preceding `authorization` step part for the same tool), the
 * auth card is updated in place instead of appending a duplicate card:
 * - approved/pending → the auth part is REPLACED by the tool step (the box
 *   "continues" with arguments + result — same as what history replays);
 * - rejected + errored result → the incoming step is DROPPED (the rejected
 *   auth card already tells the story). */
function appendStepPart(parts: AgentPart[], meta: Record<string, unknown>): void {
  const isRunning = meta.status === "running";
  // Paths this step just wrote, handed to the workspace listeners so a freshly
  // written file is merged into the live file set immediately. Without them the
  // card renders against the PREVIOUS set, which already covers the directory —
  // and "covered directory, path absent" reads as deleted, so the card flashed
  // "this file was deleted" until the refetch landed.
  const writtenPaths = (): string[] => {
    const multi = Array.isArray(meta.paths)
      ? (meta.paths as unknown[]).map(String).filter(Boolean)
      : [];
    if (multi.length > 0) return multi;
    const single = String(meta.path ?? "");
    return single ? [single] : [];
  };
  const notifyWorkspace = () => dispatchWorkspaceChanged(writtenPaths());
  // Live-card merge by call_id: a tool's "running" card (emitted on
  // tool_call_started) is replaced IN PLACE by its completed / interrupted step
  // (same call_id) — so a slow tool shows an immediate "executing" card that
  // becomes the result, never a duplicate. Also lets a completed tool supersede
  // its own authorization card when they share a call_id.
  const callId = String(meta.call_id ?? "");
  if (callId) {
    for (let i = parts.length - 1; i >= 0; i--) {
      const p = parts[i];
      if (p.kind === "step" && String(p.step.meta.call_id ?? "") === callId) {
        // A rejected ask keeps its card; an errored result must not overwrite
        // the "rejected" story. Keyed on `state`, not on the card kind: a shell
        // ask renders as its own terminal card (backend _AUTH_INLINE_KINDS), so
        // the rejection can live on any step kind.
        if (p.step.meta.state === "rejected" && meta.status === "error") {
          return;
        }
        parts[i] = { kind: "step", step: { kind: meta.kind as StepKind, meta } };
        if (
          !isRunning &&
          (meta.kind === "file_write" || meta.kind === "file_edit")
        )
          notifyWorkspace();
        return;
      }
    }
  }
  // Fallback for buffers/history without call_id: continue an authorization card
  // by tool_name when the tool result arrives. `tool_name` is stamped only on
  // ask cards, so it identifies one whatever kind it renders as (a shell ask is
  // a terminal card).
  if (meta.kind !== "authorization") {
    const name = String(meta.tool ?? meta.name ?? "");
    for (let i = parts.length - 1; i >= 0; i--) {
      const p = parts[i];
      if (
        p.kind === "step" &&
        String(p.step.meta.tool_name ?? "") === name &&
        name !== ""
      ) {
        if (p.step.meta.state === "rejected" && meta.status === "error") {
          return; // rejection already shown by the auth card
        }
        parts[i] = { kind: "step", step: { kind: meta.kind as StepKind, meta } };
        if (meta.kind === "file_write" || meta.kind === "file_edit")
          notifyWorkspace();
        return;
      }
    }
  }
  parts.push({ kind: "step", step: { kind: meta.kind as StepKind, meta } });
  // Notify workspace when a file is actually WRITTEN (not while still running)
  // so the file list refreshes mid-turn (not waiting for the turn to finish).
  if (!isRunning && (meta.kind === "file_write" || meta.kind === "file_edit")) {
    notifyWorkspace();
  }
}

/**
 * Recover an `AgentChunk` from a raw SSE frame. `chunk.data` is the raw string
 * value of the `data:` field (per XRequest's default SSE parser), so it needs
 * JSON parsing; we also tolerate an already-parsed object defensively.
 */
export function parseChunk(data: string | AgentChunk | undefined): AgentChunk | null {
  if (data == null) return null;
  if (typeof data !== "string") return data;
  const s = data.trim();
  if (!s || s === "[DONE]") return null;
  try {
    return JSON.parse(s) as AgentChunk;
  } catch {
    return null;
  }
}

/** Insert or update a task (by id) immutably. */
function upsertTask(
  tasks: AgentTask[] | undefined,
  meta: Record<string, unknown>,
): AgentTask[] {
  const id = String(meta.id ?? "");
  const label = String(meta.label ?? "");
  const status = (meta.status as TaskStatus) ?? "running";
  const list = tasks ? [...tasks] : [];
  const idx = list.findIndex((t) => t.id === id);
  if (idx >= 0) {
    list[idx] = { ...list[idx], label: label || list[idx].label, status };
  } else {
    list.push({ id, label, status });
  }
  return list;
}

/**
 * Wire shape of one persisted message returned by GET /api/sessions/:id/messages
 * (backend/app/schemas/session.py::SessionMessage). A "thought" part replays a
 * persisted reasoning block (rendered as a finished thought — the log records
 * no elapsed time, so it carries no duration).
 */
export interface HistoryPart {
  kind: "text" | "thought" | "tasks" | "step" | "error" | "interrupted";
  text?: string;
  // kind="thought": persisted elapsed seconds, so replay shows "thought Ns".
  duration?: number;
  // kind="error": whether the error re-entered model context (turn/API: false).
  recoverable?: boolean;
  // kind="tasks": the plan items (labels + status), no nested steps.
  tasks?: {
    id: string;
    label: string;
    status: string;
  }[];
  // kind="step": a single tool-call step (meta.status="error" if it failed).
  step?: { kind: string; meta: Record<string, unknown> };
}

export interface HistoryMessage {
  role: "user" | "assistant" | "system";
  content: string;
  parts?: HistoryPart[];
  // Assistant turns only: wall-clock duration of the turn's tool-call loop
  // (persisted `loop_end` marker) — the "processing done · Ns" header timing.
  duration_ms?: number | null;
  // Assistant turns only: workspace paths written/edited during the turn's
  // loop — the deliverables shown as file cards after the summary.
  changed_files?: string[];
  // Assistant turns only: session plan markdown path when the turn rewrote
  // the todo list (persisted `loop_end` marker's plan_file).
  plan_file?: string | null;
  // User turns only: files attached to the message, reconstructed by the
  // backend from the persisted attachment block (with an `exists` flag).
  files?: ChatFileRef[];
  // User turns only: configuration-style content echo (skill pills + text),
  // same segment shape the composer sent (loose backend shape, narrowed in
  // historyToAgentMessages).
  segments?: { type: "text" | "skill"; text?: string; id?: string; name?: string }[];
}

/** Convert persisted history rows into the live AgentMessage view-model. */
export function historyToAgentMessages(
  rows: HistoryMessage[] | undefined,
): AgentMessage[] {
  if (!rows) return [];
  return rows.map((row) => {
    const msg: AgentMessage = { role: row.role, content: row.content };
    if (typeof row.duration_ms === "number")
      msg.loopDurationMs = row.duration_ms;
    if (row.changed_files && row.changed_files.length > 0)
      msg.changedFiles = row.changed_files;
    if (typeof row.plan_file === "string" && row.plan_file)
      msg.planFile = row.plan_file;
    if (row.files && row.files.length > 0) msg.files = row.files;
    if (row.segments && row.segments.length > 0)
      msg.segments = row.segments.map(
        (s): MessageSegment =>
          s.type === "skill"
            ? { type: "skill", id: s.id ?? "", name: s.name }
            : { type: "text", text: s.text ?? "" },
      );
    if (row.parts && row.parts.length > 0) {
      msg.parts = row.parts.map((part): AgentPart => {
        if (part.kind === "tasks") {
          return {
            kind: "tasks",
            tasks: (part.tasks ?? []).map((task) => ({
              id: task.id,
              label: task.label,
              status: task.status as TaskStatus,
            })),
          };
        }
        if (part.kind === "step") {
          return {
            kind: "step",
            step: {
              kind: (part.step?.kind ?? "tool_call") as StepKind,
              meta: part.step?.meta ?? {},
            },
          };
        }
        if (part.kind === "thought") {
          // Replayed reasoning: a closed block whose persisted elapsed time (if
          // any) drives the "thought Ns" header.
          return {
            kind: "thought",
            text: part.text ?? "",
            duration: part.duration,
            done: true
          };
        }
        if (part.kind === "interrupted") {
          // Faithful-interrupt badge: marks the exact stop point in replay,
          // matching what the live view showed when the turn was stopped.
          return { kind: "interrupted" };
        }
        if (part.kind === "error") {
          // Same alert card as the live path (never body text).
          return {
            kind: "error",
            text: part.text ?? "",
            recoverable: part.recoverable ?? false,
          };
        }
        return { kind: "text", text: part.text ?? "" };
      });
    }
    return msg;
  });
}
