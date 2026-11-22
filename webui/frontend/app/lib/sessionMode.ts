import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '~/lib/api'
import type { ExecutionMode } from '~/lib/types'

const CHANNEL = 'msa:execution-mode'

export function useSessionMode(sessionId: string | null, initial: ExecutionMode, initialLocked: boolean, initialAvailable: boolean) {
  const [mode, setMode] = useState(initial)
  const [locked, setLocked] = useState(initialLocked)
  const [available, setAvailable] = useState(initialAvailable)
  const [saving, setSaving] = useState(false)
  const selected = useRef(initial)
  const explicit = useRef(false)
  const revision = useRef(0)
  const inFlight = useRef(0)
  const pending = useRef<Promise<unknown>>(Promise.resolve())
  const channel = useRef<BroadcastChannel | null>(null)
  const refresh = useCallback(async () => {
    const version = revision.current
    const [settings, session] = await Promise.all([
      api.getAgentSettings(), sessionId ? api.getSession(sessionId, { silent: true }) : Promise.resolve(null)
    ])
    setAvailable(!!settings.decision_available)
    if (version !== revision.current || inFlight.current > 0) return
    if (session) {
      setLocked(!!session.execution_mode_locked)
      selected.current = session.execution_mode ?? 'standard'
      setMode(selected.current)
    } else if (!explicit.current) {
      selected.current = settings.default_execution_mode ?? 'standard'
      setMode(selected.current)
    }
  }, [sessionId])

  useEffect(() => {
    const reload = () => { void refresh().catch(() => {}) }
    const bus = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel(CHANNEL)
    channel.current = bus
    if (bus) bus.onmessage = reload
    window.addEventListener('focus', reload)
    window.addEventListener('msa:session-done', reload)
    reload()
    return () => {
      bus?.close()
      channel.current = null
      window.removeEventListener('focus', reload)
      window.removeEventListener('msa:session-done', reload)
    }
  }, [refresh])

  const select = (next: ExecutionMode) => {
    if (locked) return Promise.resolve()
    const version = ++revision.current
    explicit.current = true
    setSaving(true)
    inFlight.current += 1
    const operation = pending.current.catch(() => {}).then(async () => {
      if (sessionId) await api.updateSessionExecutionMode(sessionId, next)
      else await api.putAgentSettings({ default_execution_mode: next })
      if (revision.current === version) {
        selected.current = next
        setMode(next)
      }
      channel.current?.postMessage(sessionId)
    }).catch(async error => {
      explicit.current = false
      throw error
    }).finally(() => {
      inFlight.current -= 1
      if (revision.current === version) {
        setSaving(false)
        void refresh().catch(() => {})
      }
    })
    pending.current = operation
    void operation.catch(() => {})
    return operation
  }
  const ready = async () => {
    let operation: Promise<unknown>
    do { operation = pending.current; await operation } while (operation !== pending.current)
    return selected.current
  }
  return { mode, locked, available, saving, select, ready }
}
export type SessionModeSelection = ReturnType<typeof useSessionMode>
