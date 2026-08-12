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
 * Every ~10s the app shell POSTs /api/presence and receives the ids of
 * sessions with a turn in flight. This drives the sidebar "running" spinners,
 * triggers the live re-attach when the user opens a running session, and
 * revalidates route data when the set changes (a new turn started elsewhere,
 * or a background turn finished and its answer is ready).
 *
 * Note this is a STATUS poll, not a liveness contract: by product decision a
 * running turn is never stopped because clients went away — navigation,
 * refresh and even a fully closed browser all leave it running to completion
 * in the background. Only the explicit Stop button cancels a turn.
 */
const HEARTBEAT_MS = 10_000

/**
 * How long a locally-started turn is trusted before the server has to confirm
 * it. Sending a message marks the session running IMMEDIATELY (the heartbeat is
 * far too coarse for that feedback), but the request can also fail without ever
 * producing a `done` frame — so the optimistic mark is dropped once this window
 * passes without the server reporting the session as running. Comfortably longer
 * than one heartbeat so a normal turn is confirmed well before it expires.
 */
const OPTIMISTIC_TTL_MS = 30_000

interface PresenceValue {
  /** Ids of sessions with a turn currently in flight. */
  running: ReadonlySet<string>
}

const PresenceContext = createContext<PresenceValue>({ running: new Set() })

export function PresenceProvider({ children }: { children: ReactNode }) {
  const [running, setRunning] = useState<ReadonlySet<string>>(() => new Set())
  const prevRef = useRef<ReadonlySet<string>>(new Set())
  const revalidator = useRevalidator()
  const revalidateRef = useRef(revalidator.revalidate)
  revalidateRef.current = revalidator.revalidate
  // Sessions this tab just started, with the instant they were marked. Merged
  // into every heartbeat result so a turn the server hasn't picked up yet keeps
  // its spinner instead of flickering off on the next poll.
  const optimisticRef = useRef<Map<string, number>>(new Map())
  // Lets the session-started handler kick a poll right away.
  const beatRef = useRef<() => void>(() => {})

  useEffect(() => {
    let alive = true
    const beat = async () => {
      try {
        const res = await api.postPresence()
        if (!alive) return
        // Expire stale optimistic marks (a failed request never reports done).
        const now = Date.now()
        const optimistic = optimisticRef.current
        for (const [sid, at] of optimistic) {
          if (now - at > OPTIMISTIC_TTL_MS) optimistic.delete(sid)
        }
        const next = new Set([...res.running, ...optimistic.keys()])
        const prev = prevRef.current
        const changed =
          next.size !== prev.size || [...next].some((id) => !prev.has(id))
        // Only publish a CHANGED set. Re-publishing an identical one still hands
        // every consumer a new Set identity, which re-runs their effects — the
        // session view's re-attach effect then aborted and reopened its live SSE
        // (plus a plan re-read) on every single beat.
        if (!changed) return
        prevRef.current = next
        setRunning(next)
        // Any running-set change revalidates route data: a session ENTERING
        // the set may be brand-new (started from the home page — the sidebar
        // doesn't list it until loaders re-run), and one LEAVING it means its
        // background answer is ready for an open session view / flag clear.
        revalidateRef.current()
      } catch {
        // Offline/unreachable backend: keep beating; the next success resyncs.
      }
    }
    beatRef.current = () => void beat()
    beat()
    const timer = setInterval(beat, HEARTBEAT_MS)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [])

  // A turn was just sent from THIS tab: show the spinner now rather than up to
  // HEARTBEAT_MS later, and poll immediately so the server view catches up.
  const handleStarted = useCallback((sid: string) => {
    if (!sid) return
    optimisticRef.current.set(sid, Date.now())
    setRunning((prev) => (prev.has(sid) ? prev : new Set(prev).add(sid)))
    // Keep the heartbeat's diff baseline equal to what is rendered, so the next
    // beat compares against reality (it now skips publishing when unchanged).
    if (!prevRef.current.has(sid)) {
      prevRef.current = new Set(prevRef.current).add(sid)
    }
    beatRef.current()
  }, [])
  useOnSessionStarted(handleStarted)

  // When a turn finishes in THIS tab (done frame), immediately remove the
  // session from the running set so the spinner disappears without waiting
  // for the next heartbeat.
  const handleDone = useCallback(
    (sid: string) => {
      // Drop the optimistic mark too, or the next heartbeat would re-add it.
      optimisticRef.current.delete(sid)
      setRunning((prev) => {
        if (!prev.has(sid)) return prev
        const next = new Set(prev)
        next.delete(sid)
        return next
      })
      // Baseline mirrors what's rendered (see handleStarted). Dropping it here
      // also means a session the SERVER still reports as running gets its
      // spinner back on the next beat — that beat now counts as a change.
      if (prevRef.current.has(sid)) {
        const next = new Set(prevRef.current)
        next.delete(sid)
        prevRef.current = next
      }
    },
    []
  )
  useOnSessionDone(handleDone)

  const value = useMemo(() => ({ running }), [running])
  return (
    <PresenceContext.Provider value={value}>
      {children}
    </PresenceContext.Provider>
  )
}

export function usePresence() {
  return useContext(PresenceContext)
}
