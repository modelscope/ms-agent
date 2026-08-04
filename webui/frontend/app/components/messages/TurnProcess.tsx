import { useEffect, useState } from 'react'
import { useT } from '~/lib/i18n'
import TaskIcon from '~/assets/icons/task.svg?react'
import ArrowDownIcon from '~/assets/icons/arrow-down.svg?react'

/** Format elapsed seconds as "Ns" (< 60s) or "Nm Ns" (per the design). */
function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

/**
 * Turn-level process wrapper: everything a turn produced BEFORE its final
 * summary answer lives under one header.
 *
 * - While the turn runs (`done === false`) the header reads "processing Ns ..."
 *   with a live counter and the blocks below stay FLAT — no chevron, not
 *   collapsible (the user watches the work happen).
 * - Once the SDK closes the tool-call loop (`loop_end` → the turn's final
 *   assistant text becomes the summary) the header flips to "processed Ns",
 *   becomes a collapsible accordion (collapsed by default) and its content is
 *   wrapped in a bordered card; the summary renders after it, outside.
 * - An interrupted turn never gets a summary, so it keeps the flat
 *   "processing" presentation with its frozen elapsed time.
 */
export function TurnProcess({
  done,
  live,
  startedAt,
  durationMs,
  children
}: {
  /** Loop finished → collapsible "processed" header + bordered content. */
  done: boolean
  /** Turn still streaming → tick the counter. */
  live: boolean
  /** Epoch ms of the turn's first frame (live counter base). */
  startedAt?: number
  /** Server-reported loop duration; preferred once done. */
  durationMs?: number
  children: React.ReactNode
}) {
  const { t } = useT()
  const [expanded, setExpanded] = useState(false)

  // Live elapsed seconds, ticked once a second while the turn is in flight.
  // FLOOR (not round) so the number matches wall-clock reading and formatDuration
  // — rounding showed "1s" at 0.5s and could tick backwards on timer drift.
  const [elapsed, setElapsed] = useState(() =>
    startedAt ? Math.max(0, Math.floor((Date.now() - startedAt) / 1000)) : 0
  )
  useEffect(() => {
    if (!live || !startedAt) return
    const tick = () =>
      setElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [live, startedAt])

  // Prefer the server's loop duration once the turn is done (authoritative and
  // identical across live / replay); fall back to the live tick. `elapsed` is
  // rendered even at 0 — hiding it for the first second made the header text
  // change width one tick later, which read as a jitter.
  const seconds = durationMs != null ? Math.floor(durationMs / 1000) : elapsed
  const timing = ` ${formatDuration(seconds)}`

  if (!done) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-1.5 text-sm font-medium text-msa-text-3">
          <TaskIcon className="h-5 w-5 shrink-0" />
          <span>
            {t.chat.processing}
            {timing}
            {/* The trailing ellipsis means "still running" — an interrupted turn
                keeps the "processing" wording but its clock has stopped. */}
            {live ? ' ...' : ''}
          </span>
        </div>
        {children}
      </div>
    )
  }

  return (
    <div>
      <div
        onClick={() => setExpanded((v) => !v)}
        className="flex w-fit cursor-pointer items-center gap-1.5 text-md text-msa-text-3"
      >
        <span>
          {t.chat.processed}
          {timing}
        </span>
        <ArrowDownIcon
          className={`h-3 w-3 transition-transform duration-200 ${
            expanded ? 'rotate-180' : ''
          }`}
        />
      </div>
      <div
        className={`grid transition-all duration-200 ease-out ${
          expanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
        }`}
      >
        <div className="overflow-hidden">
          {/* Expanded process history gets its own bordered card (design). */}
          <div className="mt-2 space-y-3 rounded-2xl border border-msa-line-1 p-4">
            {children}
          </div>
        </div>
      </div>
    </div>
  )
}
