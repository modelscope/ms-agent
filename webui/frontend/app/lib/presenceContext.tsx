import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState
} from 'react'
import type { ReactNode } from 'react'
import { useRevalidator } from 'react-router'
import { api } from '~/lib/api'
import { useOnSessionDone, useOnSessionStarted } from '~/lib/events'

/**
 * Live running-session state poll.
 *
 * POSTs /api/presence and publishes the ids of sessions with a turn in flight,
 * driving the sidebar spinners, the live re-attach and route revalidation.
 *
 * Beats every HEARTBEAT_MS while a turn is running and every IDLE_HEARTBEAT_MS
 * otherwise, only while the tab is visible — plus one beat on mount (even if the
 * tab is hidden) and one each time it becomes visible again.
 */
const HEARTBEAT_MS = 10_000

/** Poll interval while this tab knows of no running turn. */
const IDLE_HEARTBEAT_MS = 30_000

/**
 * How long a locally-started turn stays marked running without server
 * confirmation. The mark is dropped once the server confirms the session or this
 * window passes, whichever comes first.
 */
const OPTIMISTIC_TTL_MS = 30_000

interface PresenceValue {
  /** Ids of sessions with a turn currently in flight. */
  running: ReadonlySet<string>
  /** False until the first heartbeat has answered. */
  seeded: boolean
}

const PresenceContext = createContext<PresenceValue>({
  running: new Set(),
  seeded: false
})

export function PresenceProvider({ children }: { children: ReactNode }) {
  const [running, setRunning] = useState<ReadonlySet<string>>(() => new Set())
  const [seeded, setSeeded] = useState(false)
  const prevRef = useRef<ReadonlySet<string>>(new Set())
  const revalidator = useRevalidator()
  const revalidateRef = useRef(revalidator.revalidate)
  revalidateRef.current = revalidator.revalidate
  // Sessions this tab just started, with the instant they were marked. Merged
  // into every heartbeat result.
  const optimisticRef = useRef<Map<string, number>>(new Map())
  // Lets the session-started handler kick a poll right away.
  const beatRef = useRef<() => void>(() => {})

  useEffect(() => {
    let alive = true
    let timer = 0

    /** Replaces any pending timer with the next beat; no-op while hidden. */
    const schedule = () => {
      window.clearTimeout(timer)
      if (!alive || document.visibilityState !== 'visible') return
      timer = window.setTimeout(
        () => void beat(),
        prevRef.current.size > 0 ? HEARTBEAT_MS : IDLE_HEARTBEAT_MS
      )
    }

    const beat = async () => {
      try {
        const res = await api.postPresence()
        if (!alive) return
        // Set before the unchanged-set bail-out below, which an all-empty first
        // answer takes.
        setSeeded(true)
        // Expire optimistic marks: confirmed by the server, or past the TTL.
        const now = Date.now()
        const optimistic = optimisticRef.current
        const reported = new Set(res.running)
        for (const [sid, at] of optimistic) {
          if (reported.has(sid) || now - at > OPTIMISTIC_TTL_MS) {
            optimistic.delete(sid)
          }
        }
        const next = new Set([...res.running, ...optimistic.keys()])
        const prev = prevRef.current
        const changed =
          next.size !== prev.size || [...next].some((id) => !prev.has(id))
        // Only publish a changed set; an identical one would hand consumers a new
        // Set identity and re-run their effects.
        if (!changed) return
        prevRef.current = next
        setRunning(next)
        revalidateRef.current()
      } catch {
        // Offline/unreachable backend: keep beating; the next success resyncs.
      } finally {
        // In `finally` so the early returns above still arm the next beat.
        schedule()
      }
    }
    beatRef.current = () => void beat()
    // Beat once even when the tab starts hidden, so `seeded` reports.
    void beat()

    const onVisibility = () => {
      if (document.visibilityState === 'visible') void beat()
      else window.clearTimeout(timer)
    }
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      alive = false
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  // A turn was sent from this tab: mark it running now and poll immediately.
  const handleStarted = useCallback((sid: string) => {
    if (!sid) return
    optimisticRef.current.set(sid, Date.now())
    setRunning((prev) => (prev.has(sid) ? prev : new Set(prev).add(sid)))
    // Keep the diff baseline equal to what is rendered.
    if (!prevRef.current.has(sid)) {
      prevRef.current = new Set(prevRef.current).add(sid)
    }
    beatRef.current()
  }, [])
  useOnSessionStarted(handleStarted)

  // A turn finished in this tab: drop it from the running set without waiting
  // for the next heartbeat.
  const handleDone = useCallback((sid: string) => {
    optimisticRef.current.delete(sid)
    setRunning((prev) => {
      if (!prev.has(sid)) return prev
      const next = new Set(prev)
      next.delete(sid)
      return next
    })
    if (prevRef.current.has(sid)) {
      const next = new Set(prevRef.current)
      next.delete(sid)
      prevRef.current = next
    }
  }, [])
  useOnSessionDone(handleDone)

  const value = useMemo(() => ({ running, seeded }), [running, seeded])
  return (
    <PresenceContext.Provider value={value}>
      {children}
    </PresenceContext.Provider>
  )
}

export function usePresence() {
  return useContext(PresenceContext)
}
