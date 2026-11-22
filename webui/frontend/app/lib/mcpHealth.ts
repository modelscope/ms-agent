/** Shared diagnostics, scoped to the current configuration generation. */
import { useCallback, useEffect, useSyncExternalStore } from 'react'
import { api } from './api'
import { useOnMcpSkillChanged } from './events'
import type { McpHealth } from './types'

export interface McpHealthState {
  rows: Record<string, McpHealth>
  sweeping: boolean
}
const PENDING: McpHealthState = { rows: {}, sweeping: true }
let state = PENDING
let generation = 0
let fetchedAt = 0
let inFlight: Promise<void> | null = null
const listeners = new Set<() => void>()
function set(next: McpHealthState) {
  state = next
  listeners.forEach((notify) => notify())
}
function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}
export const getMcpHealthSnapshot = () => state
const getServerSnapshot = () => PENDING

function prefer(old: McpHealth | undefined, next: McpHealth): McpHealth {
  if (!old) return next
  if (old.level === 'connection' && next.level === 'command' && old.expires_at * 1000 > Date.now()) return old
  return old.checked_at > next.checked_at ? old : next
}

export function sweepMcpHealth(force = false): Promise<void> {
  if (force) {
    generation++
    fetchedAt = 0
    inFlight = null
    set({ rows: {}, sweeping: true })
  }
  if (inFlight) return inFlight
  const fresh = Object.values(state.rows).every((row) => row.expires_at * 1000 > Date.now())
  if (fetchedAt && fresh && Date.now() - fetchedAt < 60_000) return Promise.resolve()
  const current = generation
  set({ ...state, sweeping: true })
  const request = api.listMcpHealth().then((rows) => {
    if (current !== generation) return
    fetchedAt = Date.now()
    set({
      rows: Object.fromEntries(rows.map((row) => [row.id, prefer(state.rows[row.id], row)])),
      sweeping: false
    })
  }).catch(() => {
    if (current === generation) set({ ...state, sweeping: false })
  }).finally(() => {
    if (inFlight === request) inFlight = null
  })
  inFlight = request
  return request
}

/** Capture the generation before I/O so an edited/deleted row cannot return. */
export async function testMcpHealth(id: string): Promise<McpHealth> {
  const current = generation
  const row = await api.checkMcpHealth(id)
  if (current === generation) {
    set({ ...state, rows: { ...state.rows, [row.id]: prefer(state.rows[row.id], row) } })
  }
  return row
}

export function useMcpHealth() {
  const shared = useSyncExternalStore(subscribe, getMcpHealthSnapshot, getServerSnapshot)
  useEffect(() => { void sweepMcpHealth() }, [])
  useOnMcpSkillChanged(useCallback(() => { void sweepMcpHealth(true) }, []))
  return { ...shared, refresh: sweepMcpHealth, check: testMcpHealth }
}
