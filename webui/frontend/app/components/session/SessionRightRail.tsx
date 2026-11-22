import {
  App,
  Button,
  Dropdown,
  Input,
  Modal,
  Segmented,
  Splitter,
  Tooltip
} from 'antd'
import type { MenuProps, TreeDataNode } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { CodeEditor } from '~/components/common/CodeEditor'
import { EmptyState } from '~/components/common/EmptyState'
import { FolderTree } from '~/components/common/FolderTree'
import { HtmlPreview } from '~/components/common/HtmlPreview'
import { Markdown } from '~/components/common/Markdown'
import { docKindFor, languageFor } from '~/lib/editorLanguage'
import { extensionOf, mediaKindFor } from '~/lib/mediaKind'
import { makeRefResolver } from '~/lib/previewRefs'
import { ScrollArea } from '~/components/common/ScrollArea'
import { DeferredSkeleton } from '~/components/common/DeferredSkeleton'
import type { FolderTreeActions } from '~/components/common/FolderTree'
import { IconButton } from '~/components/common/IconButton'
import { api } from '~/lib/api'
import { dispatchWorkspaceChanged, useOnWorkspaceChanged } from '~/lib/events'
import { useSpin } from '~/lib/useSpin'
import { collectDroppedFiles } from '~/lib/dropFiles'
import { createWorkspaceEntry } from '~/lib/workspaceCreate'
import {
  downloadErrorText,
  downloadWorkspaceAll,
  downloadWorkspaceFile,
  hasDownloadableFiles
} from '~/lib/download'
import { useT } from '~/lib/i18n'
import type { Project, WorkspaceFile } from '~/lib/types'
import { MsaButton } from '../common/MsaButton'
import AddIcon from '~/assets/icons/add.svg?react'
import CloseIcon from '~/assets/icons/close.svg?react'
import RefreshIcon from '~/assets/icons/refresh.svg?react'
import SearchIcon from '~/assets/icons/search.svg?react'
import DownloadIcon from '~/assets/icons/download.svg?react'
import ViewIcon from '~/assets/icons/view.svg?react'
import TerminalIcon from '~/assets/icons/terminal.svg?react'
import DefaultFileIcon from '~/assets/files/default.svg?react'

interface Props {
  project: Project
  /** Unused: the workspace is project-scoped. Kept optional for callers. */
  sessionId?: string
  /**
   * Whether the workspace rail is currently open. The rail component stays
   * mounted (width-animated) while closed, so this drives a file-list refresh
   * on every open — the agent may have written files while it was hidden.
   * When omitted, the list loads once on mount (standalone use).
   */
  active?: boolean
  /**
   * External "open this file" request (e.g. a click on a file card in a chat
   * bubble). The rail selects `path` and previews it; `nonce` changes on every
   * request so re-clicking the same file re-triggers the selection.
   */
  openFile?: { path: string; nonce: number }
  /**
   * External "create an entry here" request (e.g. the project page's file
   * table, which opens this rail instead of asking for the name itself). Opens
   * the inline naming row inside `dir` ('' = workspace root); `nonce` changes
   * on every request so asking twice re-opens the row.
   */
  createEntry?: { dir: string; kind: 'file' | 'folder'; nonce: number }
  /**
   * Asked before a container closes this rail. The rail sets it to a function
   * that answers "I am holding this close back" — unsaved buffers get a prompt
   * instead of being thrown away. Only containers that DESTROY the rail on close
   * need to pass it; where it stays mounted, closing loses nothing.
   *
   * A ref rather than a callback prop, because the answer has to arrive
   * synchronously, inside the container's own close handler.
   */
  closeGuard?: RefObject<(() => boolean) | null>
  onClose?: () => void
}

interface DirNode {
  name: string
  full: string
  children: Map<string, DirNode>
  files: WorkspaceFile[]
}

function buildTree(files: WorkspaceFile[]): DirNode {
  const root: DirNode = {
    name: '',
    full: '',
    children: new Map(),
    files: []
  }
  for (const f of files) {
    const parts = f.path.split('/')
    const name = parts.pop()!
    let cur = root
    let acc = ''
    for (const p of parts) {
      acc = acc ? `${acc}/${p}` : p
      let child = cur.children.get(p)
      if (!child) {
        child = { name: p, full: acc, children: new Map(), files: [] }
        cur.children.set(p, child)
      }
      cur = child
    }
    // A folder entry becomes a DIRECTORY node — never a file leaf. Nested
    // paths already create their parents above, so this matters for folders
    // the listing reports explicitly (e.g. EMPTY ones like `.locks`): treating
    // them as files would render a file icon and let a click try to preview a
    // directory (which the backend rightly refuses to read/write).
    if (f.kind === 'folder') {
      const full = acc ? `${acc}/${name}` : name
      if (!cur.children.has(name)) {
        cur.children.set(name, {
          name,
          full,
          children: new Map(),
          files: []
        })
      }
      continue
    }
    cur.files.push({ ...f, path: name })
  }
  return root
}

function toTreeData(node: DirNode): TreeDataNode[] {
  const dirs = Array.from(node.children.values()).map((child) => ({
    key: `dir:${child.full}`,
    title: child.name,
    children: toTreeData(child)
  }))
  const files = node.files.map((f) => ({
    key: `file:${node.full ? node.full + '/' : ''}${f.path}`,
    title: f.path,
    isLeaf: true
  }))
  return [...dirs, ...files]
}

type PreviewKind = 'text' | 'image' | 'video' | 'audio' | 'unsupported'

const TEXT_EXTS = new Set([
  'txt',
  'md',
  'markdown',
  'json',
  'jsonl',
  'js',
  'mjs',
  'cjs',
  'ts',
  'mts',
  'tsx',
  'jsx',
  'py',
  'pyi',
  'html',
  'htm',
  'css',
  'scss',
  'less',
  'yml',
  'yaml',
  'xml',
  'sh',
  'bash',
  'zsh',
  'fish',
  'toml',
  'ini',
  'cfg',
  'conf',
  'env',
  'rs',
  'go',
  'java',
  'kt',
  'c',
  'cpp',
  'cc',
  'h',
  'hpp',
  'cs',
  'rb',
  'php',
  'sql',
  'vue',
  'svelte',
  'astro',
  'swift',
  'r',
  'lua',
  'dockerfile',
  'makefile',
  'cmake',
  'gradle',
  'tf',
  'hcl',
  'graphql',
  'proto',
  'csv',
  'tsv',
  'log',
  'diff',
  'patch',
  'ipynb'
])

// Decide how a file should be previewed based solely on its extension. This
// ensures that renaming a file (changing its extension) immediately changes
// the preview behavior without waiting for the server to re-classify.
function previewKindOf(file: WorkspaceFile): PreviewKind {
  // Directories are never previewable (the backend returns metadata only, and
  // writing one is rejected) — guard before any extension guessing.
  if (file.kind === 'folder') return 'unsupported'
  const media = mediaKindFor(file.path)
  if (media) return media
  const ext = extensionOf(file.path)
  if (TEXT_EXTS.has(ext)) return 'text'
  // Extensionless files (Dockerfile, Makefile, logging, dotfiles…) default
  // to plain-text preview.
  if (!ext) return 'text'
  // Fallback: if the backend managed to decode the file as UTF-8 text, show it.
  if (file.content != null) return 'text'
  return 'unsupported'
}

const baseName = (p: string) => p.split('/').pop() ?? p
const parentDir = (p: string) => {
  const i = p.lastIndexOf('/')
  return i === -1 ? '' : p.slice(0, i)
}
const joinPath = (dir: string, name: string) => (dir ? `${dir}/${name}` : name)

// How often the open file is re-read to notice a write nothing announced. Long
// enough that an open editor is not a source of traffic, short enough that the
// user is warned before they have typed a paragraph over someone else's work.
const OPEN_FILE_POLL_MS = 15_000

// Unsaved text for a file that is not the open one. `disk` is what the file held
// when the buffer was parked, which is what lets a later save tell an external
// write from its own. `changed` carries the "changed elsewhere" warning along
// with it: nothing on the way back can re-derive a warning that was ALREADY up.
interface ParkedBuffer {
  draft: string
  disk: string
  changed: boolean
}

export function SessionRightRail({
  project,
  sessionId: _sessionId,
  active,
  openFile,
  createEntry,
  closeGuard,
  onClose
}: Props) {
  const { t } = useT()
  const { message, modal } = App.useApp()
  const [files, setFiles] = useState<WorkspaceFile[] | null>(null)
  const [refreshing, spin] = useSpin()
  const [filter, setFilter] = useState('')
  // The entry being created: an inline row in the tree, named in place the way
  // an editor does it. null = nothing being created; '' is the workspace root,
  // so null and '' cannot be collapsed into one falsy check.
  const [newEntry, setNewEntry] = useState<{
    dir: string
    kind: 'file' | 'folder'
  } | null>(null)
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  // Mirrored into a ref for the same reason `diskContent` below is one: every
  // mutation here broadcasts synchronously (dispatchWorkspaceChanged), and the
  // listener that re-reads the open file runs BEFORE React has re-rendered. Read
  // as state there, the path is still the one the file had before the rename, so
  // the re-read asks for a path that no longer exists and 404s. Always go through
  // `putSelectedFile` so the two cannot drift.
  const selectedFileRef = useRef<string | null>(null)
  const selectionRevision = useRef(0)
  const putSelectedFile = (path: string | null) => {
    if (path === null) selectionRevision.current += 1
    selectedFileRef.current = path
    setSelectedFile(path)
  }
  const [fileContent, setFileContent] = useState<string | null>(null)
  // Live editor buffer; diverges from `fileContent` while the user edits.
  const [draft, setDraft] = useState('')
  const [fileLoading, setFileLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [previewKind, setPreviewKind] = useState<PreviewKind>('text')
  // Markdown/HTML files open rendered; 'code' is the editor behind that.
  const [viewMode, setViewMode] = useState<'preview' | 'code'>('preview')
  // The open file was written by someone else (the agent, another view) while
  // the buffer had unsaved edits, so neither version can be dropped silently.
  const [externalChanged, setExternalChanged] = useState(false)
  // Content the open file is known to hold ON DISK. A ref, not state: our own
  // save broadcasts synchronously, before React has re-rendered with the new
  // content, so a state read inside that listener would still see the old text
  // and mistake our own write for someone else's.
  const diskContent = useRef<string | null>(null)
  // Unsaved buffers of files the user navigated AWAY from. Clicking another file
  // parks the current one here instead of dropping it — an editor that loses what
  // you typed because you looked at a second file is an editor you cannot use.
  const [stash, setStash] = useState<Record<string, ParkedBuffer>>({})
  // The close the guard is holding back, shown as a list of what would be lost.
  const [unsavedPrompt, setUnsavedPrompt] = useState(false)
  const [savingAll, setSavingAll] = useState(false)
  // Set for the one close that follows the user's answer to that prompt, so the
  // guard doesn't ask again about a stash React has not re-rendered without yet.
  const skipGuard = useRef(false)
  const [downloadingAll, setDownloadingAll] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)

  const dirty = selectedFile !== null && draft !== (fileContent ?? '')

  // What the open file can be shown as, beyond its source.
  const docKind = selectedFile ? docKindFor(selectedFile) : null
  // An HTML preview is an iframe on the file's raw URL, so it shows what is ON
  // DISK — it has to reload whenever that changes, ours or anyone else's write.
  const [diskRevision, setDiskRevision] = useState(0)
  useEffect(() => setDiskRevision((n) => n + 1), [fileContent])
  // Relative references inside a rendered markdown file point at its neighbours
  // in the workspace, not at anything under the current route.
  const previewRefs = useMemo(
    () =>
      selectedFile
        ? makeRefResolver(selectedFile, (path) =>
            api.workspaceFileRawUrl(project.id, path)
          )
        : undefined,
    [project.id, selectedFile]
  )

  // Everything holding text that is not on disk: the parked buffers plus the open
  // one, if it has been edited.
  const unsavedPaths = useMemo(() => {
    const paths = Object.keys(stash)
    if (selectedFile && dirty) paths.push(selectedFile)
    return paths.sort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stash, selectedFile, dirty])
  const dirtyKeys = useMemo(
    () => unsavedPaths.map((p) => `file:${p}`),
    [unsavedPaths]
  )

  // Set webkitdirectory attribute via DOM (React doesn't support it natively)
  useEffect(() => {
    if (folderInputRef.current) {
      folderInputRef.current.setAttribute('webkitdirectory', '')
      folderInputRef.current.setAttribute('directory', '')
    }
  }, [])

  const loadFiles = () =>
    api
      .listWorkspaceFiles(project.id)
      .then(setFiles)
      .catch(() => setFiles([]))

  // A project switch must not flash the previous project's tree (or keep its
  // selected file) while the new list loads — reset to the loading placeholder
  // first. Reopening the same project keeps the last list visible during the
  // silent refresh.
  const prevProjectRef = useRef(project.id)
  useEffect(() => {
    if (prevProjectRef.current === project.id) return
    prevProjectRef.current = project.id
    setFiles(null)
    putSelectedFile(null)
    setFileContent(null)
    setDraft('')
    // Buffers are keyed by workspace-relative path, which means nothing in
    // another project's workspace.
    setStash({})
  }, [project.id])

  // Load on open (and on project change while open). The rail stays mounted at
  // width 0 when closed, so re-running here — rather than on mount — keeps the
  // list fresh each time it's reopened. When `active` is not provided, fall back
  // to a one-shot load on mount.
  useEffect(() => {
    if (active === undefined || active) loadFiles()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, project.id])

  // Re-read the OPEN file after someone else touched the workspace — on the
  // in-tab event below, on regaining focus, on a poll while it stays open, and
  // once more right before a save. Defined before the listener, which lists it as
  // a dependency.
  //
  // Three outcomes: unchanged on disk (the common one — the event was about
  // other files, or it was our own save), changed while the buffer is clean
  // (adopt it, no one loses anything), changed while the buffer is dirty (say so
  // and let the user pick — overwriting their edits, or dropping them, are both
  // decisions that aren't ours to make).
  const syncOpenFile = useCallback(async () => {
    // Non-text previews (image, video, …) hold no buffer to conflict with, and
    // their <img>/<video> src re-reads on its own.
    const path = selectedFileRef.current
    if (!path || previewKind !== 'text') return
    if (diskContent.current === null) return
    let latest: string
    try {
      const f = await api.getWorkspaceFile(project.id, path)
      if (previewKindOf(f) !== 'text') return
      latest = f.content ?? f.preview ?? ''
    } catch {
      // Gone or unreadable now — the list refresh is the honest signal for that;
      // don't blame the editor for it.
      return
    }
    // The open file changed while this was in flight (the user clicked another
    // one, or a move landed): this text belongs to a file no longer on screen.
    if (selectedFileRef.current !== path) return
    if (latest === diskContent.current) return
    diskContent.current = latest
    if (dirty) {
      setExternalChanged(true)
      return
    }
    setFileContent(latest)
    setDraft(latest)
    // The path comes from the ref above, not from `selectedFile`, so this does
    // not need to be rebuilt when the selection changes.
  }, [project.id, previewKind, dirty])

  // Cross-component sync: another view (e.g. project-edit modal) uploaded files.
  // Wrapped so the reload also re-reads the open file, and so the event's
  // optional `created` paths payload isn't forwarded on as an argument.
  const reloadOnChange = useCallback(() => {
    loadFiles()
    void syncOpenFile()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadFiles, syncOpenFile])
  useOnWorkspaceChanged(reloadOnChange)

  // That event bus only carries writes made in THIS tab. Regaining focus is the
  // cheapest moment to notice all the others — a second tab, a turn that kept
  // running while this one was hidden, an edit made outside the browser entirely.
  // One listing fetch per focus, the same one the refresh button does.
  useEffect(() => {
    if (active === false) return
    const check = () => {
      if (document.visibilityState !== 'visible') return
      loadFiles()
      void syncOpenFile()
    }
    window.addEventListener('focus', check)
    document.addEventListener('visibilitychange', check)
    return () => {
      window.removeEventListener('focus', check)
      document.removeEventListener('visibilitychange', check)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, syncOpenFile])

  // Focus alone still leaves one case silent: the window never lost focus, and
  // the writer is outside this tab (a turn streaming into another tab, an editor
  // on the same machine). Only a poll can make the badge appear on its own.
  //
  // Deliberately narrow, so this is one small request per interval rather than
  // background traffic: only while a TEXT file is open in a visible tab, only
  // that one file (not the listing), and stopped the moment the file is closed.
  useEffect(() => {
    if (active === false || !selectedFile || previewKind !== 'text') return
    const id = window.setInterval(() => {
      if (document.visibilityState !== 'visible') return
      void syncOpenFile()
    }, OPEN_FILE_POLL_MS)
    return () => window.clearInterval(id)
  }, [active, selectedFile, previewKind, syncOpenFile])

  // Zip the whole workspace and download it as `<project>.zip`.
  const handleDownloadAll = async () => {
    if (!files || files.length === 0) return
    // A listing of only (empty) folders has no bytes to zip, and the button
    // stays enabled for it — say so instead of letting the click do nothing.
    if (!hasDownloadableFiles(files)) {
      message.warning(t.workspace.downloadEmpty)
      return
    }
    setDownloadingAll(true)
    try {
      await downloadWorkspaceAll(
        project.id,
        files,
        `${project.name || 'workspace'}.zip`
      )
    } catch (err) {
      message.error(downloadErrorText(t, err))
    } finally {
      setDownloadingAll(false)
    }
  }

  const handleUpload = async (fileList: FileList | null, dir = '') => {
    if (!fileList || fileList.length === 0) return
    // Multipart upload preserves raw bytes, so binary files (images, archives,
    // …) aren't corrupted by UTF-8 coercion the way `file.text()` would.
    const uploads = Array.from(fileList).map((file) =>
      api
        .uploadWorkspaceFile(
          project.id,
          file,
          joinPath(dir, file.webkitRelativePath || file.name),
          { silent: [409] }
        )
        .catch(() => {})
    )
    await Promise.all(uploads)
    dispatchWorkspaceChanged()
  }

  // Folder the next OS file picker should upload into. The two hidden inputs are
  // shared by the Add-file menu (root) and a folder's context menu, and a picker
  // reports back through its own onChange — so the target has to be parked
  // somewhere in between.
  const uploadDirRef = useRef('')
  const pickUpload = (dir: string, kind: 'file' | 'folder') => {
    uploadDirRef.current = dir
    const input = kind === 'file' ? fileInputRef : folderInputRef
    input.current?.click()
  }

  const addMenu: MenuProps = {
    items: [
      // First, before the uploads: creating an empty entry needs nothing from the
      // user's disk. Like the uploads below them, both land at the workspace
      // root — the tree's own context menu is what targets a specific folder.
      {
        key: 'new-file',
        label: t.workspace.newFile,
        onClick: () => startNewEntry('', 'file')
      },
      {
        key: 'new-folder',
        label: t.workspace.newFolder,
        onClick: () => startNewEntry('', 'folder')
      },
      // Made here vs. taken from the user's disk: two different errands.
      { type: 'divider' },
      {
        key: 'upload-file',
        label: t.workspace.uploadFile,
        onClick: () => pickUpload('', 'file')
      },
      {
        key: 'upload-folder',
        label: t.workspace.uploadFolder,
        onClick: () => pickUpload('', 'folder')
      }
    ]
  }

  const treeData = useMemo(
    () => (files ? toTreeData(buildTree(files)) : []),
    [files]
  )

  // Load `path` into the editor. `restore` is a buffer parked for it earlier,
  // which goes back on top of the file's content so the user's edits survive the
  // round trip through another file.
  const loadPath = (path: string, restore: ParkedBuffer | null) => {
    putSelectedFile(path)
    const revision = ++selectionRevision.current
    setFileContent(null)
    setDraft('')
    setPreviewKind('text')
    setViewMode('preview')
    setExternalChanged(false)
    diskContent.current = null
    setFileLoading(true)
    api
      .getWorkspaceFile(project.id, path)
      .then((f) => {
        // A later selection owns the editor, even if it returned to this path.
        if (selectionRevision.current !== revision) return
        const kind = previewKindOf(f)
        setPreviewKind(kind)
        if (kind === 'text') {
          const content = f.content ?? f.preview ?? ''
          setFileContent(content)
          setDraft(restore ? restore.draft : content)
          diskContent.current = content
          // The badge means "this draft no longer sits on top of what is on disk",
          // which stays true across a trip through another file — whether it was
          // already up when the buffer was parked, or the file moved on while it
          // sat there. `disk !== content` alone covers only the second case: this
          // line adopts the latest content as the new base, so the next park would
          // record "same as disk" and the warning would silently vanish on the
          // second visit. It stops mattering once the draft matches disk again —
          // then there is nothing left to overwrite.
          if (
            restore &&
            restore.draft !== content &&
            (restore.changed || restore.disk !== content)
          )
            setExternalChanged(true)
        }
      })
      .catch(() => {
        if (selectionRevision.current !== revision) return
        setPreviewKind('text')
        setFileContent('')
        setDraft('')
      })
      .finally(() => {
        if (selectionRevision.current === revision) setFileLoading(false)
      })
  }

  // Open a file the user picked. The buffer being left is parked rather than
  // dropped, and the one parked for `path` comes back with it. Both sides of that
  // swap are computed here, in one pass over the current stash: an entry parked
  // through `setStash` would not be readable until the next render.
  const selectPath = (path: string) => {
    // Already open: re-reading it would be the one click that discards a buffer.
    if (path === selectedFile) return
    const next = { ...stash }
    const parked = next[path] ?? null
    delete next[path]
    if (selectedFile && previewKind === 'text') {
      if (draft !== (fileContent ?? ''))
        next[selectedFile] = {
          draft,
          // `diskContent`, not `fileContent`: after an external write the latter
          // is still the text the draft was based on, while the former is what
          // the file actually holds — the value a later save has to compare, so
          // that saving a parked buffer behaves exactly like saving the open one.
          disk: diskContent.current ?? fileContent ?? '',
          changed: externalChanged
        }
      else delete next[selectedFile]
    }
    setStash(next)
    loadPath(path, parked)
  }

  // Forget the buffers of a deleted path (a buffer keyed to a file that no longer
  // exists would be offered for saving and fail), or carry them to where the file
  // moved. `dest === null` = deleted. Folders take their children's buffers with
  // them either way.
  const remapStash = (src: string, dest: string | null) =>
    setStash((prev) => {
      const next: Record<string, ParkedBuffer> = {}
      for (const [p, buf] of Object.entries(prev)) {
        if (p !== src && !p.startsWith(`${src}/`)) next[p] = buf
        else if (dest !== null) next[dest + p.slice(src.length)] = buf
      }
      return next
    })

  const handleSelect = (key: string) => {
    if (!key.startsWith('file:')) return
    selectPath(key.slice(5))
  }

  // ---- File-management actions (context menu + drag & drop) ----

  // Open the inline naming row. The filter is cleared first: the row lives
  // inside the tree, and a filter in force could have pruned away the very
  // folder it belongs to.
  const startNewEntry = (dir: string, kind: 'file' | 'folder') => {
    setFilter('')
    setNewEntry({ dir, kind })
  }

  const commitNewEntry = async (name: string) => {
    if (!newEntry) return
    const { dir, kind } = newEntry
    // Close the row first: the creation is the user's answer to it, and leaving
    // it open would invite a second Enter on the same name.
    setNewEntry(null)
    const res = await createWorkspaceEntry({
      projectId: project.id,
      dir,
      name,
      kind,
      existingPaths: (files ?? []).map((f) => f.path)
    })
    if (!res.ok) {
      message.error(
        res.reason === 'exists'
          ? t.workspace.nameExists
          : res.reason === 'invalid'
            ? t.workspace.nameInvalid
            : t.workspace.createFailed
      )
      return
    }
    // Open the new file in the editor, as creating one in an editor does.
    if (kind === 'file') selectPath(res.path)
  }

  // Rewrite the open file's path when it (or its parent folder) is moved/renamed
  // so the editor keeps pointing at the same file after the tree refreshes.
  const remapSelected = (src: string, dest: string) => {
    // Read through the ref: `moveMany` calls this once per move, and each call
    // has to see the previous one's result rather than the same pre-batch state.
    const cur = selectedFileRef.current
    if (cur === src) putSelectedFile(dest)
    else if (cur?.startsWith(`${src}/`))
      putSelectedFile(dest + cur.slice(src.length))
  }

  const moveEntry = async (src: string, dest: string) => {
    try {
      await api.moveWorkspaceFile(project.id, src, dest)
      remapSelected(src, dest)
      remapStash(src, dest)
      dispatchWorkspaceChanged()
    } catch {
      message.error(t.workspace.moveFailed)
    }
  }

  // Inline rename commit: `newName` is the new base name typed in the tree.
  const renameTo = async (path: string, newName: string) => {
    const dest = joinPath(parentDir(path), newName)
    if (dest === path) return
    try {
      await api.moveWorkspaceFile(project.id, path, dest)
      remapSelected(path, dest)
      remapStash(path, dest)
      dispatchWorkspaceChanged()
    } catch {
      message.error(t.workspace.renameFailed)
    }
  }

  const deleteEntry = (path: string, isDir: boolean) =>
    modal.confirm({
      title: `${t.workspace.deleteConfirm} ${
        isDir ? t.workspace.folderLabel : t.workspace.fileLabel
      } “${baseName(path)}”？`,
      okText: t.workspace.delete,
      okButtonProps: { danger: true },
      cancelText: t.workspace.cancel,
      onOk: async () => {
        try {
          await api.deleteWorkspaceFile(project.id, path)
          remapStash(path, null)
          const cur = selectedFileRef.current
          if (cur === path || cur?.startsWith(`${path}/`)) {
            putSelectedFile(null)
            setFileContent(null)
            setDraft('')
          }
          dispatchWorkspaceChanged()
        } catch {
          message.error(t.workspace.saveFailed)
        }
      }
    })

  const copyPath = async (path: string) => {
    try {
      await navigator.clipboard.writeText(path)
      message.success(t.workspace.pathCopied)
    } catch {
      /* clipboard blocked (insecure context) — ignore */
    }
  }

  const uploadTo = async (dir: string, fileList: FileList) => {
    await uploadEntries(
      dir,
      Array.from(fileList).map((file) => ({
        file,
        path: file.webkitRelativePath || file.name
      }))
    )
  }

  /** Upload files that already know their relative path — what a folder pick
   * (webkitRelativePath) or a folder DROP (walked entry tree) both produce, so a
   * dropped directory lands as its real contents instead of one unreadable
   * directory "file". */
  const uploadEntries = async (
    dir: string,
    entries: { file: File; path: string }[]
  ) => {
    if (entries.length === 0) return
    const uploads = entries.map(({ file, path }) =>
      api
        .uploadWorkspaceFile(project.id, file, joinPath(dir, path), {
          silent: [409]
        })
        .catch(() => {})
    )
    await Promise.all(uploads)
    dispatchWorkspaceChanged()
  }

  // ---- Batch actions (multi-selection) ----

  const clearSelectedIfUnder = (paths: string[]) => {
    const cur = selectedFileRef.current
    if (cur && paths.some((p) => cur === p || cur.startsWith(`${p}/`))) {
      putSelectedFile(null)
      setFileContent(null)
      setDraft('')
    }
  }

  const deleteMany = (items: { path: string; isDir: boolean }[]) =>
    modal.confirm({
      title: `${t.workspace.deleteConfirm} ${items.length} ${t.workspace.selectedItems}？`,
      okText: t.workspace.delete,
      okButtonProps: { danger: true },
      cancelText: t.workspace.cancel,
      onOk: async () => {
        try {
          await Promise.all(
            items.map((it) =>
              api.deleteWorkspaceFile(project.id, it.path).catch(() => {})
            )
          )
          clearSelectedIfUnder(items.map((it) => it.path))
          for (const it of items) remapStash(it.path, null)
          dispatchWorkspaceChanged()
        } catch {
          message.error(t.workspace.saveFailed)
        }
      }
    })

  // Every download fetches its bytes, so failures are ours to report (see
  // lib/download.ts) — an unhandled rejection would otherwise leave the click
  // looking like it did nothing.
  const downloadOne = async (path: string) => {
    try {
      await downloadWorkspaceFile(project.id, path)
    } catch (err) {
      message.error(downloadErrorText(t, err))
    }
  }

  const downloadMany = async (paths: string[]) => {
    // Folders can't be streamed as a single file; caller passes files only.
    try {
      await Promise.all(paths.map((p) => downloadWorkspaceFile(project.id, p)))
    } catch (err) {
      message.error(downloadErrorText(t, err))
    }
  }

  const copyPaths = async (paths: string[]) => {
    try {
      await navigator.clipboard.writeText(paths.join('\n'))
      message.success(t.workspace.pathCopied)
    } catch {
      /* clipboard blocked (insecure context) — ignore */
    }
  }

  const moveMany = async (moves: { src: string; dest: string }[]) => {
    if (moves.length === 0) return
    try {
      await Promise.all(
        moves.map((m) =>
          api.moveWorkspaceFile(project.id, m.src, m.dest).catch(() => {})
        )
      )
      for (const m of moves) remapSelected(m.src, m.dest)
      for (const m of moves) remapStash(m.src, m.dest)
      dispatchWorkspaceChanged()
    } catch {
      message.error(t.workspace.moveFailed)
    }
  }

  const treeActions: FolderTreeActions = {
    onNewFile: (dir) => startNewEntry(dir, 'file'),
    onNewFolder: (dir) => startNewEntry(dir, 'folder'),
    onUploadFiles: (dir) => pickUpload(dir, 'file'),
    onUploadFolder: (dir) => pickUpload(dir, 'folder'),
    onRename: renameTo,
    onDelete: deleteEntry,
    onCopyPath: copyPath,
    onDownload: downloadOne,
    onMove: moveEntry,
    onUploadTo: uploadEntries,
    onDeleteMany: deleteMany,
    onDownloadMany: downloadMany,
    onCopyPaths: copyPaths,
    onMoveMany: moveMany
  }

  // An external request (e.g. clicking a file card in a chat bubble) opens the
  // rail and selects that path. Keyed by nonce so re-clicking the same file
  // after closing re-selects it. `loadFiles` refreshes the tree so a freshly
  // written file is highlighted.
  useEffect(() => {
    if (!openFile) return
    loadFiles()
    selectPath(openFile.path)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openFile?.nonce])

  // Same, for a create request. No `loadFiles` here: the request arrives as the
  // rail mounts, which loads the list anyway, and the row is held in state — it
  // appears with the tree once that list is in.
  useEffect(() => {
    if (!createEntry) return
    startNewEntry(createEntry.dir, createEntry.kind)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [createEntry?.nonce])

  // Write one buffer to disk, refusing to flatten a change that landed after that
  // buffer was read. `knownDisk` is what the file held then; null = unknown, so
  // there is nothing to compare and the write goes ahead.
  //
  // Shared by the open file and the parked ones, so "save" means the same thing
  // whichever of them is being written.
  const writeBuffer = async (
    path: string,
    text: string,
    knownDisk: string | null
  ): Promise<
    | { status: 'saved'; file: WorkspaceFile }
    | { status: 'conflict'; latest: string }
    | { status: 'failed' }
  > => {
    if (knownDisk !== null) {
      let latest: string | null = null
      try {
        const f = await api.getWorkspaceFile(project.id, path)
        if (previewKindOf(f) === 'text') latest = f.content ?? f.preview ?? ''
      } catch {
        // Unreadable right now — let the PUT below be the one to report it.
      }
      if (latest !== null && latest !== knownDisk)
        return { status: 'conflict', latest }
    }
    try {
      return {
        status: 'saved',
        file: await api.putWorkspaceFile(project.id, path, text)
      }
    } catch {
      return { status: 'failed' }
    }
  }

  // Write the OPEN file. False = nothing was written: the file changed underneath
  // (recorded so a second press overwrites deliberately), or the request failed.
  // `quiet` is for the save-all below, which reports once for the whole batch
  // instead of per file.
  const saveSelected = async (quiet = false): Promise<boolean> => {
    if (!selectedFile) return false
    const res = await writeBuffer(selectedFile, draft, diskContent.current)
    if (res.status === 'conflict') {
      diskContent.current = res.latest
      setExternalChanged(true)
      if (!quiet) message.warning(t.workspace.saveConflict)
      return false
    }
    if (res.status === 'failed') {
      if (!quiet) message.error(t.workspace.saveFailed)
      return false
    }
    setFileContent(draft)
    // Our text is now the file's text — recorded before the broadcast below,
    // whose listener runs synchronously and would otherwise read this write as
    // someone else's. Also settles a pending conflict: the user chose to
    // overwrite.
    diskContent.current = draft
    setExternalChanged(false)
    // Reflect updated size / mtime in the tree metadata.
    setFiles((prev) =>
      prev
        ? prev.map((f) =>
            f.path === res.file.path ? { ...f, ...res.file } : f
          )
        : prev
    )
    // An edit changes no path, but it does change what other views SHOW about
    // the file — its size, its modified time, and the project page's "last
    // edited" line. The merge above only fixes this tree; every other listener
    // would keep the numbers it read before the save.
    dispatchWorkspaceChanged()
    return true
  }

  const saveFile = async () => {
    if (!selectedFile || !dirty || saving) return
    setSaving(true)
    try {
      await saveSelected()
    } finally {
      setSaving(false)
    }
  }

  // Write every unsaved buffer, the open one included. Returns the paths that were
  // NOT written; those keep their buffer, so a failed save never costs the user
  // what they typed. A conflicted buffer records the newer disk content, which
  // makes a second attempt the deliberate overwrite.
  const saveAllUnsaved = async (): Promise<string[]> => {
    const rejected: string[] = []
    const written: string[] = []
    const conflicts: Record<string, string> = {}
    for (const [path, buf] of Object.entries(stash)) {
      const res = await writeBuffer(path, buf.draft, buf.disk)
      if (res.status === 'saved') written.push(path)
      else {
        if (res.status === 'conflict') conflicts[path] = res.latest
        rejected.push(path)
      }
    }
    if (written.length > 0 || Object.keys(conflicts).length > 0)
      setStash((prev) => {
        const next = { ...prev }
        for (const p of written) delete next[p]
        for (const [p, latest] of Object.entries(conflicts))
          if (next[p]) next[p] = { ...next[p], disk: latest, changed: true }
        return next
      })
    if (written.length > 0) dispatchWorkspaceChanged()
    if (selectedFile && dirty && !(await saveSelected(true)))
      rejected.push(selectedFile)
    return rejected
  }

  const selectedLanguage = selectedFile ? languageFor(selectedFile) : ''

  // Drop the buffer and take what's on disk. Confirmed, because the edits being
  // discarded are the user's and nothing else holds a copy of them. Goes straight
  // to `loadPath`: `selectPath` would park this buffer and hand it right back.
  const reloadOpenFile = () => {
    if (!selectedFile) return
    modal.confirm({
      title: t.workspace.reloadConfirm,
      okText: t.workspace.reload,
      cancelText: t.workspace.cancel,
      onOk: () => loadPath(selectedFile, null)
    })
  }

  // ---- Unsaved buffers vs. closing the rail ----

  // Answer the container's "may I close?". Registered only when one asks, which
  // is the same as saying: only where closing would destroy these buffers.
  useEffect(() => {
    if (!closeGuard) return
    closeGuard.current = () => {
      if (skipGuard.current) {
        skipGuard.current = false
        return false
      }
      if (unsavedPaths.length === 0) return false
      setUnsavedPrompt(true)
      return true
    }
    return () => {
      closeGuard.current = null
    }
  }, [closeGuard, unsavedPaths])

  // Close for real. The prompt below IS the answer the guard would ask for, and
  // the state that answers it (an emptied stash) has not re-rendered yet — so the
  // guard is told to stand down for this one close.
  const closeAnyway = () => {
    skipGuard.current = true
    setUnsavedPrompt(false)
    onClose?.()
  }

  const discardAllAndClose = () => {
    setStash({})
    // The open file's buffer is state rather than a stash entry: put it back to
    // the file's content so nothing is left to park on the way out.
    setDraft(fileContent ?? '')
    setExternalChanged(false)
    closeAnyway()
  }

  const saveAllAndClose = async () => {
    setSavingAll(true)
    try {
      const rejected = await saveAllUnsaved()
      // Something refused to be written — closing now would throw away exactly
      // the buffers this prompt exists to protect. Stay open, still listing them.
      if (rejected.length > 0) {
        message.warning(`${t.workspace.saveSomeFailed}${rejected.join(', ')}`)
        return
      }
      closeAnyway()
    } finally {
      setSavingAll(false)
    }
  }

  // Cmd/Ctrl+S saves the open file (falls through to the browser otherwise).
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === 's' || e.key === 'S')) {
        if (!selectedFile) return
        e.preventDefault()
        void saveFile()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedFile, dirty, saving, draft])

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Hidden file inputs (see `pickUpload` for how they learn their target
          folder) */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => {
          handleUpload(e.target.files, uploadDirRef.current)
          e.target.value = ''
        }}
      />
      <input
        ref={folderInputRef}
        type="file"
        className="hidden"
        onChange={(e) => {
          handleUpload(e.target.files, uploadDirRef.current)
          e.target.value = ''
        }}
      />

      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-msa-line-1 px-[20px] py-[16px]">
        <div className="flex items-center gap-1.5">
          <h3 className="text-base font-semibold text-msa-text-1 m-0">
            {t.session.workspaceTitle}
          </h3>
          <Tooltip title={t.workspace.refresh}>
            <IconButton
              icon={
                <RefreshIcon
                  className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`}
                />
              }
              variant="ghost"
              size="sm"
              disabled={refreshing}
              onClick={() => spin(loadFiles)}
            />
          </Tooltip>
        </div>
        {onClose && (
          <IconButton
            icon={<CloseIcon className="h-4 w-4" />}
            variant="tonal"
            size="sm"
            className="!h-7 !w-7 !rounded-[12px]"
            onClick={onClose}
          />
        )}
      </div>

      {/* Body */}
      {files !== null && files.length === 0 && !newEntry ? (
        /* Empty state: no split, full width. Once a name is being typed the tree
           takes over — that row has to be somewhere. */
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <EmptyState
            description={t.workspace.empty}
            action={
              <Dropdown menu={addMenu} trigger={['hover']}>
                <MsaButton
                  variant="primary"
                  icon={<AddIcon className="h-5 w-5" />}
                >
                  {t.workspace.addFile}
                </MsaButton>
              </Dropdown>
            }
          />
        </div>
      ) : (
        /* Tree + editor side by side, with a draggable splitter between them */
        <Splitter className="min-h-0 flex-1">
          {/* Left: file tree + footer */}
          <Splitter.Panel defaultSize={230} min={180} max="60%">
            <div className="flex h-full min-h-0 flex-col">
              <div className="shrink-0 px-2 pt-2 pb-1">
                <Input
                  allowClear
                  variant="borderless"
                  prefix={
                    <SearchIcon className="mr-1 h-5 w-5 text-msa-text-3" />
                  }
                  placeholder={t.workspace.searchPlaceholder}
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  className="rounded-lg h-8 bg-msa-fill-2 px-1.5 py-1"
                />
              </div>
              <ScrollArea
                pad={12}
                className="min-h-0 flex-1 py-1"
                // pad: keeps the selected tree-row highlight's left/right insets
                // equal whether or not the scrollbar takes space.
                onDragOver={(e) => {
                  // Native OS file drag over empty tree area -> upload to root.
                  // Folder nodes handle (and stop) their own drops.
                  if (e.dataTransfer.types.includes('Files')) e.preventDefault()
                }}
                onDrop={async (e) => {
                  if (!e.dataTransfer.types.includes('Files')) return
                  e.preventDefault()
                  // Walk the entry tree: a dropped FOLDER is not in
                  // `dataTransfer.files` (it appears there as an unreadable
                  // directory entry), so it used to upload as a 96 B junk file.
                  uploadEntries('', await collectDroppedFiles(e.dataTransfer))
                }}
              >
                {files === null ? (
                  <DeferredSkeleton rows={6} />
                ) : (
                  <FolderTree
                    treeData={treeData}
                    selectedKey={selectedFile ? `file:${selectedFile}` : ''}
                    dirtyKeys={dirtyKeys}
                    onSelect={handleSelect}
                    filter={filter}
                    actions={treeActions}
                    draft={newEntry}
                    onDraftCommit={commitNewEntry}
                    onDraftCancel={() => setNewEntry(null)}
                  />
                )}
              </ScrollArea>
              {/* Footer: download + add, inside left panel */}
              <div className="flex shrink-0 items-stretch border-t border-msa-line-1">
                <Button
                  type="text"
                  size="small"
                  icon={<DownloadIcon className="h-5 w-5" />}
                  loading={downloadingAll}
                  disabled={!files || files.length === 0}
                  onClick={handleDownloadAll}
                  className="h-10 flex-1 !rounded-none !text-msa-text-2"
                >
                  {t.workspace.downloadAll}
                </Button>
                <div className="w-px bg-msa-line-1" />
                <Dropdown menu={addMenu} trigger={['hover']}>
                  <Button
                    type="text"
                    size="small"
                    icon={<AddIcon className="h-5 w-5" />}
                    className="h-10 flex-1 !rounded-none !text-msa-text-2"
                  >
                    {t.workspace.addFile}
                  </Button>
                </Dropdown>
              </div>
            </div>
          </Splitter.Panel>

          {/* Right: file content */}
          <Splitter.Panel>
            <div className="flex h-full min-h-0 min-w-0 flex-col">
              {selectedFile ? (
                <>
                  {/* Editor toolbar: file path + download (all file types) */}
                  <div className="flex shrink-0 items-center justify-between gap-2 border-b border-msa-line-1 px-4 py-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <span
                        className="truncate text-sm text-msa-text-2"
                        title={selectedFile}
                      >
                        {selectedFile}
                        {previewKind === 'text' && dirty && (
                          <span className="ml-1 text-msa-text-3">•</span>
                        )}
                      </span>
                      {previewKind === 'text' && externalChanged && (
                        <Tooltip title={t.workspace.externalChangedHint}>
                          <button
                            type="button"
                            onClick={reloadOpenFile}
                            className="shrink-0 cursor-pointer rounded-full border-none bg-msa-fill-warning px-2 py-0.5 text-xs text-msa-text-2"
                          >
                            {t.workspace.externalChanged}
                          </button>
                        </Tooltip>
                      )}
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {previewKind === 'text' && docKind && (
                        <Segmented<'preview' | 'code'>
                          size="small"
                          value={viewMode}
                          onChange={setViewMode}
                          options={[
                            {
                              value: 'preview',
                              icon: (
                                <Tooltip title={t.common.viewPreview}>
                                  <ViewIcon className="h-5 w-5" />
                                </Tooltip>
                              )
                            },
                            {
                              value: 'code',
                              icon: (
                                <Tooltip title={t.common.viewCode}>
                                  <TerminalIcon className="h-5 w-5" />
                                </Tooltip>
                              )
                            }
                          ]}
                        />
                      )}
                      <Tooltip title={t.workspace.download}>
                        <Button
                          type="text"
                          size="small"
                          icon={<DownloadIcon className="h-5 w-5" />}
                          onClick={() => downloadOne(selectedFile)}
                          className="!text-msa-text-2"
                        />
                      </Tooltip>
                    </div>
                  </div>
                  <div className="min-h-0 flex-1 flex flex-col">
                    {fileLoading ? (
                      <DeferredSkeleton rows={10} className="p-4" />
                    ) : previewKind === 'text' &&
                      docKind === 'markdown' &&
                      viewMode === 'preview' ? (
                      <div className="h-full overflow-auto px-4 py-4">
                        <Markdown
                          content={draft}
                          frontmatter
                          resolveRef={previewRefs}
                        />
                      </div>
                    ) : previewKind === 'text' &&
                      docKind === 'html' &&
                      viewMode === 'preview' ? (
                      <HtmlPreview
                        src={api.workspaceFileRawUrl(project.id, selectedFile)}
                        title={selectedFile}
                        reloadKey={`${selectedFile}:${diskRevision}`}
                      />
                    ) : previewKind === 'text' ? (
                      <CodeEditor
                        value={draft}
                        onChange={setDraft}
                        language={selectedLanguage}
                        height="100%"
                        fullFeatures
                      />
                    ) : previewKind === 'image' ? (
                      <div className="flex h-full items-center justify-center overflow-auto bg-msa-fill-1 p-4">
                        <img
                          src={api.workspaceFileRawUrl(
                            project.id,
                            selectedFile
                          )}
                          alt={selectedFile}
                          className="max-h-full max-w-full object-contain"
                        />
                      </div>
                    ) : previewKind === 'video' ? (
                      <div className="flex h-full items-center justify-center bg-msa-fill-1 p-4">
                        <video
                          src={api.workspaceFileRawUrl(
                            project.id,
                            selectedFile
                          )}
                          controls
                          className="max-h-full max-w-full"
                        />
                      </div>
                    ) : previewKind === 'audio' ? (
                      <div className="flex h-full items-center justify-center bg-msa-fill-1 p-4">
                        <audio
                          src={api.workspaceFileRawUrl(
                            project.id,
                            selectedFile
                          )}
                          controls
                          className="w-full max-w-md"
                        />
                      </div>
                    ) : (
                      <div className="flex h-full flex-col items-center justify-center gap-3 p-4 text-center">
                        <DefaultFileIcon className="h-8 w-8" />
                        <span className="text-sm text-msa-text-3">
                          {t.workspace.previewUnsupported}
                        </span>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <div className="flex flex-1 items-center justify-center">
                  <span className="text-sm text-msa-text-3">
                    {t.workspace.selectFileHint}
                  </span>
                </div>
              )}
            </div>
          </Splitter.Panel>
        </Splitter>
      )}

      {/* Closing would take every parked buffer with it, so the ones at stake are
          named — and each name opens that file, because "which changes?" is a
          question a list of paths only half answers. */}
      <Modal
        open={unsavedPrompt}
        onCancel={() => setUnsavedPrompt(false)}
        title={t.workspace.unsavedTitle}
        footer={
          <>
            <Button onClick={() => setUnsavedPrompt(false)}>
              {t.workspace.cancel}
            </Button>
            <Button danger onClick={discardAllAndClose}>
              {t.workspace.discardAndClose}
            </Button>
            <Button
              type="primary"
              loading={savingAll}
              onClick={saveAllAndClose}
            >
              {t.workspace.saveAllAndClose}
            </Button>
          </>
        }
      >
        <p className="m-0 text-sm text-msa-text-2">{t.workspace.unsavedHint}</p>
        <ul className="m-0 mt-3 flex list-none flex-col gap-1 p-0">
          {unsavedPaths.map((p) => (
            <li key={p} className="min-w-0">
              <button
                type="button"
                title={p}
                onClick={() => {
                  setUnsavedPrompt(false)
                  selectPath(p)
                }}
                className="max-w-full cursor-pointer truncate border-none bg-transparent p-0 text-sm text-msa-text-brand1"
              >
                {p}
              </button>
            </li>
          ))}
        </ul>
      </Modal>
    </div>
  )
}
