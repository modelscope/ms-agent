import { useCallback, useEffect, useState } from 'react'
import { useLocation } from 'react-router'
import { useOnUrlChange } from '~/lib/events'

/**
 * The live browser path (`window.location.pathname`), kept in sync with BOTH
 * React Router navigations and manual `history.replaceState`.
 *
 * The chat reflects a newly created session in the URL mid-stream via
 * `history.replaceState` (so the route doesn't remount and drop the live
 * reply). That bypasses React Router, so `useLocation()` / `NavLink`'s
 * `isActive` lag behind the address bar. Anything that highlights based on the
 * current route should read this instead, so it matches the real URL.
 */
export function useUrlPath(): string {
  const location = useLocation()
  const [path, setPath] = useState(() =>
    typeof window === 'undefined' ? location.pathname : window.location.pathname
  )
  // Router navigations: re-sync from the (now-updated) window location.
  useEffect(() => {
    if (typeof window !== 'undefined') setPath(window.location.pathname)
  }, [location])
  // Manual history edits (replaceState) via the event bus.
  const sync = useCallback(() => {
    if (typeof window !== 'undefined') setPath(window.location.pathname)
  }, [])
  useOnUrlChange(sync)
  // Back/Forward.
  useEffect(() => {
    if (typeof window === 'undefined') return
    window.addEventListener('popstate', sync)
    return () => window.removeEventListener('popstate', sync)
  }, [sync])
  return path
}
