import { useEffect, useState } from 'react'
import { useT } from '~/lib/i18n'
import type { AgentTask } from '~/lib/agentProvider'
import TodoIcon from '~/assets/icons/todo.svg?react'
import TaskDoneIcon from '~/assets/icons/task-done.svg?react'
import TaskRunningIcon from '~/assets/icons/task-running.svg?react'
import TaskPausedIcon from '~/assets/icons/task-paused.svg?react'
import TaskWaitingIcon from '~/assets/icons/task-waiting.svg?react'
import ArrowDownIcon from '~/assets/icons/arrow-down.svg?react'

/** Same status glyph set as the composer's thinking plan list (mirrored so
 * both task lists read identically) — the design-spec circled icons, colored
 * via currentColor so one asset covers light & dark. A "running" item without
 * a live turn is stale plan-file state (e.g. an interrupted turn) — degrade
 * to the paused glyph. */
export function taskStatusIcon(
  status: AgentTask['status'],
  streaming: boolean
) {
  switch (status) {
    case 'done':
      return <TaskDoneIcon className="h-4 w-4 text-msa-green-5" />
    case 'running':
      return streaming ? (
        <TaskRunningIcon className="h-4 w-4 animate-spin text-msa-green-5" />
      ) : (
        <TaskPausedIcon className="h-4 w-4 text-msa-text-disabled" />
      )
    case 'pending':
      return <TaskWaitingIcon className="h-4 w-4 text-msa-text-disabled" />
    default:
      return <TaskWaitingIcon className="h-4 w-4 text-msa-text-disabled" />
  }
}

/**
 * Todo-plan card as an inline accordion (per the design spec): the header
 * ("todo tasks" + done/total) toggles a timeline-style task list — status
 * circles joined by a dashed spine. No right-rail detail anymore.
 *
 * Expansion follows the shared accordion convention: open while it's the
 * message's LAST meaningful block, auto-collapses once newer parts arrive,
 * manual toggling always available.
 */
export function TaskPlan({
  tasks,
  isLast,
  streaming = false
}: {
  tasks: AgentTask[]
  isLast?: boolean
  /** Whether a turn is live — gates the animated "running" spinner. */
  streaming?: boolean
}) {
  const { t } = useT()
  const [expanded, setExpanded] = useState(isLast ?? false)

  useEffect(() => {
    if (!isLast) setExpanded(false)
  }, [isLast])

  if (tasks.length === 0) return null

  const done = tasks.filter((task) => task.status === 'done').length
  const total = tasks.length

  return (
    <div className="w-full overflow-hidden rounded-xl border border-msa-line-1 bg-msa-fill-0">
      {/* Header */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full cursor-pointer items-center gap-2 border-none bg-transparent px-3 py-2 text-left outline-none"
      >
        <TodoIcon className="h-4 w-4 shrink-0 text-msa-text-2" />
        <span className="text-sm font-medium text-msa-text-1">
          {t.chat.todoTasks}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm text-msa-text-3">
          {done}/{total}
        </span>
        <ArrowDownIcon
          className={`h-3 w-3 shrink-0 text-msa-text-3 transition-transform duration-200 ${
            expanded ? 'rotate-180' : ''
          }`}
        />
      </button>

      {/* Body: timeline list with a dashed spine between status circles */}
      <div
        className="grid transition-[grid-template-rows] duration-200 ease-in-out"
        style={{ gridTemplateRows: expanded ? '1fr' : '0fr' }}
      >
        <div className="overflow-hidden">
          <div className="px-3 pb-3 pt-1">
            {tasks.map((task, i) => (
              <div key={task.id} className="flex gap-2.5">
                {/* Status circle + dashed connector down to the next item */}
                <div className="flex flex-col items-center self-stretch">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden">
                    {taskStatusIcon(task.status, streaming)}
                  </span>
                  {i < tasks.length - 1 && (
                    <span className="w-[0px] flex-1 border-0 border-l border-dashed border-[#D8D8D8]" />
                  )}
                </div>
                <div
                  className={`min-w-0 flex-1 text-sm font-medium ${
                    i < tasks.length - 1 ? 'pb-4' : ''
                  } ${
                    task.status === 'pending' || task.status === 'waiting'
                      ? 'text-msa-text-3'
                      : 'text-msa-text-1'
                  }`}
                >
                  {task.label}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
