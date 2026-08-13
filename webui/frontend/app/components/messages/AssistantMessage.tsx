import { Markdown } from '~/components/common/Markdown'
import type { AgentMessage, AgentPart } from '~/lib/agentProvider'
import type { OnOpenStep, OnOpenFile } from './types'
import { ThoughtsFlow } from './ThoughtsFlow'
import { TaskPlan } from './TaskPlan'
import { ToolBatch } from './ToolBatch'
import { TurnProcess } from './TurnProcess'
import { splitTurn } from './turnSplit'
import { ArtifactFiles } from './ArtifactFiles'
import { ErrorCard } from './ErrorCard'
import { TurnPlan } from './TurnPlan'

type StepPart = Extract<AgentPart, { kind: 'step' }>
type RenderGroup =
  | { kind: 'steps'; parts: StepPart[]; endIdx: number; group: unknown }
  | { kind: 'single'; part: Exclude<AgentPart, StepPart>; endIdx: number }

/** History-replayed approved authorizations render nothing (the adjacent
 * tool step shows the invocation) — exclude them from grouping so the
 * "used N tools" count matches what's actually visible. */
function isHiddenStep(p: StepPart): boolean {
  return (
    p.step.kind === 'authorization' &&
    String(p.step.meta.state ?? '') === 'approved' &&
    !p.step.meta.request_id
  )
}

/** Group step parts by the SERVER-ASSIGNED tool-round id (`meta.group`):
 * one assistant reply's tool-call set shares one id (stamped by the live
 * mapper and history reconstruction alike) — the frontend only mirrors that
 * set under a nested accordion, it never invents its own grouping. Steps
 * without a group id (defensive fallback) render standalone. */
function groupParts(parts: AgentPart[]): RenderGroup[] {
  const groups: RenderGroup[] = []
  parts.forEach((part, i) => {
    if (part.kind === 'step') {
      const prev = groups[groups.length - 1]
      const group = part.step.meta.group
      if (isHiddenStep(part)) {
        // Invisible, but must not split the round it sits inside.
        if (prev?.kind === 'steps' && prev.endIdx === i - 1) prev.endIdx = i
        return
      }
      if (
        group != null &&
        prev?.kind === 'steps' &&
        prev.endIdx === i - 1 &&
        prev.group === group
      ) {
        prev.parts.push(part)
        prev.endIdx = i
      } else {
        groups.push({ kind: 'steps', parts: [part], endIdx: i, group })
      }
      return
    }
    groups.push({ kind: 'single', part, endIdx: i })
  })
  return groups
}

/**
 * Rich assistant message. A turn is presented in two stages (design spec):
 *
 * - while it runs, every block sits FLAT under a live "processing Ns ..."
 *   header (no accordion — the user watches the work);
 * - once the SDK closes the tool-call loop, the turn's trailing text block IS
 *   the final summary: it renders on its own, and everything before it folds
 *   into the collapsible "processed Ns" card above it.
 *
 * Falls back to plain markdown of `content` when a message has no parts (e.g.
 * an error/fallback message).
 */
export function AssistantMessage({
  message,
  streaming,
  sessionId,
  onOpenStep,
  onOpenFile
}: {
  message: AgentMessage
  streaming: boolean
  /** Backend session id — the plan chip fetches the session plan with it. */
  sessionId?: string | null
  onOpenStep?: OnOpenStep
  onOpenFile?: OnOpenFile
}) {
  const parts = message.parts

  if (!parts || parts.length === 0) {
    return (
      <div className="space-y-3">
        {/* A turn that has started but produced nothing yet still shows the
            "processing Ns" header, so the counter is visible from 0 and grows
            naturally. Without this the header first appeared with the first
            part — after a slow model's think delay it popped in already
            reading "8s". */}
        {streaming && message.turnStartedAt != null && (
          <TurnProcess
            done={false}
            live
            startedAt={message.turnStartedAt}
            durationMs={message.loopDurationMs}
          >
            {null}
          </TurnProcess>
        )}
        {message.content && (
          <Markdown content={message.content} streaming={streaming} />
        )}
      </div>
    )
  }

  // An interrupted turn produced no summary — it stays in the "processing"
  // presentation forever (per spec), so the partial work isn't hidden behind a
  // "processed" header that never really happened.
  const { loopDone, processParts, summary } = splitTurn(parts, streaming)

  const renderParts = (source: AgentPart[], frozen: boolean) =>
    groupParts(source).map((g, gi) => {
      // Expanded if it's the last meaningful block; auto-collapses when new
      // parts arrive (checked against the ORIGINAL parts order). Blocks folded
      // into the finished "processed" card are all history — keep them closed.
      const isLast =
        !frozen &&
        !source.slice(g.endIdx + 1).some((p) => p.kind !== 'interrupted')
      if (g.kind === 'steps') {
        // One server tool round (1..N calls) → one nested accordion.
        return (
          <ToolBatch
            key={gi}
            steps={g.parts}
            isLast={isLast}
            onOpenStep={onOpenStep}
            onOpenFile={onOpenFile}
          />
        )
      }
      const part = g.part
      if (part.kind === 'thought') {
        return (
          <ThoughtsFlow
            key={gi}
            text={part.text}
            startedAt={part.startedAt}
            duration={part.duration}
            done={part.done}
            isLast={isLast}
          />
        )
      }
      if (part.kind === 'tasks') {
        // A conversation plan block is a frozen SNAPSHOT of the plan at that
        // point in the stream (each update appends a new one) — never animated,
        // even mid-turn. The composer's pinned panel is the live view.
        return (
          <TaskPlan key={gi} tasks={part.tasks} isLast={isLast} streaming={false} />
        )
      }
      if (part.kind === 'interrupted') {
        return null
      }
      // Text: only the last text block gets the streaming cursor.
      return (
        part.text && (
          <Markdown
            key={gi}
            content={part.text}
            streaming={streaming && isLast}
          />
        )
      )
    })

  // changed_files carries the reserved "plan.md" marker when the loop rewrote
  // the todo list (pairs with `plan_file`). The plan lives in the SESSION dir,
  // not the workspace, so it is NOT a file card: it renders once more at the
  // end as the flat TaskPlan list (TurnPlan). Out-of-workspace writes and
  // custom-named plan files are already filtered server-side
  // (sessions.changed_files_in_rows), so only the literal "plan.md" marker
  // reaches here.
  const deliverables = (message.changedFiles ?? []).filter(
    (p) => p !== 'plan.md'
  )
  const planTouched =
    !!message.planFile || (message.changedFiles ?? []).includes('plan.md')
  // This turn's FINAL plan state = the LAST plan snapshot the turn produced
  // (each todo_write appends one). TurnPlan renders THIS per-turn state, not
  // the session's current plan — an old turn's plan must not reflect a later
  // turn's edits. Undefined for a render-only turn (no snapshot); TurnPlan then
  // falls back to GET /plan.
  const turnPlanTasks = [...parts]
    .reverse()
    .find((p): p is Extract<AgentPart, { kind: 'tasks' }> => p.kind === 'tasks')
    ?.tasks

  // Errors never fold into the "processed" accordion: a turn/API failure must
  // be visible without expanding anything (a message that is ONLY an error
  // would otherwise be an empty-looking collapsed card).
  const errorParts = processParts.filter(
    (p): p is Extract<AgentPart, { kind: 'error' }> => p.kind === 'error'
  )
  const foldableParts = processParts.filter((p) => p.kind !== 'error')

  return (
    <div className="space-y-3">
      {/* Header shows while the turn RUNS (even before its first block) or once
          it has folded content — never for a bare finished reply. */}
      {(foldableParts.length > 0 ||
        (streaming && message.turnStartedAt != null)) && (
        <TurnProcess
          done={loopDone}
          live={streaming}
          startedAt={message.turnStartedAt}
          durationMs={message.loopDurationMs}
        >
          {renderParts(foldableParts, loopDone)}
        </TurnProcess>
      )}
      {/* Alert cards sit outside the fold, before the summary. */}
      {errorParts.map((p, i) => (
        <ErrorCard key={`err-${i}`} text={p.text} recoverable={p.recoverable} />
      ))}
      {summary && <Markdown content={summary.text} streaming={false} />}
      {/* The turn's deliverables (files written/edited this loop) close the
          message, after the summary. */}
      {loopDone && deliverables.length > 0 && (
        <ArtifactFiles paths={deliverables} onOpenFile={onOpenFile} />
      )}
      {/* The final todo plan is replayed once more as a flat task list (not a
          file card), per the design — showing THIS turn's final state (the
          per-turn snapshot), falling back to GET /plan only for a render-only
          turn that produced no snapshot. */}
      {loopDone && planTouched && (
        <TurnPlan
          tasks={turnPlanTasks}
          sessionId={sessionId ?? undefined}
        />
      )}
    </div>
  )
}
