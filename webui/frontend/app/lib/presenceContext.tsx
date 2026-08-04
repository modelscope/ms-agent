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
import { useOnSessionDone } from '~/lib/events'

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

  useEffect(() => {
    let alive = true
    const beat = async () => {
      try {
        const res = await api.postPresence()
        if (!alive) return
        const next = new Set(res.running)
        const prev = prevRef.current
        prevRef.current = next
        setRunning(next)
        // Any running-set change revalidates route data: a session ENTERING
        // the set may be brand-new (started from the home page — the sidebar
        // doesn't list it until loaders re-run), and one LEAVING it means its
        // background answer is ready for an open session view / flag clear.
        const changed =
          next.size !== prev.size || [...next].some((id) => !prev.has(id))
        if (changed) revalidateRef.current()
      } catch {
        // Offline/unreachable backend: keep beating; the next success resyncs.
      }
    }
    beat()
    const timer = setInterval(beat, HEARTBEAT_MS)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [])

  // When a turn finishes in THIS tab (done frame), immediately remove the
  // session from the running set so the spinner disappears without waiting
  // for the next heartbeat.
  const handleDone = useCallback(
    (sid: string) => {
      setRunning((prev) => {
        if (!prev.has(sid)) return prev
        const next = new Set(prev)
        next.delete(sid)
        return next
      })
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
