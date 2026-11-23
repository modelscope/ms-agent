import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router'
import { api } from '~/lib/api'
import type { Scope } from '~/lib/types'

/** Low-frequency checks belong to the open app, independent of the Skills page. */
export function SkillUpdateChecks() {
  const location = useLocation()
  const attempted = useRef(new Map<Scope, number>())
  const project = location.pathname.match(/^\/projects\/([^/]+)/)?.[1]
  const selectedScope = new URLSearchParams(location.search).get('scope')
  const scope: Scope = project
    ? `project:${decodeURIComponent(project)}`
    : selectedScope?.startsWith('project:')
      ? (selectedScope as Scope)
      : 'global'

  useEffect(() => {
    let disposed = false
    async function check() {
      if (document.visibilityState !== 'visible') return
      try {
        const settings = await api.skillManagementSettings()
        if (disposed || !settings.auto_check) return
        for (const target of new Set<Scope>(['global', scope])) {
          if (Date.now() - (attempted.current.get(target) ?? 0) < 60_000)
            continue
          attempted.current.set(target, Date.now())
          // The SDK owns the 24-hour TTL and source-level deduplication. SSE
          // reports completion; this component does not start a polling loop.
          await api.checkSkillUpdates(target, false)
          if (disposed) return
        }
      } catch {
        /* Background failures stay on the affected Skill cards. */
      }
    }
    const timer = setTimeout(check, 1500)
    document.addEventListener('visibilitychange', check)
    return () => {
      disposed = true
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', check)
    }
  }, [scope])
  return null
}
