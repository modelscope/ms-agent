import { useEffect, useState } from 'react'
import { api } from '~/lib/api'
import type { AgentTask, TaskStatus } from '~/lib/agentProvider'
import { TaskPlan } from './TaskPlan'

/** Narrow the server's plan status strings (already frontend-mapped by
 * sessions._plan_part) into the AgentTask status union. */
function toAgentTasks(
  tasks: { id: string; label: string; status: string }[]
): AgentTask[] {
  return tasks.map((t) => ({
    id: t.id,
    label: t.label,
    status: (['done', 'running', 'pending'].includes(t.status)
      ? t.status
      : 'pending') as TaskStatus
  }))
}

/**
 * Final plan recap at the end of a finished turn: when the loop rewrote the
 * todo list (reserved "plan.md" changed_files entry / `plan_file`), the plan
 * is shown ONE more time here as the flat TaskPlan accordion — same widget the
 * conversation uses inline — instead of a file card. The plan lives in the
 * SESSION dir, not the workspace, so it never goes through the file card /
 * exists-check.
 *
 * Scope is PER-TURN: `tasks` is THIS turn's final plan snapshot (the last
 * `tasks` part on the message). It is rendered directly so an old turn's recap
 * shows the plan as it was at THAT turn — never a later turn's edits. Only a
 * render-only turn (todo_render_md without a todo_write → no snapshot) leaves
 * `tasks` undefined; then it falls back to the session's current plan via
 * GET /sessions/{id}/plan. Renders nothing when there's neither.
 */
export function TurnPlan({
  tasks,
  sessionId
}: {
  /** This turn's final plan snapshot; rendered directly when present. */
  tasks?: AgentTask[]
  /** Fallback source for a render-only turn (no snapshot). */
  sessionId?: string
}) {
  const [fetched, setFetched] = useState<AgentTask[] | null>(null)
  const hasSnapshot = tasks !== undefined

  useEffect(() => {
    // Only fetch as a fallback: a per-turn snapshot needs no request.
    if (hasSnapshot || !sessionId) return
    let cancelled = false
    api
      .getSessionPlan(sessionId, { silent: true })
      .then((plan) => {
        if (!cancelled) setFetched(toAgentTasks(plan.tasks))
      })
      .catch(() => {
        if (!cancelled) setFetched([])
      })
    return () => {
      cancelled = true
    }
  }, [hasSnapshot, sessionId])

  const plan = hasSnapshot ? tasks : fetched
  if (!plan || plan.length === 0) return null

  // isLast → the recap opens expanded (it closes the message); a frozen
  // snapshot, so no live spinner.
  return <TaskPlan tasks={plan} isLast streaming={false} />
}
