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
  return fileSet.has(path)
}
