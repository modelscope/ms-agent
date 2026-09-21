import { useEffect, useRef } from 'react'
import { useRevalidator } from 'react-router'
import {
  dispatchMcpSkillChanged,
  dispatchModelsChanged,
  dispatchProjectSettingsChanged,
  dispatchProjectsChanged,
  dispatchWorkspaceChanged
} from '~/lib/events'

/**
 * Server → client change stream.
 *
 * Opens one long-lived EventSource on GET /api/events per tab and refreshes the
 * affected lists whenever the backend reports a successful write. This is what
 * lets a change made OUTSIDE this tab — an external script hitting the REST API,
 * or another browser tab — reach the open page; the in-tab event bus in
 * `~/lib/events` only fires for mutations this tab performs itself.
 *
 * Mounted once at the app shell (root) so it covers both the app and settings
 * layouts with a single connection.
 */

// An external batch (e.g. a script installing several skills in a row) arrives
// as a burst of notices; coalesce them into one refresh.
const COALESCE_MS = 250

export function ServerEventsBridge() {
  const revalidator = useRevalidator()
  const revalidateRef = useRef(revalidator.revalidate)
  revalidateRef.current = revalidator.revalidate

  useEffect(() => {
    if (typeof window === 'undefined' || typeof EventSource === 'undefined')
      return
    let timer = 0
    const pendingPaths = new Set<string>()

    const flush = () => {
      const paths = [...pendingPaths]
      pendingPaths.clear()
      // Loader-backed lists (models, projects, sessions, global MCPs/skills,
      // agent/search settings) all refresh through one revalidate of the active
      // routes — `shouldRevalidate` lets a same-URL revalidate pass.
      revalidateRef.current()
      // Consumers that hold their own state instead of reading loader data
      // listen on the in-tab bus, so replay the matching in-tab event: an
      // external change then looks exactly like a local one to them.
      if (paths.some((p) => p.includes('/mcps') || p.includes('/skills')))
        dispatchMcpSkillChanged()
      // Providers and models both feed the model picker, which seeds its own
      // state from the loader and so never sees a bare revalidate.
      if (paths.some((p) => p.includes('/models') || p.includes('/providers')))
        dispatchModelsChanged()
      if (paths.some((p) => p.includes('/workspace'))) dispatchWorkspaceChanged()
      // Project create/rename/delete: loader-backed lists ride the revalidate
      // above, the Composer picker rides this. Excludes the nested settings
      // routes (/projects/:id/mcps …) already covered by their own events.
      if (paths.some((p) => /\/projects(\/[^/]+)?$/.test(p)))
        dispatchProjectsChanged()
      if (
        paths.some((p) =>
          /\/(memory|agent-settings|instructions|profile|search-settings)/.test(
            p
          )
        )
      )
        dispatchProjectSettingsChanged()
    }

    const onChange = (e: MessageEvent) => {
      try {
        const parsed = JSON.parse(e.data) as { path?: string }
        if (parsed?.path) pendingPaths.add(parsed.path)
      } catch {
        // Malformed frame — still refresh; a change definitely happened.
      }
      window.clearTimeout(timer)
      timer = window.setTimeout(flush, COALESCE_MS)
    }

    // EventSource reconnects on its own after a drop (honouring the server's
    // retry hint), so there is nothing to rebuild by hand — bind the handler and
    // close the connection on unmount.
    const es = new EventSource('/api/events')
    es.addEventListener('change', onChange)

    return () => {
      window.clearTimeout(timer)
      es.removeEventListener('change', onChange)
      es.close()
    }
  }, [])

  return null
}
