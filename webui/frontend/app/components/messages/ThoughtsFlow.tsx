import { useEffect, useState } from 'react'
import { useT } from '~/lib/i18n'
import ThinkingIcon from '~/assets/icons/thinking.svg?react'
import ArrowDownIcon from '~/assets/icons/arrow-down.svg?react'

/** Format elapsed seconds as "Ns" (< 60s) or "Nm Ns" (per the design). */
function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

/**
 * A single reasoning block: a "thinking Ns..." header (a live counter that ticks
 * up while streaming, then freezes at the reported duration) followed by the
 * gray reasoning text. One is rendered per `thought` part, in stream order.
 *
 * While the model is still thinking (`!done`) the reasoning stays visible and
 * cannot be collapsed, and the header counts up from `startedAt`. Once thinking
 * finishes (`done`) it defaults to collapsed and shows the frozen elapsed time.
 */
export function ThoughtsFlow({
  text,
  startedAt,
  duration,
  done,
  isLast
}: {
  text: string
  startedAt?: number
  duration?: number
  done?: boolean
  /** Whether this thought is currently the last meaningful part in the message.
   * When true → expanded; when it becomes false (new parts arrived) → auto-collapse. */
  isLast?: boolean
}) {
  const { t } = useT()
  // done=false → live streaming; done=undefined (server history) or true → complete.
  const isDone = done !== false

  const [expanded, setExpanded] = useState(isLast ?? false)

  // Auto-collapse when this thought is no longer the last part (streaming
  // pushed new content after it).
  useEffect(() => {
    if (isDone && !isLast) setExpanded(false)
  }, [isDone, isLast])

  // Live elapsed seconds, ticked once a second while thinking is in flight.
  const [elapsed, setElapsed] = useState(() =>
    startedAt ? Math.max(0, Math.floor((Date.now() - startedAt) / 1000)) : 0
  )
  useEffect(() => {
    if (done || !startedAt) return
    const tick = () =>
      setElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [done, startedAt])

  if (!text) return null

  // Finished → the reported duration; live → the ticking counter.
  //
  // A duration of 0 is treated as "none": the SDK rounds the thinking time to
  // whole seconds, so a sub-second block reports 0 — and a block cut short by
  // Stop reports nothing at all (its end callback never runs, and history
  // carries no start time). Rendering "0s" in the first case but nothing in the
  // second made the label flicker from "0s" to blank when the canonical history
  // replaced the live turn. "0s" carries no information anyway, so both cases
  // now show the bare label.
  const reported = duration != null && duration > 0 ? duration : undefined
  const shown = isDone ? reported : elapsed
  const timing = shown != null ? ` ${formatDuration(shown)}` : ''
  const header = isDone
    ? `${t.chat.thoughts}${timing}`
    : `${t.chat.thoughts}${timing} ...`

  // Live thinking → always shown; finished → collapsed unless the user expands.
  // `done` is explicitly `false` only during live streaming; `undefined` or `true`
  // (from server history) means the thought is complete → default collapsed.
  const showContent = !isDone || expanded
  return (
    <div>
      {isDone ? (
        <div
          onClick={() => setExpanded((v: boolean) => !v)}
          className="flex cursor-pointer items-center gap-1.5 text-sm text-msa-text-2"
        >
          <ThinkingIcon className="h-5 w-5 shrink-0" />
          <span>{header}</span>
          <ArrowDownIcon
            className={`h-3 w-3 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
          />
        </div>
      ) : (
        <div className="flex items-center gap-1.5 text-sm font-medium text-msa-text-2">
          <ThinkingIcon className="h-5 w-5 shrink-0" />
          <span>{header}</span>
        </div>
      )}
      <div
        className={`grid transition-all duration-200 ease-out ${
          showContent
            ? 'grid-rows-[1fr] opacity-100'
            : 'grid-rows-[0fr] opacity-0'
        }`}
      >
        <div className="overflow-hidden">
          <div className="whitespace-pre-wrap pt-1.5 text-sm leading-relaxed text-msa-text-3">
            {text}
          </div>
        </div>
      </div>
    </div>
  )
}
