import {
  App,
  Button,
  Dropdown,
  Input,
  Modal,
  Splitter,
  Tooltip
} from 'antd'
import type { MenuProps, TreeDataNode } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CodeEditor } from '~/components/common/CodeEditor'
import { EmptyState } from '~/components/common/EmptyState'
import { FolderTree } from '~/components/common/FolderTree'
import { languageFor } from '~/lib/editorLanguage'
import { DeferredSkeleton } from '~/components/common/DeferredSkeleton'
import type { FolderTreeActions } from '~/components/common/FolderTree'
import { IconButton } from '~/components/common/IconButton'
import { api } from '~/lib/api'
import { dispatchWorkspaceChanged, useOnWorkspaceChanged } from '~/lib/events'
import { collectDroppedFiles } from '~/lib/dropFiles'
import { downloadWorkspaceAll, downloadWorkspaceFile } from '~/lib/download'
import { useT } from '~/lib/i18n'
import type { Project, WorkspaceFile } from '~/lib/types'
import { MsaButton } from '../common/MsaButton'
import AddIcon from '~/assets/icons/add.svg?react'
import CloseIcon from '~/assets/icons/close.svg?react'
import RefreshIcon from '~/assets/icons/refresh.svg?react'
import SearchIcon from '~/assets/icons/search.svg?react'
import DownloadIcon from '~/assets/icons/download.svg?react'
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

const IMAGE_EXTS = new Set([
  'png',
  'jpg',
  'jpeg',
  'gif',
  'webp',
  'svg',
  'bmp',
  'ico',
  'avif'
])
const VIDEO_EXTS = new Set(['mp4', 'webm', 'ogg', 'mov', 'avi', 'mkv'])
const AUDIO_EXTS = new Set(['mp3', 'wav', 'aac', 'flac', 'm4a', 'wma', 'opus'])
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
  // Real extension only: text after the last dot of the BASENAME, and only
  // when that dot isn't the leading character. `logging` / `Dockerfile`
  // (no dot) and `.locks` (dotfile) have NO extension — naive
  // `split('.').pop()` would return the whole name instead of ''.
  const name = file.path.split('/').pop() ?? ''
  const dot = name.lastIndexOf('.')
  const ext = dot > 0 ? name.slice(dot + 1).toLowerCase() : ''
  if (IMAGE_EXTS.has(ext)) return 'image'
  if (VIDEO_EXTS.has(ext)) return 'video'
  if (AUDIO_EXTS.has(ext)) return 'audio'
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

export function SessionRightRail({
  project,
  sessionId: _sessionId,
  active,
  openFile,
  onClose
}: Props) {
  const { t } = useT()
  const { message, modal } = App.useApp()
  const [files, setFiles] = useState<WorkspaceFile[] | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [filter, setFilter] = useState('')
  // Name-prompt modal for New file / New folder / Rename.
  const [prompt, setPrompt] = useState<{
    title: string
    initial: string
    onOk: (value: string) => void
  } | null>(null)
  const [promptValue, setPromptValue] = useState('')
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [fileContent, setFileContent] = useState<string | null>(null)
  // Live editor buffer; diverges from `fileContent` while the user edits.
  const [draft, setDraft] = useState('')
  const [fileLoading, setFileLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [previewKind, setPreviewKind] = useState<PreviewKind>('text')
  const [downloadingAll, setDownloadingAll] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)

  const dirty = selectedFile !== null && draft !== (fileContent ?? '')

  // Set webkitdirectory attribute via DOM (React doesn't support it natively)
  useEffect(() => {
    if (folderInputRef.current) {
      folderInputRef.current.setAttribute('webkitdirectory', '')
      folderInputRef.current.setAttribute('directory', '')
    }
  }, [])

  const loadFiles = (spin = false) => {
    if (spin) setRefreshing(true)
    api
      .listWorkspaceFiles(project.id)
      .then(setFiles)
      .catch(() => setFiles([]))
      .finally(() => {
        if (spin) setRefreshing(false)
      })
  }

  // A project switch must not flash the previous project's tree (or keep its
  // selected file) while the new list loads — reset to the loading placeholder
  // first. Reopening the same project keeps the last list visible during the
  // silent refresh.
  const prevProjectRef = useRef(project.id)
  useEffect(() => {
    if (prevProjectRef.current === project.id) return
    prevProjectRef.current = project.id
    setFiles(null)
    setSelectedFile(null)
    setFileContent(null)
    setDraft('')
  }, [project.id])

  // Load on open (and on project change while open). The rail stays mounted at
  // width 0 when closed, so re-running here — rather than on mount — keeps the
  // list fresh each time it's reopened. When `active` is not provided, fall back
  // to a one-shot load on mount.
  useEffect(() => {
    if (active === undefined || active) loadFiles()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, project.id])

  // Cross-component sync: another view (e.g. project-edit modal) uploaded files.
  // Wrapped so the event's optional `created` paths payload isn't mistaken for
  // loadFiles' `spin` flag.
  const reloadOnChange = useCallback(() => loadFiles(), [loadFiles])
  useOnWorkspaceChanged(reloadOnChange)

  // Zip the whole workspace and download it as `<project>.zip`.
  const handleDownloadAll = async () => {
    if (!files || files.length === 0) return
    setDownloadingAll(true)
    try {
      await downloadWorkspaceAll(
        project.id,
        files,
        `${project.name || 'workspace'}.zip`
      )
    } catch {
      message.error(t.workspace.downloadFailed)
    } finally {
      setDownloadingAll(false)
    }
  }

  const handleUpload = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return
    // Multipart upload preserves raw bytes, so binary files (images, archives,
    // …) aren't corrupted by UTF-8 coercion the way `file.text()` would.
    const uploads = Array.from(fileList).map((file) =>
      api
        .uploadWorkspaceFile(
          project.id,
          file,
          file.webkitRelativePath || file.name,
          { silent: [409] }
        )
        .catch(() => {})
    )
    await Promise.all(uploads)
    dispatchWorkspaceChanged()
  }

  const addMenu: MenuProps = {
    items: [
      {
        key: 'upload-file',
        label: t.workspace.uploadFile,
        onClick: () => fileInputRef.current?.click()
      },
      {
        key: 'upload-folder',
        label: t.workspace.uploadFolder,
        onClick: () => folderInputRef.current?.click()
      }
    ]
  }

  const treeData = useMemo(
    () => (files ? toTreeData(buildTree(files)) : []),
    [files]
  )

  const selectPath = (path: string) => {
    setSelectedFile(path)
    setFileContent(null)
    setDraft('')
    setPreviewKind('text')
    setFileLoading(true)
    api
      .getWorkspaceFile(project.id, path)
      .then((f) => {
        const kind = previewKindOf(f)
        setPreviewKind(kind)
        if (kind === 'text') {
          const content = f.content ?? f.preview ?? ''
          setFileContent(content)
          setDraft(content)
        }
      })
      .catch(() => {
        setPreviewKind('text')
        setFileContent('')
        setDraft('')
      })
      .finally(() => setFileLoading(false))
  }

  const handleSelect = (key: string) => {
    if (!key.startsWith('file:')) return
    selectPath(key.slice(5))
  }

  // ---- File-management actions (context menu + drag & drop) ----

  const openPrompt = (p: {
    title: string
    initial: string
    onOk: (value: string) => void
  }) => {
    setPromptValue(p.initial)
    setPrompt(p)
  }

  const submitPrompt = () => {
    const value = promptValue.trim()
    if (!value || !prompt) return
    prompt.onOk(value)
    setPrompt(null)
  }

  const createEntry = (dir: string, kind: 'file' | 'folder') =>
    openPrompt({
      title:
        kind === 'folder'
          ? t.workspace.newFolderTitle
          : t.workspace.newFileTitle,
      initial: '',
      onOk: async (name) => {
        const path = joinPath(dir, name)
        try {
          await api.createWorkspaceFile(project.id, { path, kind, content: '' })
          // Broadcast instead of a local reload: our own listener refreshes
          // the tree, AND chat file cards / the project page stay in sync.
          dispatchWorkspaceChanged()
          if (kind === 'file') selectPath(path)
        } catch {
          message.error(t.workspace.createFailed)
        }
      }
    })

  // Rewrite the open file's path when it (or its parent folder) is moved/renamed
  // so the editor keeps pointing at the same file after the tree refreshes.
  const remapSelected = (src: string, dest: string) => {
    if (selectedFile === src) setSelectedFile(dest)
    else if (selectedFile?.startsWith(`${src}/`))
      setSelectedFile(dest + selectedFile.slice(src.length))
  }

  const moveEntry = async (src: string, dest: string) => {
    try {
      await api.moveWorkspaceFile(project.id, src, dest)
      remapSelected(src, dest)
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
          if (selectedFile === path || selectedFile?.startsWith(`${path}/`)) {
            setSelectedFile(null)
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
    if (
      selectedFile &&
      paths.some((p) => selectedFile === p || selectedFile.startsWith(`${p}/`))
    ) {
      setSelectedFile(null)
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
          dispatchWorkspaceChanged()
        } catch {
          message.error(t.workspace.saveFailed)
        }
      }
    })

  const downloadMany = (paths: string[]) => {
    // Folders can't be streamed as a single file; caller passes files only.
    paths.forEach((p) => downloadWorkspaceFile(project.id, p))
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
      dispatchWorkspaceChanged()
    } catch {
      message.error(t.workspace.moveFailed)
    }
  }

  const treeActions: FolderTreeActions = {
    onNewFile: (dir) => createEntry(dir, 'file'),
    onNewFolder: (dir) => createEntry(dir, 'folder'),
    onRename: renameTo,
    onDelete: deleteEntry,
    onCopyPath: copyPath,
    onDownload: (path) => downloadWorkspaceFile(project.id, path),
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

  const saveFile = async () => {
    if (!selectedFile || !dirty || saving) return
    setSaving(true)
    try {
      const saved = await api.putWorkspaceFile(project.id, selectedFile, draft)
      setFileContent(draft)
      // Reflect updated size / mtime in the tree metadata.
      setFiles((prev) =>
        prev
          ? prev.map((f) => (f.path === saved.path ? { ...f, ...saved } : f))
          : prev
      )
    } catch {
      message.error(t.workspace.saveFailed)
    } finally {
      setSaving(false)
    }
  }

  const selectedLanguage = selectedFile ? languageFor(selectedFile) : ''

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
      {/* Hidden file inputs */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => {
          handleUpload(e.target.files)
          e.target.value = ''
        }}
      />
      <input
        ref={folderInputRef}
        type="file"
        className="hidden"
        onChange={(e) => {
          handleUpload(e.target.files)
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
              onClick={() => loadFiles(true)}
            />
          </Tooltip>
        </div>
        {onClose && (
          <IconButton
            icon={<CloseIcon className="h-4 w-4" />}
            variant="tonal"
            size="sm"
            onClick={onClose}
          />
        )}
      </div>

      {/* Body */}
      {files !== null && files.length === 0 ? (
        /* Empty state: no split, full width */
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <EmptyState
            description={t.workspace.empty}
            action={
              <Dropdown menu={addMenu} trigger={['click']}>
                <MsaButton variant="primary" icon={<AddIcon className="h-4 w-4" />}>
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
                  size="small"
                  prefix={<SearchIcon className="h-4 w-4 text-msa-text-3" />}
                  placeholder={t.workspace.searchPlaceholder}
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                />
              </div>
              <div
                className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-2 py-1"
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
                    onSelect={handleSelect}
                    filter={filter}
                    actions={treeActions}
                  />
                )}
              </div>
              {/* Footer: download + add, inside left panel */}
              <div className="flex shrink-0 items-stretch border-t border-msa-line-1">
                <Button
                  type="text"
                  size="small"
                  icon={<DownloadIcon className="h-4 w-4" />}
                  loading={downloadingAll}
                  disabled={!files || files.length === 0}
                  onClick={handleDownloadAll}
                  className="h-10 flex-1 !rounded-none !text-msa-text-2"
                >
                  {t.workspace.downloadAll}
                </Button>
                <div className="w-px bg-msa-line-1" />
                <Dropdown menu={addMenu} trigger={['click']}>
                  <Button
                    type="text"
                    size="small"
                    icon={<AddIcon className="h-4 w-4" />}
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
                    <span
                      className="truncate text-sm text-msa-text-2"
                      title={selectedFile}
                    >
                      {selectedFile}
                      {previewKind === 'text' && dirty && (
                        <span className="ml-1 text-msa-text-3">•</span>
                      )}
                    </span>
                    <Tooltip title={t.workspace.download}>
                      <Button
                        type="text"
                        size="small"
                        icon={<DownloadIcon className="h-4 w-4" />}
                        onClick={() =>
                          downloadWorkspaceFile(project.id, selectedFile)
                        }
                        className="!text-msa-text-2"
                      />
                    </Tooltip>
                  </div>
                  <div className="min-h-0 flex-1">
                    {fileLoading ? (
                      <DeferredSkeleton rows={10} className="p-4" />
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

      {/* New file / New folder / Rename name prompt */}
      <Modal
        open={!!prompt}
        title={prompt?.title}
        okText={t.workspace.save}
        cancelText={t.workspace.cancel}
        okButtonProps={{ disabled: !promptValue.trim() }}
        onOk={submitPrompt}
        onCancel={() => setPrompt(null)}
        destroyOnHidden
      >
        <Input
          autoFocus
          placeholder={t.workspace.namePlaceholder}
          value={promptValue}
          onChange={(e) => setPromptValue(e.target.value)}
          onPressEnter={submitPrompt}
        />
      </Modal>
    </div>
  )
}
