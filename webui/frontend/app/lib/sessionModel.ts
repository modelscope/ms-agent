import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '~/lib/api'
import type { AgentSettings } from '~/lib/types'

const CHANNEL = 'msa:session-model'

/** Page-local drafts; persisted selections only after a session exists. */
export function useSessionModel(sessionId: string | null, initialId: string, enabled = true) {
  const [modelId, setModelId] = useState(initialId)
  const [saveFailed, setSaveFailed] = useState(false)
  const selected = useRef(initialId)
  const saved = useRef(initialId)
  const pending = useRef<Promise<unknown>>(Promise.resolve())
  const revision = useRef(0)
  const saving = useRef(0)
  const error = useRef<unknown>(null)
  const channel = useRef<BroadcastChannel | null>(null)

  const refresh = useCallback(async () => {
    if (!sessionId || saving.current) return
    const version = revision.current
    const session = await api.getSession(sessionId, { silent: true })
    if (saving.current || revision.current !== version) return
    saved.current = selected.current = session.model_id || ''
    setModelId(selected.current)
  }, [sessionId])

  useEffect(() => {
    if (!enabled) return
    const reload = () => { void refresh().catch(() => {}) }
    window.addEventListener('focus', reload)
    const bus = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel(CHANNEL)
    channel.current = bus
    if (bus) bus.onmessage = (event) => { if (event.data === sessionId) reload() }
    reload()
    return () => {
      window.removeEventListener('focus', reload)
      bus?.close()
      channel.current = null
    }
  }, [enabled, refresh, sessionId])

  const select = (providerId: string, nextId: string): Promise<AgentSettings> => {
    const version = ++revision.current
    selected.current = nextId
    setModelId(nextId)
    saving.current += 1
    const request = pending.current.catch(() => {}).then(async () => {
      const result = sessionId
        ? await api.updateSessionModel(sessionId, nextId)
        : { settings: await api.putAgentSettings({ default_provider_id: providerId, default_model_id: nextId }) }
      saved.current = nextId
      if (revision.current === version) {
        error.current = null
        setSaveFailed(false)
      }
      if (sessionId) channel.current?.postMessage(sessionId)
      return result.settings
    }).catch(async (failure) => {
      if (revision.current === version) {
        error.current = failure
        setSaveFailed(true)
        // A multi-file save may have partly succeeded. Read the actual state.
        if (sessionId) {
          try { saved.current = (await api.getSession(sessionId, { silent: true })).model_id || '' } catch { /* keep last known selection */ }
        }
        selected.current = saved.current
        setModelId(saved.current)
      }
      throw failure
    }).finally(() => { saving.current -= 1 })
    pending.current = request
    void request.catch(() => {})
    return request
  }

  const ready = async () => {
    let last: Promise<unknown>
    do {
      last = pending.current
      await last
    } while (last !== pending.current)
    if (error.current) throw error.current
    return selected.current
  }

  return { modelId, select, ready, saveFailed }
}

export type SessionModelSelection = ReturnType<typeof useSessionModel>
