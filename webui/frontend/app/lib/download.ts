import { api } from './api'
import type { Dict } from './i18n'
import type { Session, WorkspaceFile } from './types'

/**
 * Unified workspace download logic. Single source of truth for every "download"
 * affordance in the app:
 *
 * - single file  -> fetch the raw bytes, then save them from memory.
 * - directory     -> ask the server for a zip of that subtree.
 * - whole workspace -> ask the server for a zip of everything.
 *
 * `downloadWorkspacePath` auto-detects file vs directory from the file listing,
 * so callers can wire one handler to a per-row action regardless of kind.
 *
 * Zipping used to happen here, with fflate over bytes fetched file by file.
 * That meant one request per file with no concurrency limit, and a memory peak
 * of every file's bytes AND the finished archive at once -- enough to lose the
 * tab on a large workspace. The server now streams the zip as it compresses it,
 * so this is a single request and only the archive is held.
 *
 * Every one of them goes through `fetch`, deliberately. Pointing an `<a
 * download>` straight at the raw or archive URL would avoid copying through
 * memory, but that request leaves the document: the browser's download stack
 * makes it, so it does not inherit the frame's cookie partition. Deployed
 * inside an iframe with partitioned cookies -- a gateway putting its token
 * there -- such a download arrives with no credentials and gets rejected, while
 * every fetch-based download here succeeds against the same URL. The in-memory
 * copy buys credentials that work, plus a response we can inspect, which is
 * what `assertRawResponse` needs.
 */

const basename = (path: string): string => path.split('/').pop() || path

/** Trigger a browser download of an in-memory Blob (revoking the URL after).
 * A blob URL is same-origin and never hits the network, so unlike a raw
 * endpoint URL it raises no credentials question (see the file header). */
function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noreferrer'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1_000)
}

/**
 * A raw-bytes request that came back with something other than file bytes
 * because it wasn't authorized — an auth gateway bouncing it to a login page,
 * or a session that expired mid-visit.
 *
 * Kept apart from a plain failure so the UI can point at the session instead of
 * saying "download failed", which sends the user hunting for a problem with the
 * file.
 */
export class DownloadUnauthorizedError extends Error {
  constructor(path: string) {
    super(`download not authorized: ${path}`)
    this.name = 'DownloadUnauthorizedError'
  }
}

/** True when the body is an HTML page nobody asked for. Real `.html` files in
 * the workspace are served as text/html too, so only an unexpected one gives
 * away a gateway's login page. */
function isUnexpectedHtml(res: Response, path: string): boolean {
  const ctype = res.headers.get('content-type') ?? ''
  if (!/^\s*text\/html\b/i.test(ctype)) return false
  return !/\.(html?|xhtml)$/i.test(path)
}

/**
 * Vet a raw-bytes response before its body is treated as file content.
 *
 * `res.ok` on its own isn't enough behind an auth gateway: an unauthorized
 * request gets redirected to a login page answering 200 text/html, and fetch
 * follows that silently — so the page would be saved, or zipped up, as if it
 * were the file. `redirected` is the tell, since the raw endpoint never
 * redirects on its own; the HTML check backs it up for gateways that rewrite
 * the response in place instead.
 */
function assertRawResponse(res: Response, path: string): void {
  if (res.status === 401 || res.status === 403) {
    throw new DownloadUnauthorizedError(path)
  }
  if (!res.ok) throw new Error(`download failed: ${path} (${res.status})`)
  if (res.redirected || isUnexpectedHtml(res, path)) {
    throw new DownloadUnauthorizedError(path)
  }
}

/**
 * A download target that holds no bytes: an empty folder, or one whose only
 * contents are hidden from the listing.
 *
 * Not a failure — there is simply nothing to put in a zip — so callers report
 * it as a notice in its own right rather than as a download that broke, which
 * would have the user retrying something that cannot succeed.
 */
export class DownloadEmptyError extends Error {
  constructor(path: string) {
    super(`nothing to download: ${path}`)
    this.name = 'DownloadEmptyError'
  }
}

/** Message for a download that actually failed. An auth bounce gets its own
 * wording, since "download failed" would have the user looking at the file
 * rather than at their expired session. (`DownloadEmptyError` is not a failure
 * and is handled by the caller, which reports it at notice level.) */
export function downloadErrorText(t: Dict, err: unknown): string {
  return err instanceof DownloadUnauthorizedError
    ? t.workspace.downloadUnauthorized
    : t.workspace.downloadFailed
}

/** Fetch one workspace file's raw bytes. `credentials` is spelled out because
 * in deployment this runs inside an iframe, where the cookie the gateway checks
 * is partitioned to the embedding page. */
async function fetchBytes(projectId: string, path: string): Promise<Uint8Array> {
  const res = await fetch(api.workspaceFileRawUrl(projectId, path), {
    credentials: 'include'
  })
  assertRawResponse(res, path)
  return new Uint8Array(await res.arrayBuffer())
}

/** Download a single file, keeping its name. */
export async function downloadWorkspaceFile(
  projectId: string,
  path: string
): Promise<void> {
  const bytes = await fetchBytes(projectId, path)
  saveBlob(new Blob([bytes as unknown as BlobPart]), basename(path))
}

/** Download a server-built zip of the workspace, or of the folder at `path`,
 * saving it as `zipName`. The archive arrives already assembled, so folder
 * entries are named by the server (a folder unpacks as itself, not as its
 * loose contents). */
async function downloadWorkspaceZip(
  projectId: string,
  zipName: string,
  path?: string
): Promise<void> {
  const url = api.workspaceArchiveUrl(projectId, path)
  const res = await fetch(url, { credentials: 'include' })
  // Same vetting as a raw file fetch: behind an auth gateway a bounced request
  // answers 200 with a login page, which would otherwise be saved as the .zip.
  // Vetted against the archive name, not the folder path: what's expected back
  // is always a zip, so any HTML at all gives the gateway away.
  assertRawResponse(res, zipName)
  saveBlob(await res.blob(), zipName)
}

export type SessionExportFormat = 'markdown' | 'html'
export type SessionExportDetail = 'full' | 'compact' | 'user-only'

function exportedFilename(res: Response, fallback: string): string {
  const disposition = res.headers.get('content-disposition') ?? ''
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  if (encoded) {
    try {
      return decodeURIComponent(encoded)
    } catch {
      // Fall through to the conservative local name for a malformed header.
    }
  }
  const plain = disposition.match(/filename="([^"\r\n]+)"/i)?.[1]
  return plain || fallback
}

function sessionExportFallbackName(
  session: Pick<Session, 'id' | 'title'>,
  format: SessionExportFormat
): string {
  const safeTitle = session.title
    .replace(/[\u0000-\u001f\u007f/\\:*?"<>|]+/g, '-')
    .trim()
    .slice(0, 96) || 'conversation'
  return `${safeTitle}-${session.id.slice(0, 8)}.${format === 'html' ? 'html' : 'md'}`
}

/** Download one immutable snapshot of the reconstructed conversation. The
 * request stays fetch-based so iframe deployments retain partitioned auth
 * cookies; a server-provided UTF-8 filename is preferred over the fallback. */
export async function downloadSessionExport(
  session: Pick<Session, 'id' | 'title'>,
  format: SessionExportFormat,
  detail: SessionExportDetail
): Promise<void> {
  const fallback = sessionExportFallbackName(session, format)
  const res = await fetch(api.sessionExportUrl(session.id, format, detail), {
    credentials: 'include'
  })
  if (res.status === 401 || res.status === 403 || res.redirected) {
    throw new DownloadUnauthorizedError(fallback)
  }
  if (!res.ok) throw new Error(`session export failed (${res.status})`)
  const disposition = res.headers.get('content-disposition') ?? ''
  if (!/\battachment\b/i.test(disposition)) {
    throw new Error('session export did not return an attachment')
  }
  saveBlob(await res.blob(), exportedFilename(res, fallback))
}

/** Whether a listing holds anything a download could contain. Folders carry no
 * bytes of their own, so a workspace of only (empty) ones would yield an empty
 * zip — callers check this to say so rather than letting the click do nothing. */
export function hasDownloadableFiles(files: WorkspaceFile[]): boolean {
  return files.some((f) => f.kind !== 'folder')
}

/** Download every file in the workspace as a single zip. */
export async function downloadWorkspaceAll(
  projectId: string,
  files: WorkspaceFile[],
  zipName = 'workspace.zip'
): Promise<void> {
  if (!hasDownloadableFiles(files)) return
  await downloadWorkspaceZip(projectId, zipName)
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
  const hasChildren = files.some(
    (f) => f.kind !== 'folder' && f.path.startsWith(prefix)
  )
  if (hasChildren) {
    // A directory: the server zips its subtree, keeping the folder as the root.
    await downloadWorkspaceZip(projectId, `${basename(clean)}.zip`, clean)
    return
  }
  // Nothing under it, so the target is either a file or an empty folder. Asking
  // the raw endpoint for a folder 404s (it only serves files), which would
  // surface as "download failed" — so an empty folder is reported for what it
  // is, matching what the download-all button says about the same situation.
  if (files.some((f) => f.path === clean && f.kind === 'folder')) {
    throw new DownloadEmptyError(clean)
  }
  await downloadWorkspaceFile(projectId, clean)
}
