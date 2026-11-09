import { Markdown } from '~/components/common/Markdown'
import type { AgentMessage, AgentPart } from '~/lib/agentProvider'
import type { OnOpenStep, OnOpenFile } from './types'
import { ThoughtsFlow } from './ThoughtsFlow'
import { TaskPlan } from './TaskPlan'
import { ToolBatch } from './ToolBatch'
import { ToolComposing } from './ToolComposing'
import { StepCard } from './StepCard'
import { TurnProcess } from './TurnProcess'
import { splitTurn } from './turnSplit'
import { ArtifactFiles } from './ArtifactFiles'
import { ErrorCard } from './ErrorCard'
import { TurnPlan } from './TurnPlan'

type StepPart = Extract<AgentPart, { kind: 'step' }>
type RenderGroup =
  | { kind: 'steps'; parts: StepPart[]; endIdx: number; group: unknown }
  | { kind: 'composing'; parts: StepPart[]; endIdx: number }
  | { kind: 'single'; part: AgentPart; endIdx: number }

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
      if (part.step.kind === 'context_compaction') {
        // Upkeep is a plain notice, never a tool accordion or tool count.
        groups.push({ kind: 'single', part, endIdx: i })
        return
      }
      const prev = groups[groups.length - 1]
      const group = part.step.meta.group
      // Not a tool round: nothing has run. Kept in its own group so it never
      // inflates the "used N tools" header of a real round.
      if (part.step.kind === 'tool_composing') {
        if (prev?.kind === 'composing' && prev.endIdx === i - 1) {
          prev.parts.push(part)
          prev.endIdx = i
        } else {
          groups.push({ kind: 'composing', parts: [part], endIdx: i })
        }
        return
      }
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

/** A React key each block OWNS, instead of the position it happens to sit at.
 *
 * The parts array is not append-only: a stale placeholder gets swept out of the
 * MIDDLE of it (see `sweepComposing`), and when a turn seals, the live parts are
 * replaced wholesale by the server's reconstruction, which need not line up
 * block for block. Under a positional key React hands one block's mounted state
 * to a DIFFERENT block whenever that happens — a thought's expand flag and
 * running timer, an accordion's open flag — and for a component whose hook count
 * depends on its props it escalates to "the order of Hooks changed", which is an
 * error rather than a cosmetic glitch. So the two blocks that own an identity
 * use it: a tool round its server-assigned round id (paired with a call id, in
 * case a round is ever split across two groups), a thought its start stamp. The
 * rest keep the index — they hold no state worth carrying across a shift. */
function groupKey(g: RenderGroup, gi: number): string {
  if (g.kind === 'steps') {
    const { group, call_id: callId } = g.parts[0].step.meta
    return `steps-${String(group ?? '')}-${String(callId ?? gi)}`
  }
  if (g.kind === 'composing') return `composing-${gi}`
  const p = g.part
  if (p.kind === 'thought') return `thought-${p.startedAt ?? gi}`
  return `${p.kind}-${gi}`
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
  const { loopDone, processParts, summary, trailingNotices } = splitTurn(parts, streaming)

  const renderParts = (source: AgentPart[], frozen: boolean) =>
    groupParts(source).map((g, gi) => {
      const key = groupKey(g, gi)
      // Expanded if it's the last meaningful block; auto-collapses when new
      // parts arrive (checked against the ORIGINAL parts order). Blocks folded
      // into the finished "processed" card are all history — keep them closed.
      const isLast =
        !frozen &&
        !source.slice(g.endIdx + 1).some((p) =>
          p.kind !== 'interrupted' &&
          !(p.kind === 'step' && p.step.kind === 'context_compaction')
        )
      if (g.kind === 'composing') {
        // A placeholder is only ever truthful in one position: the tail of a turn
        // that is still streaming. Anywhere else it outlived the call it stood
        // for — the stream layer sweeps those (sweepComposing), and this is the
        // backstop for a path that doesn't, e.g. a turn the user stopped, whose
        // parts are frozen exactly as the last frame left them. A pulsing
        // "preparing …" row over finished work is worse than no row at all.
        if (!streaming || !isLast) return null
        return <ToolComposing key={key} steps={g.parts} />
      }
      if (g.kind === 'steps') {
        // One server tool round (1..N calls) → one nested accordion.
        return (
          <ToolBatch
            key={key}
            steps={g.parts}
            isLast={isLast}
            onOpenStep={onOpenStep}
            onOpenFile={onOpenFile}
          />
        )
      }
      const part = g.part
      if (part.kind === 'step') {
        return <StepCard key={key} step={part.step} />
      }
      if (part.kind === 'thought') {
        return (
          <ThoughtsFlow
            key={key}
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
          <TaskPlan key={key} tasks={part.tasks} isLast={isLast} streaming={false} />
        )
      }
      if (part.kind === 'interrupted') {
        return null
      }
      // Text: only the last text block gets the streaming cursor.
      return (
        part.text && (
          <Markdown
            key={key}
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
      {renderParts(trailingNotices, true)}
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
