import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Popover, Tooltip } from 'antd'
import { IconButton } from './IconButton'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { ContextStatus } from '~/lib/types'

/** Server estimates describe the last assembled request; the browser never tokenizes. */
export function ContextMeter({ sessionId, loading, selectionKey, onBusy, onComplete }: {
  sessionId: string
  loading: boolean
  selectionKey: string
  onBusy: (value: boolean) => void
  onComplete?: () => void
}) {
  const { t } = useT()
  const labels = t.context
  const [open, setOpen] = useState(false)
  const [state, setState] = useState<ContextStatus | null>(null)
  const [sending, setSending] = useState(false)
  const observedBusy = useRef(false)
  const epoch = useRef(0)
  const request = useRef(0)
  const complete = useRef(onComplete)
  complete.current = onComplete
  const refresh = useCallback(async () => {
    const generation = epoch.current
    const sequence = ++request.current
    const next = await api.getContext(sessionId)
    if (generation !== epoch.current || sequence !== request.current) return
    setState(next)
    const busy = !!next.busy
    onBusy(busy)
    if (observedBusy.current && !busy) complete.current?.()
    observedBusy.current = busy
  }, [sessionId, onBusy])
  useEffect(() => {
    let active = true
    epoch.current += 1
    // Invalidate immediately on model/thinking changes. Never label old usage
    // with the newly selected model while the next request is pending.
    setState(null)
    const run = () => { if (active) void refresh().catch(() => {}) }
    run()
    window.addEventListener('focus', run)
    return () => { active = false; epoch.current += 1; window.removeEventListener('focus', run) }
  }, [refresh, selectionKey, loading])
  const busy = sending || !!state?.busy
  useEffect(() => {
    if (!open && !busy && !loading) return
    const timer = window.setInterval(() => { void refresh().catch(() => {}) }, 2000)
    return () => window.clearInterval(timer)
  }, [open, busy, loading, refresh])
  const snapshot = state?.snapshot
  const ratio = snapshot?.ratio
  const percent = ratio == null ? null : Math.round(ratio * 100)
  const compact = async (retry = false) => {
    setSending(true)
    onBusy(true)
    try {
      if (retry) await api.retryContext(sessionId)
      else await api.compactContext(sessionId)
      observedBusy.current = true
      await refresh()
    } catch { onBusy(false) } finally { setSending(false) }
  }
  const stop = async () => { await api.interruptChat(sessionId); await refresh() }
  const format = (value: number) => value.toLocaleString('en', { notation: 'compact', maximumFractionDigits: 1 })
  const status = state?.operation?.status
  const statusLabel = status && status !== 'running' && status !== 'completed' ? (state?.operation?.trigger === 'retry' && status === 'not_needed' ? labels.resumed : labels.status[status]) : null
  return (
    <Popover trigger="click" placement="top" open={open} onOpenChange={setOpen}
      content={<div className="w-64 max-w-[calc(100vw-48px)] space-y-3 p-1 text-msa-text-1">
        <div className="flex items-center justify-between font-medium">
          <span>{labels.title}</span><span className="tabular-nums">{percent == null ? '—' : `${percent}%`}</span>
        </div>
        {snapshot ? <>
          <div className="text-xs tabular-nums text-msa-text-2">{labels.input.replace('{used}', format(snapshot.input_tokens)).replace('{limit}', format(snapshot.context_limit))}</div>
          <div className="h-1.5 overflow-hidden rounded-full bg-msa-fill-3">
            <div className="h-full rounded-full bg-msa-icon-neutral" style={{ width: `${Math.min(100, percent ?? 0)}%` }} />
          </div>
          <div className="space-y-2 text-xs text-msa-text-2">
            {Object.entries(snapshot.buckets).map(([key, value]) => <div key={key} className="flex justify-between gap-4">
              <span>{labels.buckets[key as keyof typeof labels.buckets] ?? key}</span><span className="shrink-0 whitespace-nowrap tabular-nums">{format(value)}</span>
            </div>)}
          </div>
          <div className="border-x-0 border-b-0 border-t border-solid border-msa-line-1 pt-2 text-xs text-msa-text-2">
            {labels.reserve.replace('{tokens}', format(snapshot.output_reserve))}
          </div>
        </> : <p className="text-xs text-msa-text-2">{labels.unavailable}</p>}
        {(busy || statusLabel || state?.operation?.memory_status === 'failed') && <div role="status" className="text-xs leading-5 text-msa-text-2">
          {busy ? (state?.resuming ? labels.resuming : labels.running) : statusLabel}
          {state?.operation?.memory_status === 'failed' && <div>{labels.memoryFailed}</div>}
        </div>}
        {!busy && state?.pending?.status === 'paused' && <Button block disabled={loading} onClick={() => { void compact(true) }}>{labels.retry}</Button>}
        {busy ? <Button block onClick={() => { void stop() }}>{labels.stop}</Button>
          : <Button block disabled={loading || !state?.can_compact} onClick={() => { void compact() }}>{labels.compact}</Button>}
      </div>}>
      <Tooltip title={open ? null : labels.title}>
        <IconButton
          aria-label={labels.title}
          aria-expanded={open}
          className="shrink-0 rounded-full!"
          icon={<svg viewBox="0 0 24 24" className={`h-5 w-5 ${busy ? 'motion-safe:animate-spin' : ''}`} aria-hidden="true">
            <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="3" className="text-msa-text-3" />
            {(busy || (percent != null && percent > 0)) && <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="3" pathLength="100"
              className="text-msa-text-1" strokeLinecap="round"
              strokeDasharray={`${busy ? 25 : Math.min(100, percent ?? 0)} 100`} transform="rotate(-90 12 12)" />}
          </svg>}
        />
      </Tooltip>
    </Popover>
  )
}
