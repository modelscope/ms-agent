import {
  AbstractChatProvider,
  type TransformMessage,
  type XRequestOptions,
} from "@ant-design/x-sdk";
import { ApiError, readFailure } from "~/lib/api";
import { dispatchImageDelivery } from "~/lib/imageDelivery";
import { dispatchWorkspaceChanged } from "~/lib/events";

/** Name carried by the error `assertChatStream` throws, so a caller can tell a
 * rejected response apart from an abort or a bare network failure. */
export const CHAT_STREAM_ERROR = "ChatStreamError";

/**
 * Guard every chat response: unless it IS the SSE stream we expect, reject it
 * with whatever explanation its body carries.
 *
 * Neither streaming path validates this on its own. XRequest routes purely on
 * content-type and never reads a failed body: a non-2xx becomes the opaque
 * `Fetch failed with status N`, while a rejection delivered as
 * `application/json` with a 2xx status is handed to `onUpdate` as if it were a
 * message — `transformMessage` then finds no `data` on it, returns the untouched
 * (empty) assistant message, and the turn silently produces nothing at all. The
 * hand-rolled /api/chat/attach reader is worse: it skips every line without a
 * `data:` prefix, so a rejection leaves its placeholder bubble stuck loading
 * forever.
 *
 * Both shapes occur for real — the ModelScope gateway answers a request whose
 * content trips its security inspection with `{ code, message }` instead of
 * proxying to us, and its HTTP status is not something we control.
 */
export async function assertChatStream(response: Response): Promise<Response> {
  const mime = (response.headers.get("content-type") || "")
    .split(";")[0]
    .trim();
  if (response.ok && mime === "text/event-stream") return response;
  // Not our stream, so the body is a (small) error report and reading it whole
  // costs nothing — this response is never handed back for streaming.
  let body: unknown;
  try {
    body = JSON.parse(await response.text());
  } catch {
    body = undefined;
  }
  const failure = readFailure(body);
  // Throw the same ApiError the REST client raises, so the failure reads
  // identically wherever it surfaces (via `describeFailure`): a bare status
  // when the body carried no message, the message when it did. `name` marks it
  // as a chat-stream rejection so callers can tell it from an abort.
  const err = new ApiError(
    failure?.message ?? "",
    response.status,
    failure?.code ?? response.status,
    response.statusText
  );
  err.name = CHAT_STREAM_ERROR;
  throw err;
}

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
  // Images only: what actually happened to this picture on the turn it was
  // attached to. Undefined for non-images, for live uploads before the turn
  // runs, and for turns recorded before this was tracked — all of which render
  // as no badge, never as a wrong one.
  delivery?: "delivered" | "degraded" | "unreadable";
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
  model_id?: string;
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
  | "tasks"
  // Transient: the model is still writing a tool call. Never persisted and
  // never replayed — it exists only to fill the streaming gap before
  // `tool_call_started`, and is removed the moment a real step arrives.
  | "tool_composing";

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
  // `startedAt` (epoch ms) is what the live "thinking Ns" counter counts from
  // until `done`; `duration` is the final elapsed seconds. `block` is the
  // SERVER's id for this reasoning block, so frames find it by id rather than
  // by position. `derived` marks a duration this client guessed — the server's
  // number always replaces it.
  | {
      kind: "thought"
      text: string
      startedAt?: number
      duration?: number
      done?: boolean
      block?: number
      derived?: boolean
    }
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
  /** Server history only: the trailing message of a turn that is still running
   * (its finished rounds are also being replayed on the live stream, so an
   * attached viewer renders one description of the turn, not two). */
  partial?: boolean;
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
      model_id: requestParams.model_id,
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
      // The turn is over: close any thought still marked live. A thought
      // normally closes on `reasoning_ended`, so this only bites when an error
      // ended the turn while reasoning was still streaming AND the `error` frame
      // didn't already run this cleanup (e.g. it was suppressed as a duplicate) —
      // last-resort stop for the "thinking Ns" counter.
      if (out.parts?.some((p) => p.kind === "thought" && !p.done)) {
        const parts = [...out.parts];
        finalizeOpenThoughts(parts);
        out = { ...out, parts };
      }
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
      // Answer text means reasoning is over. Normally `reasoning_ended` (a
      // duration-bearing thought frame) already closed the block, so this is a
      // no-op; it only bites when that frame never came.
      finalizeOpenThoughts(parts);
      // The model is talking again, so whatever call it was writing has been
      // delivered: the placeholder for it is stale (see sweepComposing).
      sweepComposing(parts);
      appendTextPart(parts, c.content);
      // Keep `content` in sync for serialization / fallback rendering.
      return { ...base, content: (base.content || "") + c.content, parts };
    case "thought":
      appendThoughtPart(parts, c.content, meta);
      return { ...base, parts };
    case "task":
      // A plan snapshot begins: reasoning is over, close any open thought.
      finalizeOpenThoughts(parts);
      // This snapshot IS the output of the todo call being composed — and the
      // todo tools are exactly the ones that emit no step of their own, so
      // without this sweep their placeholder has nothing to retire it.
      sweepComposing(parts);
      appendTaskSnapshot(parts, meta);
      return { ...base, parts };
    case "step":
      // A tool call begins: reasoning is over. This is the common gap — the
      // model often goes straight from reasoning to a tool call (which may then
      // sit awaiting authorization) with NO `reasoning_ended` in between, so
      // without this the "thinking Ns …" counter would keep ticking behind the
      // tool card. Freeze it here.
      //
      // An image-delivery report is exempt: it says what became of an attached
      // picture on THIS REQUEST and draws no card, and the SDK publishes it once
      // the response's first chunk has arrived — which for a thinking model is
      // normally mid-reasoning. Closing the block there cut one continuous
      // thought into two live (a first block holding the couple of words that
      // made it into chunk one, then the sentence that continued them), while
      // the finished turn — rebuilt from the message's single
      // `reasoning_content` — showed one block: the same reasoning changed shape
      // the moment the turn stopped running.
      if (meta.kind !== IMAGE_DELIVERY) finalizeOpenThoughts(parts);
      appendStepPart(parts, meta);
      return { ...base, parts };
    case "error": {
      // Its own alert card (ErrorCard) rather than body text — a turn/API
      // failure is not part of the reply. `content` still gets the message so
      // the plain-text fallback (and copy) keep working.
      const msg = String(meta.message ?? "");
      // An error ends the turn, so any reasoning still in flight is over.
      // Normally a thought closes the moment the backend maps `reasoning_ended`
      // (a duration-bearing frame), so a completed turn's blocks are already
      // done. The gap is an ERROR that terminates the turn WHILE reasoning is
      // still streaming (rate limit, insufficient balance, dropped connection):
      // `reasoning_ended` never arrives, and — unlike a manual Stop, which the
      // ChatPanel `stoppedLocally` path closes client-side — an error turn has no
      // such cleanup, so the block stays `done:false` and its "thinking Ns"
      // counter ticks forever. Force it closed here.
      finalizeOpenThoughts(parts);
      // A turn that died mid-call leaves a placeholder that would otherwise keep
      // pulsing under the error card, as if the call were still being written.
      sweepComposing(parts);
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

/** Force any still-open thought block closed (sets `done`, freezing its live
 * counter). Called on terminal events other than the normal duration-bearing
 * close frame — an errored/interrupted turn never emits that frame, and neither
 * does a turn where the model goes straight from reasoning to a tool call, so
 * the block would otherwise tick forever. Idempotent: already-done blocks
 * untouched.
 *
 * When no authoritative `duration` arrived we DERIVE one from `startedAt`, so
 * the header freezes at the elapsed value the live counter last showed. Without
 * this the UI, seeing `done` but no `duration`, blanks the time entirely (see
 * ThoughtsFlow: `shown = isDone ? duration : elapsed`). It is marked `derived`
 * because it only measures from when THIS client first saw the block; the
 * server's closing frame replaces it if one still arrives. */
export function finalizeOpenThoughts(parts: AgentPart[]): void {
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    if (part.kind === "thought" && !part.done) {
      const derived = part.duration == null && part.startedAt != null;
      const duration =
        part.duration ??
        (part.startedAt != null
          ? Math.max(0, Math.floor((Date.now() - part.startedAt) / 1000))
          : undefined);
      parts[i] = { ...part, done: true, duration, derived: derived || undefined };
    }
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

/** Count from the server's age for the block (`elapsed_ms`), but only take
 * corrections bigger than a second: every stamp arrives a little late, and
 * applying each one nudged the counter backwards across second boundaries
 * (67s → 66s under a refresh-every-2s stress run). The large corrections are
 * the ones that matter — a client that joined mid-block or replayed the buffer. */
function rebase(startedAt: number | undefined, elapsedMs: number | undefined) {
  if (elapsedMs == null) return startedAt;
  const fromServer = Date.now() - elapsedMs;
  if (startedAt == null || Math.abs(fromServer - startedAt) > 1000)
    return fromServer;
  return startedAt;
}

/**
 * Fold one `thought` frame into its reasoning block, found by the SERVER's id:
 * a closing frame can arrive after other parts, and matching "the last part"
 * silently dropped it there — leaving the block ticking. Time is the server's
 * too, so a re-attached client (which replays the block in a burst) keeps the
 * real elapsed instead of "<1s", and `meta.duration` always wins over a value
 * this client derived. Frames without `block` fall back to the tail block.
 */
function appendThoughtPart(
  parts: AgentPart[],
  text: string,
  meta: Record<string, unknown>,
): void {
  const duration = typeof meta.duration === "number" ? meta.duration : undefined;
  const block = typeof meta.block === "number" ? meta.block : undefined;
  const elapsedMs =
    typeof meta.elapsed_ms === "number" ? meta.elapsed_ms : undefined;

  // Which block does this frame belong to? By id when the server names one;
  // otherwise the most recent thought block, and only while it is still open.
  let idx = -1;
  for (let i = parts.length - 1; i >= 0; i--) {
    const p = parts[i];
    if (p.kind !== "thought") continue;
    if (block != null) {
      if (p.block !== block) continue;
      idx = i;
      break;
    }
    // Still open, or closed only by this client's guess — a late authoritative
    // frame still belongs to it (this is what makes the fix work on its own,
    // against a backend that does not name blocks yet).
    if (!p.done || p.derived) idx = i;
    break; // at most one block is open, and it is the most recent one
  }

  if (idx >= 0) {
    const prev = parts[idx] as Extract<AgentPart, { kind: "thought" }>;
    parts[idx] = {
      ...prev,
      text: prev.text + text,
      startedAt: rebase(prev.startedAt, elapsedMs),
      duration: duration ?? (prev.derived ? undefined : prev.duration),
      // More reasoning after a block this client had sealed itself means the
      // guess was wrong and the model is still thinking — re-open it.
      done: duration != null ? true : prev.derived ? false : prev.done,
      derived: duration != null ? undefined : prev.derived,
      block: prev.block ?? block,
    };
  } else if (text) {
    // At most one block is ever open: a new one means every earlier one is
    // over. The server already closes them, so this normally finds nothing —
    // but an orphaned block only shows up as a counter that never stops.
    finalizeOpenThoughts(parts);
    parts.push({
      kind: "thought",
      text,
      startedAt: Date.now() - (elapsedMs ?? 0),
      duration,
      done: duration != null,
      block,
    });
  }
  // Nothing to open: the ONLY chunk that carries no text is the one closing a
  // thought (`_close_thought` sends duration and an empty body), and with no
  // open block to close, the model reasoned for a measurable time without
  // emitting a word. That used to append a text-less block, which rendered as
  // nothing yet still counted as the turn's last part — collapsing the block
  // above it, taking the streaming cursor with it, and hiding the final answer
  // by making the tail not-a-text (see `splitTurn`). A duration with no
  // reasoning to label is not worth a part.
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

const COMPOSING = "tool_composing";
/** A `step` frame that reports something about the REQUEST rather than a step of
 * the round — it renders nothing and must leave the turn's live state alone. */
const IMAGE_DELIVERY = "image_delivery";

/** Drop every "still writing this call" placeholder.
 *
 * The placeholder is the ONE part with no event of its own to retire it: the
 * backend emits it from `tool_call_composing` and then simply stops mentioning
 * it, on the assumption that the call it describes will show up as a step and
 * take its place. Two kinds of frame break that assumption, and both used to
 * leave a row pulsing "preparing {tool}" over work that was already finished:
 *
 * - tools that render NO card of their own (`todo_list---*`, `task_control---*`
 *   map to no step meta server-side), so no step ever arrives for them — their
 *   result surfaces as a plan snapshot instead;
 * - a turn that ends before the call lands (error), where the last frame is not
 *   a step either.
 *
 * So every frame that proves the composing phase is over sweeps, not just the
 * step frame. Sweeping ALL placeholders (not the matching index) is deliberate:
 * the SDK writes a round's calls as one array, so any evidence the round moved
 * on retires the whole set. Beyond the stale animation this also keeps `isLast`
 * and the summary split honest — both read the tail of `parts`, and a leftover
 * placeholder sitting there collapses the block that should be open and hides a
 * final answer that should be outside the fold. */
function sweepComposing(parts: AgentPart[]): void {
  for (let i = parts.length - 1; i >= 0; i--) {
    const p = parts[i];
    if (p.kind === "step" && p.step.kind === COMPOSING) parts.splice(i, 1);
  }
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
  // An image outcome is a report about the REQUEST, not a step in the round. It
  // produces no card at all: the model's own reply already says it cannot see
  // the picture, and the badge on the attachment says why — a third telling in
  // between would be noise. Broadcast so the bubble can update mid-turn.
  //
  // Handled first, ahead of everything that treats a step as proof the round
  // moved on: this frame arrives right after the response's first chunk, so it
  // lands in the middle of whatever is still in flight — including the first
  // `tool_composing` frame of a round, whose placeholder the sweep below would
  // retire while the call was still being written.
  if (meta.kind === IMAGE_DELIVERY) {
    dispatchImageDelivery(String(meta.path ?? ""), String(meta.state ?? ""));
    return;
  }
  // "Still writing this call" placeholders: one per tool-call index, updated in
  // place as the arguments grow. Handled before everything below because they
  // carry no call_id and must never merge with a real step.
  if (meta.kind === COMPOSING) {
    const index = Number(meta.index ?? 0);
    for (let i = parts.length - 1; i >= 0; i--) {
      const p = parts[i];
      if (
        p.kind === "step" &&
        p.step.kind === COMPOSING &&
        Number(p.step.meta.index ?? 0) === index
      ) {
        parts[i] = { kind: "step", step: { kind: COMPOSING, meta } };
        return;
      }
    }
    parts.push({ kind: "step", step: { kind: COMPOSING, meta } });
    return;
  }
  // A real step landed: the round is represented by its own cards now.
  sweepComposing(parts);

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
  // Fallback for buffers whose ASK card carries no call_id: continue it by
  // tool_name when the tool result arrives. `tool_name` is stamped only on ask
  // cards, so it identifies one whatever kind it renders as (a shell ask is a
  // terminal card).
  //
  // Two conditions keep this from reaching across calls, because a tool name is
  // not an identity — the same tool is called again in a later round all the
  // time, and a denied one is retried immediately:
  //   * the candidate must carry NO call_id. One that carries a DIFFERENT id is
  //     a different call, already identified, and must never be overwritten.
  //   * it must belong to the same round (`group`).
  // Without them a retry hijacked the earlier call's card: the retry landed in
  // the previous round's slot instead of below the "let me try again" reasoning
  // (so its own position rendered blank), and it erased what that slot said —
  // a timed-out ask's "rejected" state was replaced by the retry's pending
  // buttons, i.e. live approval buttons for a request already answered.
  if (meta.kind !== "authorization") {
    const name = String(meta.tool ?? meta.name ?? "");
    const group = String(meta.group ?? "");
    for (let i = parts.length - 1; i >= 0; i--) {
      const p = parts[i];
      if (p.kind !== "step") continue;
      if (String(p.step.meta.tool_name ?? "") !== name || name === "") continue;
      if (String(p.step.meta.call_id ?? "") !== "") continue;
      const otherGroup = String(p.step.meta.group ?? "");
      if (otherGroup && group && otherGroup !== group) continue;
      if (p.step.meta.state === "rejected" && meta.status === "error") {
        return; // rejection already shown by the auth card
      }
      parts[i] = { kind: "step", step: { kind: meta.kind as StepKind, meta } };
      if (meta.kind === "file_write" || meta.kind === "file_edit")
        notifyWorkspace();
      return;
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
  // Assistant turns only: this is the trailing message of a turn that is STILL
  // RUNNING — the rounds it finished are on disk, the rest is still coming over
  // the live stream. A viewer attached to that stream is receiving the same
  // rounds again and drops this copy (see ChatPanel); a viewer without a stream
  // keeps it, since it is all they have.
  partial?: boolean;
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
    if (row.partial) msg.partial = true;
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
