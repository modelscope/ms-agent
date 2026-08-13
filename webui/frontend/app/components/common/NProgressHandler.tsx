import { useEffect } from 'react'
import { useNavigation } from 'react-router'
import nprogress from 'nprogress'

import './NProgressHandler.css'

nprogress.configure({ showSpinner: false, trickleSpeed: 120 })

/**
 * Top loading bar driven by React Router navigation. While a client page
 * transition is pending (`navigation.location` is set) NProgress runs; it
 * completes when the new route commits. Styling lives in the co-located
 * NProgressHandler.css (design-token colors, no default NProgress blue).
 * Initial full-document loads aren't navigations, so the bar only appears on
 * in-app page switches. Start is DELAYED 150ms so a fast transition never
 * flashes the bar (nprogress.done() is a no-op when it never started).
 */
export function NProgressHandler() {
  const navigation = useNavigation()
  const isNavigating = Boolean(navigation.location)

  useEffect(() => {
    if (!isNavigating) return
    const t = setTimeout(() => nprogress.start(), 150)
    return () => {
      clearTimeout(t)
      nprogress.done()
    }
  }, [isNavigating])

  return null
}
