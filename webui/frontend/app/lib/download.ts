import { zip } from 'fflate'
import { api } from './api'
import type { WorkspaceFile } from './types'

/**
 * Unified workspace download logic. Single source of truth for every "download"
 * affordance in the app:
 *
 * - single file  -> stream the raw endpoint straight to the browser (no copy).
 * - directory     -> fetch every file under it and zip on the client.
 * - whole workspace -> zip everything.
 *
 * `downloadWorkspacePath` auto-detects file vs directory from the file listing,
 * so callers can wire one handler to a per-row action regardless of kind.
 */

const basename = (path: string): string => path.split('/').pop() || path

/** Trigger a browser "Save as" for `url`, keeping `filename`. Same-origin plus
 * the `download` attribute forces a download instead of navigating. */
function saveUrl(url: string, filename: string): void {
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noreferrer'
  document.body.appendChild(a)
  a.click()
  a.remove()
}

/** Trigger a browser download of an in-memory Blob (revoking the URL after). */
function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  saveUrl(url, filename)
  setTimeout(() => URL.revokeObjectURL(url), 1_000)
}

/** Fetch one workspace file's raw bytes. */
async function fetchBytes(projectId: string, path: string): Promise<Uint8Array> {
  const res = await fetch(api.workspaceFileRawUrl(projectId, path))
  if (!res.ok) throw new Error(`download failed: ${path} (${res.status})`)
  return new Uint8Array(await res.arrayBuffer())
}

/** Download a single file by streaming the raw endpoint, keeping its name. */
export function downloadWorkspaceFile(projectId: string, path: string): void {
  saveUrl(api.workspaceFileRawUrl(projectId, path), basename(path))
}

/** Zip the given files (by full workspace path) and download as `zipName`.
 * `stripPrefix` is removed from each entry name so a folder unpacks cleanly
 * (e.g. `src/utils/a.ts` under prefix `src/` becomes `utils/a.ts`). */
async function downloadWorkspaceZip(
  projectId: string,
  paths: string[],
  zipName: string,
  stripPrefix = ''
): Promise<void> {
  const entries: Record<string, Uint8Array> = {}
  await Promise.all(
    paths.map(async (p) => {
      const rel =
        stripPrefix && p.startsWith(stripPrefix)
          ? p.slice(stripPrefix.length)
          : p
      entries[rel || basename(p)] = await fetchBytes(projectId, p)
    })
  )
  const bytes = await new Promise<Uint8Array>((resolve, reject) => {
    zip(entries, { level: 6 }, (err, data) =>
      err ? reject(err) : resolve(data)
    )
  })
  saveBlob(
    new Blob([bytes as unknown as BlobPart], { type: 'application/zip' }),
    zipName
  )
}

/** Download every file in the workspace as a single zip. */
export async function downloadWorkspaceAll(
  projectId: string,
  files: WorkspaceFile[],
  zipName = 'workspace.zip'
): Promise<void> {
  const paths = files.filter((f) => f.kind !== 'folder').map((f) => f.path)
  if (paths.length === 0) return
  await downloadWorkspaceZip(projectId, paths, zipName)
}

/** Download a workspace path, auto-detecting file vs directory: a directory (a
 * path that is the prefix of other files) is zipped with the folder as the
 * zip's root; a single file downloads directly. `files` is the full listing. */
export async function downloadWorkspacePath(
  projectId: string,
  targetPath: string,
  files: WorkspaceFile[]
): Promise<void> {
  const clean = targetPath.replace(/\/+$/, '')
  const prefix = `${clean}/`
  const children = files.filter(
    (f) => f.kind !== 'folder' && f.path.startsWith(prefix)
  )
  if (children.length > 0) {
    // A directory: zip its subtree, keeping the folder itself as the zip root.
    const parent = clean.includes('/')
      ? clean.slice(0, clean.lastIndexOf('/') + 1)
      : ''
    await downloadWorkspaceZip(
      projectId,
      children.map((f) => f.path),
      `${basename(clean)}.zip`,
      parent
    )
    return
  }
  // A single file (or an empty folder — nothing to zip): download directly.
  downloadWorkspaceFile(projectId, clean)
}
