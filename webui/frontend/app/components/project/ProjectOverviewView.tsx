import { BulbOutlined } from '@ant-design/icons'
import './ProjectOverviewView.css'
import {
  App,
  Button,
  Drawer,
  Dropdown,
  Popconfirm,
  Skeleton,
  Space,
  Table,
  Tabs,
  Tooltip,
  Typography
} from 'antd'
import type { MenuProps } from 'antd'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { useNavigate, useRevalidator, useSearchParams } from 'react-router'
import { Composer } from '~/components/common/Composer'
import { IconButton } from '~/components/common/IconButton'
import { McpTabPanel } from '~/components/project/McpTabPanel'
import { SkillTabPanel } from '~/components/project/SkillTabPanel'
import { ProjectWidgetRail } from '~/components/project/ProjectWidgetRail'
import { api } from '~/lib/api'
import { dispatchWorkspaceChanged, useOnWorkspaceChanged } from '~/lib/events'
import type { ChatFileRef, MessageSegment } from '~/lib/agentProvider'
import {
  DownloadEmptyError,
  downloadErrorText,
  downloadWorkspaceAll,
  downloadWorkspacePath,
  hasDownloadableFiles
} from '~/lib/download'
import { EmptyState, EmptyStateAction } from '~/components/common/EmptyState'
import { SessionRightRail } from '~/components/session/SessionRightRail'
import { RailDrawer } from '~/components/common/RailDrawer'
import { DeferredSkeleton } from '~/components/common/DeferredSkeleton'
import { useT } from '~/lib/i18n'
import type { Project, Session, WorkspaceFile } from '~/lib/types'
import EditIcon from '~/assets/icons/edit.svg?react'
import DetailsIcon from '~/assets/icons/custom-instruction.svg?react'
import RecentChatsIcon from '~/assets/icons/recent-chats.svg?react'
import WorkspaceIcon from '~/assets/icons/workspace.svg?react'
import McpIcon from '~/assets/icons/mcp.svg?react'
import SkillIcon from '~/assets/icons/skill.svg?react'
import JumpIcon from '~/assets/icons/jump.svg?react'
import { FileTypeIcon } from '~/components/common/FileCard'
import ChatsIcon from '~/assets/icons/recent-chats.svg?react'
import MediaIcon from '~/assets/icons/media.svg?react'
import ParamsIcon from '~/assets/icons/params.svg?react'
import TodoIcon from '~/assets/icons/todo.svg?react'
import GlobeIcon from '~/assets/icons/globe.svg?react'
import TerminalIcon from '~/assets/icons/terminal.svg?react'
import FolderIcon from '~/assets/icons/folder.svg?react'
import DownloadIcon from '~/assets/icons/download.svg?react'
import CaretDownIcon from '~/assets/icons/chevron-down.svg?react'
import RefreshIcon from '~/assets/icons/refresh.svg?react'

interface Props {
  project: Project
  sessions: Session[]
  onEditProject?: (p: Project) => void
}

export function ProjectOverviewView({
  project,
  sessions,
  onEditProject
}: Props) {
  const { t } = useT()
  const navigate = useNavigate()
  const revalidator = useRevalidator()
  const [searchParams, setSearchParams] = useSearchParams()
  const VALID_TABS = ['recent', 'workspace', 'mcps', 'skills'] as const
  const tabFromUrl = searchParams.get('tab') ?? 'recent'
  const activeTab = VALID_TABS.includes(tabFromUrl as any)
    ? tabFromUrl
    : 'recent'
  const setActiveTab = (key: string) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (key === 'recent') next.delete('tab')
        else next.set('tab', key)
        return next
      },
      { replace: true }
    )
  }

  const handleSubmit = async (
    text: string,
    files?: ChatFileRef[],
    segments?: MessageSegment[],
    modelId?: string
  ) => {
    const session = await api.createSession({
      title: text.slice(0, 60) || 'New chat',
      project_id: project.id,
      preview: text,
      model_id: modelId
    })
    // Refresh the sidebar's session list BEFORE leaving: the app layout no
    // longer revalidates on a route change (see its `shouldRevalidate`), so
    // without this the session just created would be missing from the list
    // until the next explicit refresh. Awaited so the navigation below cannot
    // interrupt it.
    await revalidator.revalidate()
    // Carry the composer's FULL submission across the navigation. `segments` is
    // the ordered text+skill-pill layout: dropping it here downgraded a
    // "/skill …" first message to plain text, so the skill never ran for a
    // conversation started from this page (it worked from inside a session).
    navigate(`/projects/${project.id}/sessions/${session.id}`, {
      state: { prefill: text, prefillFiles: files, prefillSegments: segments }
    })
  }

  // Right widget rail is side-by-side on >=lg; on smaller screens it collapses
  // into a drawer opened from a title-bar button (kept out of the horizontal
  // flow so narrow screens never squeeze or hide it silently).
  const [detailsDrawer, setDetailsDrawer] = useState(false)

  // Clicking a file in the workspace table opens the SAME rail the chat view
  // uses (tree + preview + editor), rather than a second, weaker preview built
  // just for this page. `nonce` re-triggers the selection when the same file is
  // clicked again after closing the drawer.
  const [openFileReq, setOpenFileReq] = useState<{
    path: string
    nonce: number
  } | null>(null)
  const [workspaceDrawer, setWorkspaceDrawer] = useState(false)
  const openWorkspaceFile = (path: string) => {
    setOpenFileReq((prev) => ({ path, nonce: (prev?.nonce ?? 0) + 1 }))
    setWorkspaceDrawer(true)
  }

  // Creating one goes through the same rail, for the same reason: naming happens
  // inline in its tree, so this page has one way of making files rather than a
  // dialog of its own that behaves differently.
  const [createEntryReq, setCreateEntryReq] = useState<{
    dir: string
    kind: 'file' | 'folder'
    nonce: number
  } | null>(null)
  const startWorkspaceEntry = (dir: string, kind: 'file' | 'folder') => {
    // The table browses with a trailing slash ('docs/'); the tree keys its
    // folders without one.
    const clean = dir.replace(/\/+$/, '')
    setCreateEntryReq((prev) => ({
      dir: clean,
      kind,
      nonce: (prev?.nonce ?? 0) + 1
    }))
    setWorkspaceDrawer(true)
  }

  // Both requests are one-shot orders, spent by the drawer they opened. The rail
  // is destroyed on close and replays whatever request it mounts with, so a
  // leftover here would hijack the NEXT open — closing a naming row without
  // naming anything, then clicking a file to preview it, re-opened that row.
  //
  // Destroying it also destroys any unsaved editor buffer inside it, so the rail
  // gets the first word on every close (its own button, the mask, Esc) and can put
  // up its own prompt instead.
  const railCloseGuard = useRef<(() => boolean) | null>(null)
  const closeWorkspaceDrawer = () => {
    if (railCloseGuard.current?.()) return
    setWorkspaceDrawer(false)
    setOpenFileReq(null)
    setCreateEntryReq(null)
  }

  return (
    <div className="flex h-full min-h-0 rounded-[16px] bg-msa-fill-0 px-4 py-4 md:px-9 md:py-6">
      {/* Main content */}
      <section className="min-h-0 min-w-0 flex-5 shrink-0">
        <div className="w-full flex flex-col h-full">
          {/* Project title with edit icon.
              The left padding below `md` is clearance for the layout's floating
              sidebar toggle (`absolute left-3 top-3`, 40px — see layouts/app.tsx),
              which overlays this row and was covering the title's first
              character on every project: "渲染验证-Demo" read "染验证-Demo". This is
              the only page that puts content in that corner; from `md` up the
              toggle is gone and the title sits at the shell's own gutter. */}
          <div className="flex items-center gap-2 mb-[12px] pl-9 md:pl-0">
            <Typography.Title
              level={1}
              className="my-0 text-xl font-bold text-msa-text-1"
              ellipsis={{
                rows: 1,
                tooltip: project.name
              }}
            >
              {project.name}
            </Typography.Title>
            {onEditProject && (
              <IconButton
                icon={<EditIcon className="h-4 w-4" />}
                size="sm"
                variant="filled"
                onClick={() => onEditProject(project)}
              />
            )}
            {/* <lg: open Instructions & Memory as a drawer */}
            <Tooltip title={t.projectDetail.detailsPanel}>
              <IconButton
                className="ml-auto lg:hidden"
                icon={<DetailsIcon className="h-4 w-4" />}
                size="sm"
                variant="filled"
                onClick={() => setDetailsDrawer(true)}
              />
            </Tooltip>
          </div>

          {/* Composer */}
          <Composer
            project={project}
            onSubmit={handleSubmit}
            autoSize={{
              minRows: 2,
              maxRows: 6
            }}
          />

          {/* Tabs: Recent / Workspace / MCPs / Skills */}
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            indicator={{ size: 8, align: 'center' }}
            className={`h-0 flex-1 pov-tabs-scroll-content`}
            classNames={{
              indicator: 'bg-msa-text-1 h-[2px]',
              header: 'before:hidden',
              body: 'h-full'
            }}
            items={[
              {
                key: 'recent',
                label: (
                  <span
                    className={`flex items-center gap-1.5 ${activeTab === 'recent' ? 'font-semibold' : ''}`}
                  >
                    {activeTab === 'recent' && (
                      <RecentChatsIcon className="h-4 w-4" />
                    )}
                    {t.projectDetail.tabRecent}
                  </span>
                ),
                children: (
                  <RecentChats projectId={project.id} sessions={sessions} />
                )
              },
              {
                key: 'workspace',
                label: (
                  <span
                    className={`flex items-center gap-1.5 ${activeTab === 'workspace' ? 'font-semibold' : ''} `}
                  >
                    {activeTab === 'workspace' && (
                      <WorkspaceIcon className="h-4 w-4" />
                    )}
                    {t.projectDetail.tabWorkspace}
                  </span>
                ),
                children: (
                  <WorkspacePanel
                    project={project}
                    onOpenFile={openWorkspaceFile}
                    onNewEntry={startWorkspaceEntry}
                  />
                )
              },
              {
                key: 'mcps',
                label: (
                  <span
                    className={`flex items-center gap-1.5 ${activeTab === 'mcps' ? 'font-semibold' : ''}`}
                  >
                    {activeTab === 'mcps' && <McpIcon className="h-4 w-4" />}
                    {t.projectDetail.tabMcps}
                  </span>
                ),
                children: <McpTabPanel project={project} />
              },
              {
                key: 'skills',
                label: (
                  <span
                    className={`flex items-center gap-1.5 ${activeTab === 'skills' ? 'font-semibold' : ''}`}
                  >
                    {activeTab === 'skills' && (
                      <SkillIcon className="h-4 w-4" />
                    )}
                    {t.projectDetail.tabSkills}
                  </span>
                ),
                children: <SkillTabPanel project={project} />
              }
            ]}
          />
        </div>
      </section>

      {/* Right widget rail — large screen only, no divider */}
      <div className="hidden flex-3 w-0 ml-[20px] lg:block">
        <ProjectWidgetRail project={project} />
      </div>

      {/* <lg: same rail content in an overlay drawer */}
      <Drawer
        rootClassName="lg:hidden"
        open={detailsDrawer}
        onClose={() => setDetailsDrawer(false)}
        placement="right"
        size="min(720px, 92vw)"
        title={t.projectDetail.detailsPanel}
        styles={{ body: { padding: 20 } }}
      >
        <ProjectWidgetRail project={project} />
      </Drawer>

      {/* Workspace file preview — the chat view's rail in the shared overlay
          shell (RailDrawer). Wider than the chat's version: this page has no
          conversation to keep visible behind it, so the tree + preview split
          gets more room. */}
      <RailDrawer
        open={workspaceDrawer}
        onClose={closeWorkspaceDrawer}
        size="min(1100px, 94vw)"
        destroyOnHidden
      >
        <SessionRightRail
          project={project}
          active={workspaceDrawer}
          openFile={openFileReq ?? undefined}
          createEntry={createEntryReq ?? undefined}
          closeGuard={railCloseGuard}
          onClose={closeWorkspaceDrawer}
        />
      </RailDrawer>
    </div>
  )
}

/* ─── Recent Chats ─────────────────────────────────── */

// Topic category -> leading icon for a recent conversation. Keys mirror the
// backend taxonomy (ms_agent/titler.CATEGORIES); an unset/unknown category
// falls back to the generic "general" chat icon.
const CATEGORY_ICON: Record<string, ReactNode> = {
  coding: <TerminalIcon className="h-5 w-5 text-msa-text-3" />,
  writing: <EditIcon className="h-5 w-5 text-msa-text-3" />,
  research: <GlobeIcon className="h-5 w-5 text-msa-text-3" />,
  planning: <TodoIcon className="h-5 w-5 text-msa-text-3" />,
  data: <ParamsIcon className="h-5 w-5 text-msa-text-3" />,
  creative: <BulbOutlined className="text-xl text-msa-text-3" />,
  media: <MediaIcon className="h-5 w-5 text-msa-text-3" />,
  general: <ChatsIcon className="h-5 w-5 text-msa-text-3" />
}

function categoryIcon(category?: string): ReactNode {
  return CATEGORY_ICON[
    category && category in CATEGORY_ICON ? category : 'general'
  ]
}

function getRelativeTime(dateStr: string, t: any): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const diff = now - then
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return t.projectDetail.timeJustNow
  if (minutes < 60)
    return t.projectDetail.timeMinutesAgo.replace('{n}', String(minutes))
  const hours = Math.floor(minutes / 60)
  if (hours < 24)
    return t.projectDetail.timeHoursAgo.replace('{n}', String(hours))
  const days = Math.floor(hours / 24)
  if (days < 30) return t.projectDetail.timeDaysAgo.replace('{n}', String(days))
  return new Date(dateStr).toLocaleDateString()
}

function RecentChats({
  projectId,
  sessions
}: {
  projectId: string
  sessions: Session[]
}) {
  const { t } = useT()
  const navigate = useNavigate()

  if (sessions.length === 0) {
    return (
      <EmptyState
        size="lg"
        description={`${t.projectDetail.recentEmpty}${t.projectDetail.recentEmptyHint}`}
        action={
          <EmptyStateAction
            onClick={() => navigate(`/projects/${projectId}/new`)}
          >
            {t.projectDetail.startChat}
          </EmptyStateAction>
        }
      />
    )
  }

  return (
    <div className="space-y-3">
      {sessions.map((s) => (
        <div
          key={s.id}
          className="group/chat flex cursor-pointer items-center gap-4 rounded-xl bg-msa-fill-2 px-4 py-3.5 transition-colors hover:bg-msa-fill-4"
          onClick={() => navigate(`/projects/${projectId}/sessions/${s.id}`)}
        >
          {/* Topic-category icon */}
          <span className="shrink-0 flex items-center justify-center">
            {categoryIcon(s.category)}
          </span>
          {/* Title + preview */}
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-msa-text-1">
              {s.title}
            </div>
            {s.preview && (
              <div className="mt-0.5 truncate text-xs text-msa-text-3">
                {s.preview}
              </div>
            )}
          </div>
          {/* Relative time / Enter chat */}
          <span className="shrink-0 text-xs text-msa-text-3 group-hover/chat:hidden">
            {getRelativeTime(s.updated_at, t)}
          </span>
          <span className="hidden shrink-0 items-center gap-1 text-xs font-medium text-msa-text-brand1 group-hover/chat:inline-flex">
            {t.projectDetail.enterChat}
            <JumpIcon className="h-4 w-4" />
          </span>
        </div>
      ))}
    </div>
  )
}

/* ─── Workspace Panel ──────────────────────────────── */

function WorkspacePanel({
  project,
  onOpenFile,
  onNewEntry
}: {
  project: Project
  /** Preview a file in the workspace rail drawer. */
  onOpenFile: (path: string) => void
  /** Create an entry in `dir` — opens the same rail, which names it inline. */
  onNewEntry: (dir: string, kind: 'file' | 'folder') => void
}) {
  // Drives the add-file caret flip (antd Dropdown owns the panel).
  const [addMenuOpen, setAddMenuOpen] = useState(false)
  const { t } = useT()
  const { message } = App.useApp()
  const [files, setFiles] = useState<WorkspaceFile[] | null>(null)
  const [currentPath, setCurrentPath] = useState('')
  const [downloadingAll, setDownloadingAll] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)

  // Set webkitdirectory attribute via DOM (React doesn't support it natively)
  useEffect(() => {
    if (folderInputRef.current) {
      folderInputRef.current.setAttribute('webkitdirectory', '')
      folderInputRef.current.setAttribute('directory', '')
    }
  }, [])

  const loadFiles = () => {
    api
      .listWorkspaceFiles(project.id)
      .then(setFiles)
      .catch(() => setFiles([]))
  }

  useEffect(() => {
    loadFiles()
  }, [project.id])

  // Re-fetch when another component uploads/creates files in this workspace.
  useOnWorkspaceChanged(loadFiles)

  const handleUpload = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return
    // Multipart upload preserves raw bytes, so binary files (images, archives,
    // …) aren't corrupted by UTF-8 coercion the way `file.text()` would.
    const uploads = Array.from(fileList).map((file) =>
      api
        .uploadWorkspaceFile(
          project.id,
          file,
          currentPath + (file.webkitRelativePath || file.name),
          { silent: [409] }
        )
        .catch(() => {})
    )
    await Promise.all(uploads)
    // Broadcast: refreshes this table (own listener), the workspace rail and
    // any chat file cards.
    dispatchWorkspaceChanged()
  }

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

  // Download a row: a file fetches its bytes, a folder is zipped automatically.
  const handleDownload = async (path: string) => {
    try {
      await downloadWorkspacePath(project.id, path, files ?? [])
    } catch (err) {
      // An empty folder didn't fail, it just has nothing in it — same notice the
      // download-all button gives, so the two agree on that situation.
      if (err instanceof DownloadEmptyError) {
        message.warning(t.workspace.downloadEmpty)
        return
      }
      message.error(downloadErrorText(t, err))
    }
  }

  const addMenu: MenuProps = {
    items: [
      // First, before the uploads: creating an empty entry is the one that needs
      // nothing from the user's disk. Both land in the folder currently being
      // browsed — the same place the uploads below them go. The name is typed in
      // the rail's tree, which these open, so a file is made the same way here
      // as it is there.
      {
        key: 'new-file',
        label: t.workspace.newFile,
        onClick: () => onNewEntry(currentPath, 'file')
      },
      {
        key: 'new-folder',
        label: t.workspace.newFolder,
        onClick: () => onNewEntry(currentPath, 'folder')
      },
      // Made here vs. taken from the user's disk: two different errands.
      { type: 'divider' },
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

  // Compute visible files at current path level
  // Include explicit items + virtual folders derived from nested paths
  const visibleFiles = (() => {
    const allFiles = files ?? []
    const directItems: WorkspaceFile[] = []
    const virtualFolderNames = new Set<string>()

    for (const f of allFiles) {
      if (!f.path.startsWith(currentPath)) continue
      const relativePath = f.path.slice(currentPath.length)
      if (!relativePath) continue
      if (!relativePath.includes('/')) {
        // Direct child
        directItems.push(f)
      } else {
        // Nested — extract the first segment as a virtual folder
        const folderName = relativePath.split('/')[0]
        virtualFolderNames.add(folderName)
      }
    }

    // Add virtual folders that don't already have an explicit folder entry
    const existingNames = new Set(
      directItems.map((f) => f.path.slice(currentPath.length))
    )
    for (const name of virtualFolderNames) {
      if (!existingNames.has(name)) {
        directItems.push({
          project_id: project.id,
          path: currentPath + name,
          kind: 'folder',
          size: 0,
          updated_at: new Date().toISOString()
        })
      }
    }

    // Sort: folders first, then files; within each group sort by name alphabetically
    directItems.sort((a, b) => {
      const aIsFolder = a.kind === 'folder' ? 0 : 1
      const bIsFolder = b.kind === 'folder' ? 0 : 1
      if (aIsFolder !== bIsFolder) return aIsFolder - bIsFolder
      const aName = a.path.slice(currentPath.length).toLowerCase()
      const bName = b.path.slice(currentPath.length).toLowerCase()
      return aName.localeCompare(bName)
    })

    return directItems
  })()

  // Find latest updated_at from visible files
  const lastEdited =
    visibleFiles.length > 0
      ? visibleFiles.reduce((latest, f) =>
          new Date(f.updated_at) > new Date(latest.updated_at) ? f : latest
        ).updated_at
      : null

  // Breadcrumb segments
  const pathSegments = currentPath ? currentPath.split('/').filter(Boolean) : []

  const navigateToSegment = (index: number) => {
    if (index < 0) {
      setCurrentPath('')
    } else {
      setCurrentPath(pathSegments.slice(0, index + 1).join('/') + '/')
    }
  }

  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr)
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}.${pad(d.getMonth() + 1)}.${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  }

  const formatSize = (bytes: number) => {
    if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)}G`
    if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)}M`
    if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(1)}K`
    return `${bytes}B`
  }

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

      {files === null ? (
        <DeferredSkeleton className="min-h-0 flex-1 rounded-xl border border-msa-line-1 overflow-hidden">
          {/* Info bar — mirrors the real workspace info bar */}
          <div className="flex items-center justify-between px-5 py-3.5 bg-msa-fill-2 border-b border-msa-line-1">
            <Skeleton.Input active size="small" style={{ width: 180 }} />
            <Skeleton.Input active size="small" style={{ width: 120 }} />
          </div>
          {/* Rows — mirror the file table columns:
              icon + name on the left, size · date · actions on the right. */}
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="flex items-center gap-3 px-2 py-3 border-b border-msa-line-1 last:border-b-0"
            >
              <Skeleton.Avatar active size={16} shape="square" />
              <Skeleton.Input active size="small" style={{ width: 220 }} />
              <div className="ml-auto flex items-center gap-8 pr-2">
                <Skeleton.Input active size="small" style={{ width: 48 }} />
                <Skeleton.Input active size="small" style={{ width: 88 }} />
                <Skeleton.Input active size="small" style={{ width: 72 }} />
              </div>
            </div>
          ))}
        </DeferredSkeleton>
      ) : files.length > 0 ? (
        <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-msa-line-1 overflow-hidden">
          {/* Info bar */}
          <div className="flex shrink-0 items-center justify-between px-5 py-3.5 bg-msa-fill-2 border-b border-msa-line-1">
            <span className="text-sm text-msa-text-3">
              {t.workspace.lastEdited}
              {lastEdited && formatDate(lastEdited)}
            </span>
            <Space size={12}>
              <Tooltip title={t.workspace.refresh}>
                <Button
                  size="small"
                  type="text"
                  icon={<RefreshIcon className="h-4 w-4" />}
                  onClick={loadFiles}
                />
              </Tooltip>
              <Dropdown
                menu={addMenu}
                trigger={['hover']}
                onOpenChange={setAddMenuOpen}
              >
                <Button size="small" type="text">
                  {t.workspace.addFile}
                  <CaretDownIcon
                    className={`ml-1 h-1.5 w-1.5 transition-transform duration-200 ${
                      addMenuOpen ? 'rotate-180' : ''
                    }`}
                  />
                </Button>
              </Dropdown>
              <Button
                size="small"
                icon={<DownloadIcon className="h-4 w-4" />}
                loading={downloadingAll}
                disabled={!files || files.length === 0}
                onClick={handleDownloadAll}
              >
                {t.workspace.downloadAll}
              </Button>
            </Space>
          </div>

          {/* Breadcrumb */}
          {currentPath && (
            <div className="flex shrink-0 items-center gap-1.5 px-5 py-2.5 text-sm border-b border-msa-line-1">
              <button
                type="button"
                className="text-msa-text-brand1 hover:underline bg-transparent border-none cursor-pointer p-0"
                onClick={() => navigateToSegment(-1)}
              >
                root
              </button>
              {pathSegments.map((seg, i) => (
                <span key={i} className="flex items-center gap-1.5">
                  <span className="text-msa-text-3">/</span>
                  {i < pathSegments.length - 1 ? (
                    <button
                      type="button"
                      className="text-msa-text-brand1 hover:underline bg-transparent border-none cursor-pointer p-0"
                      onClick={() => navigateToSegment(i)}
                    >
                      {seg}
                    </button>
                  ) : (
                    <span className="text-msa-text-1 font-medium">{seg}</span>
                  )}
                </span>
              ))}
            </div>
          )}

          {/* File table (only this area scrolls; info bar + breadcrumb stay
              fixed above it) */}
          <div className="min-h-0 flex-1 overflow-y-auto">
            <Table
              dataSource={visibleFiles}
              rowKey="path"
              showHeader={false}
              pagination={false}
              size="middle"
              className="pov-table-no-last-border"
              locale={{
                emptyText: (
                  <EmptyState size="sm" description={t.workspace.empty} />
                )
              }}
              columns={[
                {
                  dataIndex: 'path',
                  render: (_: string, record: WorkspaceFile) => {
                    const displayName = record.path.slice(currentPath.length)
                    return (
                      <span className="flex items-center gap-3">
                        {record.kind === 'folder' ? (
                          <FolderIcon className="h-4 w-4" />
                        ) : (
                          <FileTypeIcon
                            name={displayName}
                            className="h-4 w-4"
                          />
                        )}
                        {record.kind === 'folder' ? (
                          <button
                            type="button"
                            className="text-sm text-msa-text-1 hover:text-msa-text-brand1 bg-transparent border-none cursor-pointer p-0 text-left"
                            onClick={() => setCurrentPath(record.path + '/')}
                          >
                            {displayName}
                          </button>
                        ) : (
                          /* Same affordance as a folder row: a file opens its
                             preview instead of navigating into it. */
                          <button
                            type="button"
                            className="text-sm text-msa-text-1 hover:text-msa-text-brand1 bg-transparent border-none cursor-pointer p-0 text-left"
                            onClick={() => onOpenFile(record.path)}
                          >
                            {displayName}
                          </button>
                        )}
                      </span>
                    )
                  }
                },
                {
                  dataIndex: 'size',
                  width: 100,
                  render: (size: number) => (
                    <span className="text-sm text-msa-text-1">
                      {formatSize(size)}
                    </span>
                  )
                },
                {
                  dataIndex: 'updated_at',
                  width: 140,
                  render: (date: string) => (
                    <span className="text-sm text-msa-text-3">
                      {getRelativeTime(date, t)}
                    </span>
                  )
                },
                {
                  key: 'actions',
                  width: 120,
                  render: (_: unknown, record: WorkspaceFile) => (
                    <Space size={16}>
                      <button
                        type="button"
                        className="text-sm text-msa-text-brand1 hover:underline bg-transparent border-none cursor-pointer p-0"
                        onClick={() => handleDownload(record.path)}
                      >
                        {t.workspace.download}
                      </button>
                      <Popconfirm
                        title={`${t.workspace.deleteConfirm}${record.kind === 'folder' ? t.workspace.folderLabel : t.workspace.fileLabel} ${record.path.slice(currentPath.length)}?`}
                        onConfirm={async () => {
                          if (record.kind === 'folder') {
                            // Delete all files under this folder
                            const prefix = record.path + '/'
                            const children = (files ?? []).filter((f) =>
                              f.path.startsWith(prefix)
                            )
                            await Promise.all(
                              children.map((f) =>
                                api
                                  .deleteWorkspaceFile(project.id, f.path, {
                                    silent: true
                                  })
                                  .catch(() => {})
                              )
                            )
                          }
                          await api
                            .deleteWorkspaceFile(project.id, record.path)
                            .catch(() => {})
                          dispatchWorkspaceChanged()
                        }}
                        okText={t.workspace.delete}
                        cancelText={t.workspace.cancel}
                      >
                        <button
                          type="button"
                          className="text-sm text-msa-text-brand1 hover:underline bg-transparent border-none cursor-pointer p-0"
                        >
                          {t.workspace.delete}
                        </button>
                      </Popconfirm>
                    </Space>
                  )
                }
              ]}
            />
          </div>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-msa-line-1 overflow-hidden">
          {/* Info bar */}
          <div className="flex shrink-0 items-center justify-between px-5 py-3.5 bg-msa-fill-2 border-b border-msa-line-1">
            <span className="text-sm text-msa-text-3" />
            <Space size={12}>
              <Tooltip title={t.workspace.refresh}>
                <Button
                  size="small"
                  type="text"
                  icon={<RefreshIcon className="h-4 w-4" />}
                  onClick={loadFiles}
                />
              </Tooltip>
              <Dropdown
                menu={addMenu}
                trigger={['hover']}
                onOpenChange={setAddMenuOpen}
              >
                <Button size="small" type="text">
                  {t.workspace.addFile}
                  <CaretDownIcon
                    className={`ml-1 h-1.5 w-1.5 transition-transform duration-200 ${
                      addMenuOpen ? 'rotate-180' : ''
                    }`}
                  />
                </Button>
              </Dropdown>
            </Space>
          </div>
          <div className="flex min-h-0 flex-1 items-center justify-center py-16">
            <EmptyState size="lg" description={t.workspace.empty} />
          </div>
        </div>
      )}
    </div>
  )
}
