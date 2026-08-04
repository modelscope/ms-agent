/**
 * Lightweight cross-component event bus.
 *
 * Convention: when a component mutates data that OTHER mounted components
 * display (e.g. workspace files), it dispatches a named event here. Consumers
 * listen via the corresponding `useOn*` hook and refresh their local state.
 * This avoids global stores / prop drilling / React context for infrequent,
 * fire-and-forget sync.
 *
 * Adding a new sync need means adding a `dispatch*` + `useOn*` pair below —
 * keep the event name in the `msa:` namespace and document it at its
 * definition, so this file stays the single registry of cross-component events.
 */
import { useEffect } from 'react'

// ─── URL change (history.replaceState bypass) ───────────────────────────────

const URL_CHANGE = 'msa:urlchange'

/** Dispatch after a history.replaceState so route-bound UI (e.g. the sidebar
 * active highlight) re-reads the real URL. */
export function dispatchUrlChange() {
  if (typeof window !== 'undefined')
    window.dispatchEvent(new Event(URL_CHANGE))
}

/** Re-run `callback` when the address bar is updated via replaceState (bypasses
 * React Router, so useLocation won't fire). */
export function useOnUrlChange(callback: () => void) {
  useEffect(() => {
    if (typeof window === 'undefined') return
    window.addEventListener(URL_CHANGE, callback)
    return () => window.removeEventListener(URL_CHANGE, callback)
  }, [callback])
}

// ─── Workspace files ────────────────────────────────────────────────────────

/** Dispatch after any operation that changes workspace files from OUTSIDE the
 * consuming panel (e.g. NewProjectModal upload, chat-side file creation).
 * Panels that load their own file list (WorkspacePanel, SessionRightRail)
 * listen and re-fetch. `created` optionally carries paths known to exist NOW
 * (e.g. files a streaming turn just wrote) — listeners can merge them
 * optimistically instead of waiting for the refetch, so a freshly written
 * file never flashes as "deleted". */
export function dispatchWorkspaceChanged(created?: string[]) {
  if (typeof window !== 'undefined')
    window.dispatchEvent(
      new CustomEvent('msa:workspace-changed', { detail: { created } })
    )
}

/** Re-run `callback` whenever workspace files are changed by another component. */
export function useOnWorkspaceChanged(
  callback: (created?: string[]) => void
) {
  useEffect(() => {
    if (typeof window === 'undefined') return
    const handler = (e: Event) =>
      callback((e as CustomEvent<{ created?: string[] }>).detail?.created)
    window.addEventListener('msa:workspace-changed', handler)
    return () => window.removeEventListener('msa:workspace-changed', handler)
  }, [callback])
}

// ─── MCP / Skill configuration ─────────────────────────────────────────────

/** Dispatch after adding, removing, or toggling an MCP or Skill. Consumers
 * (e.g. the Composer pill counts) re-fetch their merged lists. */
export function dispatchMcpSkillChanged() {
  if (typeof window !== 'undefined')
    window.dispatchEvent(new Event('msa:mcp-skill-changed'))
}

/** Re-run `callback` whenever MCP/Skill config is changed by another component. */
export function useOnMcpSkillChanged(callback: () => void) {
  useEffect(() => {
    if (typeof window === 'undefined') return
    window.addEventListener('msa:mcp-skill-changed', callback)
    return () => window.removeEventListener('msa:mcp-skill-changed', callback)
  }, [callback])
}

// ─── Session turn completion ───────────────────────────────────────────

/** Dispatch when a session's agent turn completes (done frame received).
 * Lets PresenceProvider immediately clear the running spinner instead of
 * waiting for the next heartbeat poll. */
export function dispatchSessionDone(sessionId: string) {
  if (typeof window !== 'undefined')
    window.dispatchEvent(
      new CustomEvent('msa:session-done', { detail: sessionId })
    )
}

/** Listen for session-done events (payload = sessionId string). */
export function useOnSessionDone(callback: (sessionId: string) => void) {
  useEffect(() => {
    if (typeof window === 'undefined') return
    const handler = (e: Event) => callback((e as CustomEvent).detail)
    window.addEventListener('msa:session-done', handler)
    return () => window.removeEventListener('msa:session-done', handler)
  }, [callback])
}
