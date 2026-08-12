import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState
} from 'react'
import { api } from '~/lib/api'
import { useOnWorkspaceChanged } from '~/lib/events'

/**
 * Live set of the project workspace's file paths, shared by the chat column.
 *
 * File step cards ("modified: x", "read: x") and user-bubble attachments show
 * a disabled "deleted" state when their file no longer exists. History replay
 * bakes an `exists` flag in, but that snapshot goes stale the moment the user
 * renames/deletes the file in the workspace rail. This provider keeps a fresh
 * path set: it re-fetches on every `msa:workspace-changed` event (fired by the
 * rail/project-page file operations and by mid-turn file writes), so cards
 * flip state immediately after a webui file operation.
 *
 * `null` = not loaded yet → consumers fall back to the server-baked flag.
 */
const WorkspaceFileSetContext = createContext<Set<string> | null>(null)

export function WorkspaceFilesProvider({
  projectId,
  children
}: {
  projectId: string | null
  children: React.ReactNode
}) {
  const [fileSet, setFileSet] = useState<Set<string> | null>(null)

  const reload = useCallback(() => {
    if (!projectId) {
      setFileSet(null)
      return
    }
    api
      .listWorkspaceFiles(projectId, { silent: true })
      .then((rows) => setFileSet(new Set(rows.map((r) => r.path))))
      .catch(() => {})
  }, [projectId])

  useEffect(() => {
    reload()
  }, [reload])
  // On a change event, optimistically merge any paths the dispatcher knows
  // exist NOW (e.g. files a streaming turn just wrote) so dependent cards
  // flip immediately, then refetch for the authoritative set.
  const onChanged = useCallback(
    (created?: string[]) => {
      if (created?.length) {
        setFileSet((prev) => {
          const next = new Set(prev ?? [])
          for (const p of created) if (p) next.add(p)
          return next
        })
      }
      reload()
    },
    [reload]
  )
  useOnWorkspaceChanged(onChanged)

  return (
    <WorkspaceFileSetContext.Provider value={fileSet}>
      {children}
    </WorkspaceFileSetContext.Provider>
  )
}

/** The current workspace path set, or null while unknown (no provider / not
 * loaded yet). */
export function useWorkspaceFileSet(): Set<string> | null {
  return useContext(WorkspaceFileSetContext)
}

/** Whether `path` currently exists in the workspace. Falls back to
 * `serverBaked` (the history-replay flag) while the live set is unknown. */
export function useFileExists(path: string, serverBaked: boolean): boolean {
  const fileSet = useWorkspaceFileSet()
  if (!path || fileSet === null) return serverBaked
  if (fileSet.has(path)) return true
  // Absence is NOT proof of deletion: the listing is a curated view, not a
  // full inventory — the backend deliberately hides framework internals
  // (`sessions/`, `.ms_agent/snapshots`, machine-format memory dumps). Every
  // such file the agent legitimately reads would otherwise render as
  // "deleted".
  //
  // Rather than mirror the backend's hide rules here (they would drift), only
  // let the set contradict the server for a directory it demonstrably
  // enumerated: if some sibling shares this path's parent, the directory is
  // covered and a missing entry really means gone.
  const slash = path.lastIndexOf('/')
  const parent = slash === -1 ? '' : path.slice(0, slash + 1)
  for (const known of fileSet) {
    if (known === path) continue
    const knownSlash = known.lastIndexOf('/')
    const knownParent = knownSlash === -1 ? '' : known.slice(0, knownSlash + 1)
    if (knownParent === parent) return false // directory covered → truly gone
  }
  return serverBaked
}
