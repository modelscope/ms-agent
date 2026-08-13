import { useEffect, useState } from 'react'

// Flips to true once the app has hydrated on the client, and stays true for the
// rest of the page's lifetime. Module-level so that components mounted by later
// client-side navigations see `true` on their first render (no loading flash),
// while only the initial SSR page load observes the pre-hydration `false`.
let appHydrated = false

/**
 * Returns `false` during SSR and the first client render, then `true` after
 * hydration. Use it to gate rendering of subtrees that are not SSR-safe (e.g.
 * client-only markdown that parses differently on the server), so the server
 * HTML and the first client render match and no hydration mismatch occurs.
 */
export function useHydrated(): boolean {
  const [hydrated, setHydrated] = useState(appHydrated)

  useEffect(() => {
    appHydrated = true
    setHydrated(true)
  }, [])

  return hydrated
}
