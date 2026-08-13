import { useCallback, useSyncExternalStore } from 'react'

/**
 * Subscribe to a CSS media query in an SSR-safe way.
 *
 * Uses `useSyncExternalStore` so the real client value is read during the
 * hydration commit (before paint) rather than in a post-paint `useEffect`.
 * This removes the false→true flash the old `useState(false) + useEffect`
 * version caused on small screens, and avoids hydration mismatch warnings.
 *
 * The server render (and the hydration pass) returns `false` to match the
 * server-produced HTML; React then re-reads the live value synchronously on
 * the client and re-renders once with the correct result.
 */
export function useMatchMedia(query: string): boolean {
  const subscribe = useCallback(
    (onStoreChange: () => void) => {
      if (typeof window === 'undefined') return () => {}
      const mq = window.matchMedia(query)
      mq.addEventListener('change', onStoreChange)
      return () => mq.removeEventListener('change', onStoreChange)
    },
    [query]
  )

  const getSnapshot = () =>
    typeof window !== 'undefined' && window.matchMedia(query).matches

  const getServerSnapshot = () => false

  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}
