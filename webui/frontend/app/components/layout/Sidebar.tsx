import { App, Dropdown, Input, Modal, Popover, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import { IconButton } from '~/components/common/IconButton'
import { useEffect, useMemo, useState } from 'react'
import logoImg from '~/assets/images/logo.png'
import {
  NavLink,
  useLocation,
  useNavigate,
  useRevalidator,
  useRouteLoaderData
} from 'react-router'
import { MsaButton } from '~/components/common/MsaButton'
import { NewProjectModal } from '~/components/project/NewProjectModal'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import { usePresence } from '~/lib/presenceContext'
import { useUrlPath } from '~/lib/useUrlPath'
import type { Project, Session } from '~/lib/types'
import SidebarToggleIcon from '~/assets/icons/sidebar-toggle.svg?react'
import McpIcon from '~/assets/icons/mcp.svg?react'
import SkillIcon from '~/assets/icons/skill.svg?react'
import SettingsIcon from '~/assets/icons/settings.svg?react'
import NewChatIcon from '~/assets/icons/new-chat.svg?react'
import MoreChatsIcon from '~/assets/icons/more-chats.svg?react'
import AddIcon from '~/assets/icons/add.svg?react'
import NewProjectIcon from '~/assets/icons/new-project.svg?react'
import MoreIcon from '~/assets/icons/more.svg?react'
import ExpandIcon from '~/assets/icons/expand.svg?react'
import SpinnerIcon from '~/assets/icons/generating.svg?react'

interface AppLoaderData {
  projects: Project[]
  sessions: Session[]
}

const DEFAULT_PROJECT_ID = 'default'

interface SidebarProps {
  collapsed?: boolean
  onCollapse?: () => void
  onExpand?: () => void
  onNavigate?: () => void
}

export function Sidebar({
  collapsed = false,
  onCollapse,
  onExpand,
  onNavigate
}: SidebarProps) {
  const { t } = useT()
  const navigate = useNavigate()
  const revalidator = useRevalidator()
  const data = useRouteLoaderData('layouts/app') as AppLoaderData | undefined
  const projects = data?.projects ?? []
  const sessions = data?.sessions ?? []

  // Project modal state
  const [projectModalOpen, setProjectModalOpen] = useState(false)
  const [editingProject, setEditingProject] = useState<Project | null>(null)

  const openCreateProject = () => {
    setEditingProject(null)
    setProjectModalOpen(true)
  }

  const openEditProject = (p: Project) => {
    setEditingProject(p)
    setProjectModalOpen(true)
  }

  const sessionsByProject = useMemo(() => {
    const map = new Map<string, Session[]>()
    for (const s of sessions) {
      const pid = s.project_id ?? DEFAULT_PROJECT_ID
      const list = map.get(pid)
      if (list) list.push(s)
      else map.set(pid, [s])
    }
    return map
  }, [sessions])

  const orderedProjects = useMemo(() => {
    const def = projects.filter((p) => p.is_default)
    const named = projects.filter((p) => !p.is_default)
    return [...def, ...named]
  }, [projects])

  const openNewChat = () => {
    navigate('/')
    onNavigate?.()
  }

  return (
    <>
      <aside
        className={`group/sidebar flex h-full shrink-0 flex-col overflow-hidden bg-msa-bg-2 transition-[width] duration-200 ease-out ${
          collapsed
            ? 'w-[72px] items-center gap-3 py-3'
            : 'w-full gap-3 p-3 md:w-72'
        }`}
      >
        {collapsed ? (
          <>
            {/* Brand / expand */}
            <div className="shrink-0">
              <Tooltip title={t.nav.expand} placement="right">
                <div
                  className="relative flex h-10 w-10 cursor-pointer items-center justify-center"
                  onClick={onExpand}
                >
                  <div className="flex h-9 w-9 items-center justify-center transition-opacity group-hover/sidebar:opacity-0">
                    <img
                      src={logoImg}
                      alt="MS-Agent"
                      className="h-9 w-9 select-none"
                      draggable={false}
                    />
                  </div>
                  <div className="absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover/sidebar:opacity-100">
                    <IconButton
                      variant="outlined"
                      size="lg"
                      stopPropagation={false}
                      icon={
                        <SidebarToggleIcon className="h-5 w-5 rotate-180" />
                      }
                      className="rounded-2xl"
                    />
                  </div>
                </div>
              </Tooltip>
            </div>

            {/* Group card: new chat + MCP + Skill */}
            <div className="flex shrink-0 flex-col items-center gap-1 rounded-[12px] p-[4px] bg-msa-fill-0">
              <Tooltip title={t.nav.newChatShort} placement="right">
                <IconButton
                  variant="ghost"
                  onClick={openNewChat}
                  icon={<NewChatIcon className="h-5 w-5" />}
                  className="rounded-[12px] !bg-msa-fill-3 text-msa-text-1 hover:!bg-msa-text-1 hover:text-msa-fill-0"
                />
              </Tooltip>
              <div className="my-0.5 h-px w-6 bg-msa-line-1" />
              <Tooltip title={t.nav.mcpManage} placement="right">
                <NavLink
                  to="/settings/mcp-skills?tab=mcps"
                  onClick={onNavigate}
                  className="block"
                >
                  <IconButton
                    variant="ghost"
                    stopPropagation={false}
                    icon={<McpIcon className="h-5 w-5" />}
                    className="rounded-[12px] hover:!bg-msa-fill-3 !text-msa-text-1"
                  />
                </NavLink>
              </Tooltip>
              <Tooltip title={t.nav.skillManage} placement="right">
                <NavLink
                  to="/settings/mcp-skills?tab=skills"
                  onClick={onNavigate}
                  className="block"
                >
                  <IconButton
                    variant="ghost"
                    stopPropagation={false}
                    icon={<SkillIcon className="h-5 w-5" />}
                    className="rounded-[12px] hover:!bg-msa-fill-3 !text-msa-text-1"
                  />
                </NavLink>
              </Tooltip>
            </div>

            {/* Projects popover */}

            <CollapsedProjectList
              projects={orderedProjects}
              sessionsByProject={sessionsByProject}
              onNavigate={onNavigate}
            />

            {/* Spacer pushes settings to the bottom */}
            <div className="min-h-0 flex-1" />

            {/* Settings */}

            <Tooltip title={t.nav.agentSettings} placement="right">
              <NavLink
                to="/settings"
                onClick={onNavigate}
                className="flex shrink-0 flex-col items-center rounded-[12px] bg-msa-fill-0.5 w-[40px] h-[40px] bg-msa-fill-0 hover:bg-msa-fill-3"
              >
                <IconButton
                  variant="ghost"
                  stopPropagation={false}
                  icon={<SettingsIcon className="h-5 w-5" />}
                  className="w-full h-full"
                />
              </NavLink>
            </Tooltip>
          </>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col gap-3">
            {/* Top card: brand + new chat + nav shortcuts */}
            <div className="shrink-0 rounded-[12px] bg-msa-fill-3 p-[8px]">
              <div className="flex items-center gap-2">
                {/* Logo / collapse toggle: on sidebar hover the logo morphs
                    into the collapse icon (same pattern as collapsed mode). */}
                <div
                  className="relative flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-2xl bg-msa-fill-0"
                  onClick={onCollapse}
                >
                  <img
                    src={logoImg}
                    alt="MS-Agent"
                    className="h-8 w-8 select-none transition-opacity group-hover/sidebar:opacity-0"
                    draggable={false}
                  />
                  <div className="absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover/sidebar:opacity-100">
                    <SidebarToggleIcon className="h-5 w-5 text-msa-text-2" />
                  </div>
                </div>
                <MsaButton
                  variant="primary"
                  block
                  icon={<NewChatIcon className="h-5 w-5" />}
                  onClick={openNewChat}
                  className="!flex !items-center !justify-center !gap-2 !rounded-2xl !px-4 !py-2.5 !h-auto !font-medium !text-sm hover:!opacity-90"
                >
                  <span>{t.nav.newChatShort}</span>
                </MsaButton>
              </div>
              {/* Nav shortcuts in a white sub-card with inset dividers */}
              <div className="mt-2.5 overflow-hidden rounded-2xl bg-msa-fill-0 p-2">
                <SidebarNavItem
                  to="/settings/mcp-skills?tab=mcps"
                  label={t.nav.mcpManage}
                  icon={<McpIcon className="h-5 w-5" />}
                  onNavigate={onNavigate}
                />
                <div className="mx-3 my-1 h-px bg-msa-line-1" />
                <SidebarNavItem
                  to="/settings/mcp-skills?tab=skills"
                  label={t.nav.skillManage}
                  icon={<SkillIcon className="h-5 w-5" />}
                  onNavigate={onNavigate}
                />
              </div>
            </div>

            {/* Projects card */}
            <div className="flex min-h-0 flex-1 flex-col rounded-2xl border border-msa-line-1 bg-msa-fill-0 p-2">
              <div className="flex shrink-0 items-center justify-between px-2 py-1">
                <span className="text-sm font-medium text-msa-text-2">
                  {t.nav.projectsTitle}
                </span>
                <Tooltip title={t.nav.newProject}>
                  <IconButton
                    variant="filled"
                    size="sm"
                    onClick={openCreateProject}
                    icon={<NewProjectIcon className="h-4 w-4" />}
                    className="text-msa-text-2 hover:bg-msa-fill-2"
                  />
                </Tooltip>
              </div>
              <div className="mt-1 min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden">
                {orderedProjects.length === 0 ? (
                  <RecentEmpty />
                ) : (
                  <div className="space-y-1">
                    {orderedProjects.map((p) => (
                      <ProjectGroup
                        key={p.id}
                        project={p}
                        sessions={sessionsByProject.get(p.id) ?? []}
                        onNavigate={onNavigate}
                        onEditProject={openEditProject}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Settings card */}

            <SidebarNavItem
              to="/settings"
              label={t.nav.agentSettings}
              icon={<SettingsIcon className="h-5 w-5" />}
              onNavigate={onNavigate}
              className="bg-msa-fill-0 rounded-[12px] !text-sm !font-normal hover:bg-msa-fill-4 hover:!text-msa-text-brand1"
            />
          </div>
        )}
      </aside>

      {/* Project create/edit modal */}
      <NewProjectModal
        open={projectModalOpen}
        project={editingProject ?? undefined}
        onClose={() => setProjectModalOpen(false)}
        onCreated={(p) => {
          setProjectModalOpen(false)
          revalidator.revalidate()
          navigate(`/projects/${p.id}`)
        }}
        onUpdated={() => {
          setProjectModalOpen(false)
          revalidator.revalidate()
        }}
      />
    </>
  )
}

function SidebarNavItem({
  to,
  label,
  icon,
  onNavigate,
  className
}: {
  to: string
  label: string
  icon: React.ReactNode
  onNavigate?: () => void
  className?: string
}) {
  return (
    <NavLink
      to={to}
      onClick={onNavigate}
      className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] font-medium text-msa-text-1 transition-colors hover:bg-msa-fill-2 ${className}`}
    >
      <span className="shrink-0 flex items-center">{icon}</span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
    </NavLink>
  )
}

function CollapsedProjectList({
  projects,
  sessionsByProject,
  onNavigate
}: {
  projects: Project[]
  sessionsByProject: Map<string, Session[]>
  onNavigate?: () => void
}) {
  const content = (
    <div className="max-h-[60vh] w-56 overflow-y-auto py-1">
      {projects.map((p) => (
        <CollapsedProjectGroup
          key={p.id}
          project={p}
          sessions={sessionsByProject.get(p.id) ?? []}
          onNavigate={onNavigate}
        />
      ))}
    </div>
  )

  return (
    <div className="flex shrink-0 flex-col items-center justify-center rounded-[12px] bg-msa-fill-0.5 w-[40px] h-[40px] bg-msa-fill-0 hover:bg-msa-fill-3">
      <Popover
        content={content}
        placement="rightTop"
        trigger="hover"
        arrow={false}
        overlayInnerStyle={{ padding: 4 }}
      >
        <IconButton
          variant="ghost"
          size="sm"
          icon={<MoreChatsIcon className="h-5 w-5" />}
          stopPropagation={false}
        />
      </Popover>
    </div>
  )
}

/** Collapsed sidebar popover: single project group with expand/collapse */
function CollapsedProjectGroup({
  project,
  sessions,
  onNavigate
}: {
  project: Project
  sessions: Session[]
  onNavigate?: () => void
}) {
  const location = useLocation()
  const navigate = useNavigate()
  const { running } = usePresence()
  const isActiveProject = location.pathname.startsWith(
    `/projects/${project.id}`
  )
  const [open, setOpen] = useState(isActiveProject)

  const projectName = project.is_default ? project.name : project.name

  return (
    <div>
      {/* Project header */}
      <div
        className="flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-1.5 hover:bg-msa-fill-2"
        onClick={() => setOpen(!open)}
      >
        <span className="flex h-4 w-4 shrink-0 items-center justify-center text-[10px] text-msa-neutral-3">
          <ExpandIcon
            className={`h-3 w-3 transition-transform ${open ? '' : 'rotate-180'}`}
          />
        </span>
        <span className="min-w-0 flex-1 truncate text-sm font-semibold text-msa-text-1">
          {projectName}
        </span>
        <span className="shrink-0 text-xs tabular-nums text-msa-text-2">
          {sessions.length}
        </span>
      </div>
      {/* Sessions */}
      {open && sessions.length > 0 && (
        <div className="py-0.5">
          {sessions.map((s) => {
            const isActive = location.pathname.includes(`/sessions/${s.id}`)
            return (
              <div
                key={s.id}
                className={`group flex cursor-pointer items-center gap-1 rounded-md px-3 py-1.5 text-sm transition-colors ${
                  isActive
                    ? 'bg-msa-fill-3 font-medium text-msa-text-1'
                    : 'text-msa-text-2 hover:bg-msa-fill-2'
                }`}
                onClick={() => {
                  navigate(`/projects/${project.id}/sessions/${s.id}`)
                  onNavigate?.()
                }}
              >
                <span className="min-w-0 flex-1 truncate">{s.title}</span>
                {(running.has(s.id) || s.running) && (
                  <SpinnerIcon className="h-3 w-3 shrink-0 animate-spin text-msa-text-brand1" />
                )}
                {isActive && (
                  <span className="shrink-0 text-msa-text-3">
                    <MoreIcon className="h-3.5 w-3.5" />
                  </span>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function RecentEmpty() {
  const { t } = useT()
  return (
    <div className="flex flex-col items-center gap-2 px-4 pt-10 text-center">
      <NewChatIcon className="h-6 w-6 opacity-40" />
      <p className="text-xs text-msa-text-3">{t.nav.recentEmpty}</p>
    </div>
  )
}

function ProjectGroup({
  project,
  sessions,
  onNavigate,
  onEditProject
}: {
  project: Project
  sessions: Session[]
  onNavigate?: () => void
  onEditProject?: (p: Project) => void
}) {
  const { t } = useT()
  const { modal } = App.useApp()
  const location = useLocation()
  const navigate = useNavigate()
  const revalidator = useRevalidator()

  const isActiveProject = location.pathname.startsWith(
    `/projects/${project.id}`
  )
  const [open, setOpen] = useState(isActiveProject || project.is_default)

  useEffect(() => {
    if (isActiveProject) setOpen(true)
  }, [isActiveProject])

  // All sessions are shown directly (no secondary fold / "show all" toggle).
  const visibleSessions = sessions

  const handleDeleteProject = () => {
    modal.confirm({
      title: t.sidebar.deleteProject,
      content: t.sidebar.confirmDeleteProject,
      okText: t.sidebar.confirmOk,
      cancelText: t.sidebar.confirmCancel,
      okButtonProps: { danger: true },
      onOk: async () => {
        await api.deleteProject(project.id)
        revalidator.revalidate()
        if (isActiveProject) navigate('/')
      }
    })
  }

  const projectMenu: MenuProps = {
    items: [
      {
        key: 'edit',
        label: t.sidebar.editProject,
        onClick: () => {
          onEditProject?.(project)
        }
      },
      ...(!project.is_default
        ? [
            {
              key: 'delete',
              label: t.sidebar.deleteProject,
              danger: true,
              onClick: handleDeleteProject
            }
          ]
        : [])
    ]
  }

  const projectName = project.name

  return (
    <div>
      {/* Project header row */}
      <div
        className="group flex cursor-pointer items-center gap-1.5 rounded-lg px-2 py-2 transition-colors hover:bg-msa-fill-2"
        onClick={() => setOpen(!open)}
      >
        {/* Chevron */}
        <span
          className="flex h-4 w-4 shrink-0 items-center justify-center text-[10px] text-msa-text-3"
          onClick={(e) => {
            e.stopPropagation()
            setOpen(!open)
          }}
        >
          <ExpandIcon
            className={`h-4 w-4 transition-transform ${open ? '' : 'rotate-180'}`}
          />
        </span>
        {/* Project name — click to enter project detail */}
        <span
          className={`min-w-0 flex-1 truncate text-sm font-semibold ${
            isActiveProject ? 'text-msa-purple-5' : 'text-msa-text-1'
          }`}
          title={projectName}
          onClick={(e) => {
            e.stopPropagation()
            navigate(`/projects/${project.id}`)
            onNavigate?.()
          }}
        >
          {projectName}
        </span>
        {/* Count */}
        <span className="shrink-0 rounded-md bg-white/80 px-1.5 py-0.5 text-xs tabular-nums text-msa-text-2 dark:bg-msa-fill-2">
          {sessions.length}
        </span>
        {/* Add session */}
        <Tooltip title={t.nav.newChat}>
          <IconButton
            icon={<AddIcon className="h-3.5 w-3.5" />}
            variant="ghost"
            size="xs"
            className="!shrink-0 !opacity-0 !transition-opacity hover:!text-msa-purple-5 group-hover:!opacity-100"
            onClick={() => {
              navigate(`/projects/${project.id}/new`)
              onNavigate?.()
            }}
          />
        </Tooltip>
        {/* More menu — extra wrapper needed because Dropdown close events bypass the trigger button */}
        <span onClick={(e) => e.stopPropagation()}>
          <Dropdown
            menu={projectMenu}
            trigger={['click']}
            placement="bottomRight"
          >
            <Tooltip title={t.resources.more}>
              <IconButton
                icon={<MoreIcon className="h-3.5 w-3.5" />}
                variant="ghost"
                size="xs"
                className="!shrink-0 !opacity-0 !transition-opacity hover:!text-msa-purple-5 group-hover:!opacity-100"
              />
            </Tooltip>
          </Dropdown>
        </span>
      </div>

      {/* Session list */}
      {open && (
        <div className="space-y-0.5 py-1">
          {sessions.length === 0 ? (
            <p className="py-2 text-center text-xs text-msa-text-3">
              {t.widgets.empty}
            </p>
          ) : (
            <>
              {visibleSessions.map((s) => (
                <SessionItem
                  key={s.id}
                  session={s}
                  projectId={project.id}
                  onNavigate={onNavigate}
                />
              ))}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function SessionItem({
  session,
  projectId,
  onNavigate
}: {
  session: Session
  projectId: string
  onNavigate?: () => void
}) {
  const { t } = useT()
  const { modal } = App.useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const revalidator = useRevalidator()
  const { running } = usePresence()
  const isRunning = running.has(session.id) || !!session.running
  const [renameOpen, setRenameOpen] = useState(false)
  const [renameValue, setRenameValue] = useState('')

  const handleRename = async () => {
    const title = renameValue.trim()
    if (!title || title === session.title) {
      setRenameOpen(false)
      return
    }
    await api.updateSession(session.id, { title })
    revalidator.revalidate()
    setRenameOpen(false)
  }

  const handleDeleteSession = () => {
    modal.confirm({
      title: t.sidebar.deleteSession,
      content: t.sidebar.confirmDeleteSession,
      okText: t.sidebar.confirmOk,
      cancelText: t.sidebar.confirmCancel,
      okButtonProps: { danger: true },
      onOk: async () => {
        await api.deleteSession(session.id)
        revalidator.revalidate()
        const isActive = location.pathname.includes(`/sessions/${session.id}`)
        if (isActive) navigate(`/projects/${projectId}`)
      }
    })
  }

  const sessionMenu: MenuProps = {
    items: [
      {
        key: 'rename',
        label: t.sidebar.renameSession,
        onClick: () => {
          setRenameValue(session.title)
          setRenameOpen(true)
        }
      },
      {
        key: 'delete',
        label: t.sidebar.deleteSession,
        danger: true,
        onClick: handleDeleteSession
      }
    ]
  }

  // Bind the active highlight to the real browser URL (not NavLink's router
  // `isActive`), so a session opened via the chat's mid-stream replaceState is
  // highlighted immediately — the router location can lag the address bar.
  const to = `/projects/${projectId}/sessions/${session.id}`
  const active = useUrlPath() === to
  return (
    <>
      <NavLink
        to={to}
        end
        onClick={onNavigate}
        className={`group flex items-center gap-1 truncate rounded-lg pl-8 pr-2.5 py-2 text-sm transition-colors ${
          active
            ? 'bg-msa-fill-3 font-medium text-msa-text-1'
            : 'text-msa-text-2 hover:bg-msa-fill-2'
        }`}
        title={session.title}
      >
        <span className="min-w-0 flex-1 truncate">{session.title}</span>
        {isRunning && (
          <SpinnerIcon className="h-3 w-3 shrink-0 animate-spin text-msa-text-brand1" />
        )}
        <span
          onClick={(e) => {
            e.stopPropagation()
            e.preventDefault()
          }}
        >
          <Dropdown
            menu={sessionMenu}
            trigger={['click']}
            placement="bottomRight"
          >
            <IconButton
              icon={<MoreIcon className="h-3.5 w-3.5" />}
              variant="ghost"
              size="xs"
              className="!shrink-0 !opacity-0 !transition-opacity group-hover:!opacity-100"
            />
          </Dropdown>
        </span>
      </NavLink>
      <Modal
        open={renameOpen}
        title={t.sidebar.renameSession}
        okText={t.workspace.save}
        cancelText={t.workspace.cancel}
        onOk={handleRename}
        onCancel={() => setRenameOpen(false)}
        destroyOnHidden
      >
        <Input
          autoFocus
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          onPressEnter={handleRename}
        />
      </Modal>
    </>
  )
}
