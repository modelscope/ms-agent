import { ConfigProvider, Dropdown, Tree } from 'antd'
import type { MenuProps, TreeDataNode, TreeProps } from 'antd'
import {
  type FC,
  type ReactNode,
  type SVGProps,
  useEffect,
  useMemo,
  useRef,
  useState
} from 'react'
import { collectDroppedFiles } from '~/lib/dropFiles'
import type { DroppedFile } from '~/lib/dropFiles'
import { useT } from '~/lib/i18n'
import './FolderTree.css'

// File type icons, inlined (`?react`) so the neutral ones can follow
// `currentColor` (see FileCard).
import iconDefault from '~/assets/files/default.svg?react'
import iconPdf from '~/assets/files/pdf.svg?react'
import iconWord from '~/assets/files/word.svg?react'
import iconExcel from '~/assets/files/excel.svg?react'
import iconPpt from '~/assets/files/ppt.svg?react'
import iconZip from '~/assets/files/zip.svg?react'
import iconMarkdown from '~/assets/files/md.svg?react'
import iconJava from '~/assets/files/java.svg?react'
import iconJavascript from '~/assets/files/js.svg?react'
import iconPython from '~/assets/files/py.svg?react'
import iconText from '~/assets/files/txt.svg?react'
import iconMp3 from '~/assets/files/mp3.svg?react'
import iconWeb from '~/assets/files/web.svg?react'
import iconFolder from '~/assets/icons/folder.svg?react'

type FileIcon = FC<SVGProps<SVGSVGElement>>

// Extension → icon mapping
const FILE_ICONS: Record<string, FileIcon> = {
  pdf: iconPdf,
  doc: iconWord,
  docx: iconWord,
  xls: iconExcel,
  xlsx: iconExcel,
  csv: iconExcel,
  ppt: iconPpt,
  pptx: iconPpt,
  zip: iconZip,
  rar: iconZip,
  '7z': iconZip,
  tar: iconZip,
  gz: iconZip,
  md: iconMarkdown,
  js: iconJavascript,
  ts: iconJavascript,
  jsx: iconJavascript,
  tsx: iconJavascript,
  java: iconJava,
  py: iconPython,
  json: iconJavascript,
  mp3: iconMp3,
  html: iconWeb,
  htm: iconWeb,
  css: iconWeb,
  log: iconText,
  txt: iconText,
  yaml: iconDefault,
  yml: iconDefault,
  bin: iconDefault,
  sh: iconDefault,
  xml: iconDefault,
  svg: iconDefault
}

function iconFor(title: string, isDir: boolean): ReactNode {
  const ext = title.split('.').pop()?.toLowerCase() ?? ''
  const Icon = isDir ? iconFolder : FILE_ICONS[ext] ?? iconDefault
  return <Icon aria-hidden className="h-[14px] w-[14px] text-msa-icon-neutral" />
}

// Node keys are `file:<path>` / `dir:<path>` (built by the caller).
function parseKey(key: string): { isDir: boolean; path: string } {
  const isDir = key.startsWith('dir:')
  return { isDir, path: key.slice(key.indexOf(':') + 1) }
}
const baseName = (p: string) => p.split('/').pop() ?? p
const parentDir = (p: string) => {
  const i = p.lastIndexOf('/')
  return i === -1 ? '' : p.slice(0, i)
}

/** File-management actions surfaced by the right-click menu and drag & drop.
 * The tree only reports intent (paths); the host performs the API calls, name
 * prompts and confirmations. */
export interface FolderTreeActions {
  onNewFile: (dir: string) => void
  onNewFolder: (dir: string) => void
  /** Commit an inline rename: give `path` the new base name `newName`. */
  onRename: (path: string, newName: string) => void
  onDelete: (path: string, isDir: boolean) => void
  onCopyPath: (path: string) => void
  onDownload: (path: string) => void
  /** Move/rename `src` to `dest` (both workspace-relative). */
  onMove: (src: string, dest: string) => void
  /** Native OS files dropped onto a folder node (`dir` '' = workspace root). */
  onUploadTo: (dir: string, files: DroppedFile[]) => void
  /** Batch delete a multi-selection. */
  onDeleteMany: (items: { path: string; isDir: boolean }[]) => void
  /** Batch download (files only; folders are filtered out by the caller). */
  onDownloadMany: (paths: string[]) => void
  /** Copy several workspace paths (newline-joined) to the clipboard. */
  onCopyPaths: (paths: string[]) => void
  /** Batch move a multi-selection into a folder. */
  onMoveMany: (moves: { src: string; dest: string }[]) => void
}

interface FolderTreeProps {
  /** Tree structure data (string titles, `file:`/`dir:` keys). */
  treeData: TreeDataNode[]
  /** Currently selected file key */
  selectedKey: string
  /** Callback when a leaf node is selected */
  onSelect: (key: string) => void
  /** Case-insensitive filter: non-matching files are hidden, matches highlighted. */
  filter?: string
  /** File-management callbacks; when omitted the tree is read-only. */
  actions?: FolderTreeActions
  /** Container className */
  className?: string
  /** Expand every folder when the tree (re)loads. Default FALSE (repo-wide
   * convention): the tree starts collapsed and only the ancestors of
   * `selectedKey` auto-expand — deep-link style, revealing exactly the path
   * being opened. Pass true to restore expand-all-on-load. */
  defaultExpandAll?: boolean
}

// Collect keys of directory nodes (those with children), for expand-all.
function dirKeys(nodes: TreeDataNode[], acc: string[] = []): string[] {
  for (const n of nodes) {
    if (n.children) {
      acc.push(String(n.key))
      dirKeys(n.children, acc)
    }
  }
  return acc
}

// A pruned copy of the tree keeping only files whose name matches `filter`
// (case-insensitive) and the directories on the way to them. Returns the kept
// nodes plus the dir keys that must be expanded to reveal the matches.
function filterTree(
  nodes: TreeDataNode[],
  q: string,
  expand: string[]
): TreeDataNode[] {
  const out: TreeDataNode[] = []
  for (const n of nodes) {
    const title = String(n.title ?? '')
    if (n.children) {
      const kids = filterTree(n.children, q, expand)
      const selfMatch = title.toLowerCase().includes(q)
      if (kids.length > 0 || selfMatch) {
        expand.push(String(n.key))
        out.push({ ...n, children: kids })
      }
    } else if (title.toLowerCase().includes(q)) {
      out.push(n)
    }
  }
  return out
}

function Highlight({ text, q }: { text: string; q: string }) {
  if (!q) return <>{text}</>
  const idx = text.toLowerCase().indexOf(q.toLowerCase())
  if (idx === -1) return <>{text}</>
  return (
    <>
      {text.slice(0, idx)}
      <span className="font-semibold text-msa-text-brand1">
        {text.slice(idx, idx + q.length)}
      </span>
      {text.slice(idx + q.length)}
    </>
  )
}

// Inline rename editor rendered in place of a node's name. Autofocuses and
// pre-selects the base name (excluding the extension). Enter/blur commits,
// Escape cancels; a `done` guard prevents Escape's blur from also committing.
function RenameInput({
  initial,
  onCommit,
  onCancel
}: {
  initial: string
  onCommit: (value: string) => void
  onCancel: () => void
}) {
  const [value, setValue] = useState(initial)
  const ref = useRef<HTMLInputElement>(null)
  const done = useRef(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.focus()
    const dot = initial.lastIndexOf('.')
    if (dot > 0) el.setSelectionRange(0, dot)
    else el.select()
  }, [initial])
  const commit = () => {
    if (done.current) return
    done.current = true
    onCommit(value)
  }
  const cancel = () => {
    if (done.current) return
    done.current = true
    onCancel()
  }
  return (
    <input
      ref={ref}
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
      onDoubleClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        e.stopPropagation()
        if (e.key === 'Enter') {
          e.preventDefault()
          commit()
        } else if (e.key === 'Escape') {
          e.preventDefault()
          cancel()
        }
      }}
      onBlur={commit}
      className="mr-2 min-w-0 flex-1 rounded border border-msa-line-2 bg-msa-bg-1 px-1 text-sm text-msa-text-1 outline-none"
    />
  )
}

/**
 * A file-tree browser: full-row select/hover, a right-click context menu
 * (new file/folder, rename, delete, copy path, download), drag-to-move between
 * folders, native OS drag-and-drop upload onto folders, and a live name filter.
 */
export function FolderTree({
  treeData,
  selectedKey,
  onSelect,
  filter = '',
  actions,
  className,
  defaultExpandAll = false
}: FolderTreeProps) {
  const { t } = useT()
  const [expandedKeys, setExpandedKeys] = useState<string[]>([])
  const [autoExpandParent, setAutoExpandParent] = useState(true)
  // Folder key currently under a native file drag, for drop highlighting.
  const [dropDir, setDropDir] = useState<string | null>(null)
  // Multi-selection (Ctrl/Cmd/Shift-click). The externally opened file
  // (`selectedKey`) seeds it; plain single clicks open a file, modified clicks
  // just grow the selection for batch operations.
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  // After a context-menu item is clicked, antd closes the overlay and the
  // click can “fall through” to the tree row underneath and select it. Ignore
  // any select fired within a short window after a menu interaction.
  const suppressSelectUntil = useRef(0)
  // Anchor for Shift range selection (the last plain/toggle-clicked node).
  const anchorKey = useRef<string | null>(null)
  // Key of the node being renamed inline (its name shows an <input>).
  const [renamingKey, setRenamingKey] = useState<string | null>(null)

  // Seed / reset the selection from the externally opened file. A plain click
  // opens a file (updating `selectedKey`) and collapses the selection to it;
  // modified clicks don't change `selectedKey`, so the multi-selection sticks.
  useEffect(() => {
    setSelectedKeys(selectedKey ? [selectedKey] : [])
    anchorKey.current = selectedKey || null
  }, [selectedKey])

  const q = filter.trim().toLowerCase()
  const allDirKeys = useMemo(() => dirKeys(treeData), [treeData])
  const dirSig = allDirKeys.join('|')

  const { data, matchExpand } = useMemo(() => {
    if (!q) return { data: treeData, matchExpand: null as string[] | null }
    const expand: string[] = []
    return { data: filterTree(treeData, q, expand), matchExpand: expand }
  }, [treeData, q])

  // Expand policy on (re)load: everything (default), or — when
  // `defaultExpandAll` is off — only the ancestors of the selected file, so a
  // deep link reveals exactly its own path. While filtering, expand only the
  // ancestors of the matches so results are revealed.
  useEffect(() => {
    if (q && matchExpand) {
      setExpandedKeys(matchExpand)
      setAutoExpandParent(true)
    } else if (defaultExpandAll) {
      setExpandedKeys(allDirKeys)
      setAutoExpandParent(false)
    } else {
      setExpandedKeys([])
      setAutoExpandParent(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, dirSig, defaultExpandAll])

  // Collapsed-by-default mode: reveal the path of the externally opened file
  // (merge its ancestor dirs into the expansion, keeping user-opened folders).
  useEffect(() => {
    if (defaultExpandAll || !selectedKey.startsWith('file:')) return
    const path = selectedKey.slice('file:'.length)
    const parts = path.split('/').slice(0, -1)
    if (parts.length === 0) return
    const ancestors: string[] = []
    for (let i = 1; i <= parts.length; i++) {
      ancestors.push(`dir:${parts.slice(0, i).join('/')}`)
    }
    setExpandedKeys((prev) => [...new Set([...prev, ...ancestors])])
    setAutoExpandParent(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKey, defaultExpandAll, dirSig])

  const menuItems = (isDir: boolean, path: string, key: string): MenuProps['items'] => {
    if (!actions) return []
    // When right-clicking a node that's part of a multi-selection, offer batch
    // operations over the whole selection instead of single-node actions.
    if (selectedKeys.length > 1 && selectedKeys.includes(key)) {
      const picked = selectedKeys.map(parseKey)
      const files = picked.filter((p) => !p.isDir).map((p) => p.path)
      const n = picked.length
      const items: MenuProps['items'] = []
      if (files.length > 0) {
        items.push({
          key: 'downloadMany',
          label: `${t.workspace.download} (${files.length})`,
          onClick: () => actions.onDownloadMany(files)
        })
      }
      items.push({
        key: 'copyMany',
        label: `${t.workspace.copyPath} (${n})`,
        onClick: () => actions.onCopyPaths(picked.map((p) => p.path))
      })
      items.push({ type: 'divider' })
      items.push({
        key: 'deleteMany',
        label: `${t.workspace.delete} (${n})`,
        danger: true,
        onClick: () => actions.onDeleteMany(picked)
      })
      return items
    }
    const items: MenuProps['items'] = []
    if (isDir) {
      items.push({
        key: 'newFile',
        label: t.workspace.newFile,
        onClick: () => actions.onNewFile(path)
      })
      items.push({
        key: 'newFolder',
        label: t.workspace.newFolder,
        onClick: () => actions.onNewFolder(path)
      })
      items.push({ type: 'divider' })
    } else {
      items.push({
        key: 'download',
        label: t.workspace.download,
        onClick: () => actions.onDownload(path)
      })
    }
    items.push({
      key: 'rename',
      label: t.workspace.rename,
      onClick: () => setRenamingKey(key)
    })
    items.push({
      key: 'copy',
      label: t.workspace.copyPath,
      onClick: () => actions.onCopyPath(path)
    })
    items.push({ type: 'divider' })
    items.push({
      key: 'delete',
      label: t.workspace.delete,
      danger: true,
      onClick: () => actions.onDelete(path, isDir)
    })
    return items
  }

  // Native OS file drag handlers, attached per title. Gated on `types` carrying
  // 'Files' so they never interfere with antd's internal node dragging.
  const fileDragProps = (dir: string, key: string) =>
    actions
      ? {
          onDragOver: (e: React.DragEvent) => {
            if (!e.dataTransfer.types.includes('Files')) return
            e.preventDefault()
            e.stopPropagation()
            e.dataTransfer.dropEffect = 'copy'
            if (dropDir !== key) setDropDir(key)
          },
          onDragLeave: (e: React.DragEvent) => {
            if (!e.dataTransfer.types.includes('Files')) return
            setDropDir((k) => (k === key ? null : k))
          },
          onDrop: async (e: React.DragEvent) => {
            if (!e.dataTransfer.types.includes('Files')) return
            e.preventDefault()
            e.stopPropagation()
            setDropDir(null)
            // Entry-tree walk, not `dataTransfer.files`: a dropped FOLDER is not a
            // file there (it surfaces as an unreadable directory entry), so
            // dropping one used to upload a single junk file named after it.
            const entries = await collectDroppedFiles(e.dataTransfer)
            if (entries.length > 0) actions.onUploadTo(dir, entries)
          }
        }
      : {}

  const styledData = useMemo(() => {
    const decorate = (nodes: TreeDataNode[]): TreeDataNode[] =>
      nodes.map((node) => {
        const key = String(node.key)
        const { isDir, path } = parseKey(key)
        const title = String(node.title ?? '')
        const uploadDir = isDir ? path : parentDir(path)
        const renaming = renamingKey === key
        // The icon lives INSIDE the title (not antd's `showIcon` slot) and the
        // title fills the row, so the context-menu trigger and native file-drop
        // target cover the whole row — not just the file name text.
        const titleEl = renaming ? (
          <span className="flex w-full items-center gap-2">
            {iconFor(title, isDir)}
            <RenameInput
              initial={title}
              onCommit={(v) => {
                setRenamingKey(null)
                const next = v.trim()
                if (next && next !== title) actions?.onRename(path, next)
              }}
              onCancel={() => setRenamingKey(null)}
            />
          </span>
        ) : (
          <span
            title={path}
            className="flex w-full items-center gap-2"
            // Right-clicking a node that isn't part of the current selection
            // collapses the selection onto it, so the menu acts on that node.
            onContextMenu={() => {
              if (!selectedKeys.includes(key)) setSelectedKeys([key])
            }}
            {...fileDragProps(uploadDir, key)}
          >
            {iconFor(title, isDir)}
            <span className="min-w-0 flex-1 truncate">
              <Highlight text={title} q={q} />
            </span>
          </span>
        )
        const highlighted = renaming
          ? '' // no selection highlight while editing the name inline
          : selectedKeys.includes(key)
            ? 'bg-msa-fill-4'
            : dropDir === key
              ? 'bg-msa-fill-4 ring-1 ring-inset ring-msa-line-2'
              : 'hover:bg-msa-fill-4'
        return {
          ...node,
          // While renaming, drop the context-menu wrapper so right-click and
          // drag don't interfere with the input.
          title:
            actions && !renaming ? (
              <Dropdown
                menu={{
                  items: menuItems(isDir, path, key),
                  onClick: ({ domEvent }) => {
                    domEvent?.stopPropagation?.()
                    suppressSelectUntil.current = Date.now() + 400
                  }
                }}
                trigger={['contextMenu']}
              >
                {titleEl}
              </Dropdown>
            ) : (
              titleEl
            ),
          className: `rounded-lg ${highlighted}`,
          children: node.children ? decorate(node.children) : undefined
        }
      })
    return decorate(data)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, selectedKeys, dropDir, q, actions, renamingKey])

  // Flat list of currently visible node keys in display order (a folder's
  // children only count when it's expanded), so Shift-range selection matches
  // exactly the rows the user sees.
  const visibleKeys = useMemo(() => {
    const expanded = new Set(expandedKeys)
    const out: string[] = []
    const walk = (nodes: TreeDataNode[]) => {
      for (const n of nodes) {
        const k = String(n.key)
        out.push(k)
        if (n.children && expanded.has(k)) walk(n.children)
      }
    }
    walk(data)
    return out
  }, [data, expandedKeys])

  const rangeBetween = (a: string, b: string): string[] => {
    const ai = visibleKeys.indexOf(a)
    const bi = visibleKeys.indexOf(b)
    if (ai === -1 || bi === -1) return [b]
    const [lo, hi] = ai <= bi ? [ai, bi] : [bi, ai]
    return visibleKeys.slice(lo, hi + 1)
  }

  // Editor-style selection: plain click selects one (and opens a file);
  // Ctrl/Cmd/Alt toggles a single row; Shift selects the contiguous range from
  // the anchor (the last plain/toggle click) to the clicked row.
  const handleTreeSelect: TreeProps['onSelect'] = (_keys, info) => {
    if (Date.now() < suppressSelectUntil.current) {
      suppressSelectUntil.current = 0
      return
    }
    const ne = info.nativeEvent as MouseEvent | undefined
    const clicked = String(info.node.key)
    const shift = !!ne && ne.shiftKey
    const toggle = !!ne && (ne.ctrlKey || ne.metaKey || ne.altKey)
    if (shift && anchorKey.current) {
      // Range from anchor to clicked; anchor stays put for further shift-clicks.
      setSelectedKeys(rangeBetween(anchorKey.current, clicked))
      return
    }
    if (toggle) {
      setSelectedKeys((prev) =>
        prev.includes(clicked)
          ? prev.filter((k) => k !== clicked)
          : [...prev, clicked]
      )
      anchorKey.current = clicked
      return
    }
    // Plain click: collapse to just this node; a file opens, a FOLDER toggles
    // its expansion (the whole row acts as the caret — no need to hit the tiny
    // arrow).
    setSelectedKeys([clicked])
    anchorKey.current = clicked
    if (info.node.isLeaf) {
      onSelect(clicked)
      return
    }
    setExpandedKeys((prev) =>
      prev.includes(clicked)
        ? prev.filter((k) => k !== clicked)
        : [...prev, clicked]
    )
    // Manual toggling must not be undone by antd's ancestor auto-expansion.
    setAutoExpandParent(false)
  }

  // Replace the browser's default drag ghost (a loose snapshot of the whole
  // tree row, with stray padding/whitespace) with a compact icon+name pill.
  const onDragStart: TreeProps['onDragStart'] = (info) => {
    const dt = info.event.dataTransfer
    const row = (info.event.target as HTMLElement | null)?.closest?.(
      '.ant-tree-treenode'
    ) as HTMLElement | null
    if (!dt || !dt.setDragImage || !row) return
    const iconEl = row.querySelector('.ant-tree-title img') as HTMLImageElement | null
    const name = row.querySelector('.ant-tree-title')?.textContent ?? ''
    // Dragging any node of a multi-selection moves the whole set: show a count.
    const dragKey = String(info.node.key)
    const multi = selectedKeys.length > 1 && selectedKeys.includes(dragKey)
    const ghost = document.createElement('div')
    ghost.style.cssText =
      'position:fixed;top:-1000px;left:-1000px;display:inline-flex;align-items:center;gap:8px;max-width:260px;padding:4px 10px;border-radius:8px;background:var(--msa-bg-1);border:1px solid var(--msa-line-2);box-shadow:var(--msa-shadow-s);font-size:13px;line-height:20px;color:var(--msa-text-1);white-space:nowrap;overflow:hidden'
    if (!multi && iconEl) {
      const i = iconEl.cloneNode(true) as HTMLImageElement
      i.style.cssText = 'width:14px;height:14px;flex:0 0 auto'
      ghost.appendChild(i)
    }
    const label = document.createElement('span')
    label.textContent = multi
      ? `${selectedKeys.length} ${t.workspace.selectedItems}`
      : name
    label.style.cssText = 'overflow:hidden;text-overflow:ellipsis'
    ghost.appendChild(label)
    document.body.appendChild(ghost)
    dt.setDragImage(ghost, 12, 16)
    // Remove once the browser has snapshotted it for the drag image.
    setTimeout(() => ghost.remove(), 0)
  }

  // Internal drag-to-move: drop onto a folder moves into it; drop onto/next to
  // a file targets that file's parent dir. Dragging a node of a multi-selection
  // moves the whole set. Guards against no-ops and moving a folder into its own
  // subtree.
  const onDrop: TreeProps['onDrop'] = (info) => {
    if (!actions) return
    const target = parseKey(String(info.node.key))
    const destDir =
      !info.dropToGap && target.isDir ? target.path : parentDir(target.path)
    const dragKey = String(info.dragNode.key)
    const sources =
      selectedKeys.length > 1 && selectedKeys.includes(dragKey)
        ? selectedKeys.map(parseKey)
        : [parseKey(dragKey)]
    const moves: { src: string; dest: string }[] = []
    for (const { path: src, isDir: srcIsDir } of sources) {
      const dest = destDir ? `${destDir}/${baseName(src)}` : baseName(src)
      if (dest === src) continue
      if (srcIsDir && dest.startsWith(`${src}/`)) continue
      moves.push({ src, dest })
    }
    if (moves.length === 0) return
    if (moves.length === 1) actions.onMove(moves[0].src, moves[0].dest)
    else actions.onMoveMany(moves)
  }

  return (
    <ConfigProvider
      theme={{
        components: {
          Tree: { nodeSelectedBg: 'transparent', nodeHoverBg: 'transparent' }
        }
      }}
    >
      {q && styledData.length === 0 ? (
        <div className="px-3 py-6 text-center text-xs text-msa-text-3">
          {t.workspace.noSearchResults}
        </div>
      ) : (
        <div
          // F2 or Enter starts an inline rename of the single selected node
          // (editor-style). Enter is ignored while a rename input is already
          // open — that keystroke belongs to the input (it commits the name) —
          // and while a search box or any other field has focus.
          // Capture phase: antd Tree also acts on Enter (it re-selects the node,
          // which would open the file preview), so the rename shortcut has to
          // claim the keystroke before the Tree sees it.
          onKeyDownCapture={(e) => {
            if (!actions || renamingKey || selectedKeys.length !== 1) return
            if (e.key !== 'F2' && e.key !== 'Enter') return
            const el = e.target as HTMLElement | null
            if (
              el &&
              (el.tagName === 'INPUT' ||
                el.tagName === 'TEXTAREA' ||
                el.isContentEditable)
            )
              return
            e.preventDefault()
            e.stopPropagation()
            setRenamingKey(selectedKeys[0])
          }}
        >
          <Tree
            multiple
            blockNode
            draggable={actions ? { icon: false } : false}
            selectedKeys={selectedKeys}
            treeData={styledData}
            expandedKeys={expandedKeys}
            autoExpandParent={autoExpandParent}
            onExpand={(keys) => {
              setExpandedKeys(keys.map(String))
              setAutoExpandParent(false)
            }}
            onDrop={onDrop}
            onDragStart={actions ? onDragStart : undefined}
            className={className}
            rootClassName="folder-tree"
            classNames={{
              itemSwitcher: 'before:hidden'
            }}
            onSelect={handleTreeSelect}
          />
        </div>
      )}
    </ConfigProvider>
  )
}
