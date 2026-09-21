import { App, Dropdown, Input, Modal, Popover, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import { IconButton } from '~/components/common/IconButton'
import { EmptyState, EmptyStateAction } from '~/components/common/EmptyState'
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
import { ScrollArea } from '~/components/common/ScrollArea'
import { NewProjectModal } from '~/components/project/NewProjectModal'
import { api } from '~/lib/api'
import {
  DownloadUnauthorizedError,
  downloadSessionExport,
  type SessionExportDetail,
  type SessionExportFormat
} from '~/lib/download'
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
import GithubIcon from '~/assets/icons/github.svg?react'
import SpinnerIcon from '~/assets/icons/generating.svg?react'

const REPO_URL = 'https://github.com/modelscope/ms-agent'

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
  const location = useLocation()
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

  // Rendered in the order the API returns (plain creation order). The default
  // project is no longer pinned to the top — it behaves like any other project.
  const orderedProjects = projects

  // A fresh load usually lands somewhere that belongs to no project (home,
  // settings), so every group renders collapsed and the list reads as empty
  // even with dozens of sessions behind it. Expand the first project that
  // actually HAS sessions — an empty one would just swap one blank list for
  // another. Strictly a fallback: when the route already points into a project
  // that group expands itself, and opening a second one would bury it.
  const autoOpenProjectId = useMemo(() => {
    const insideAProject = orderedProjects.some((p) =>
      location.pathname.startsWith(`/projects/${p.id}`)
    )
    if (insideAProject) return null
    return (
      orderedProjects.find(
        (p) => (sessionsByProject.get(p.id)?.length ?? 0) > 0
      )?.id ?? null
    )
  }, [orderedProjects, sessionsByProject, location.pathname])

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
                  className="relative flex h-10 w-10 cursor-pointer items-center justify-center rounded-2xl bg-msa-fill-0"
                  onClick={onExpand}
                >
                  <div className="flex h-9.5 w-9.5 items-center justify-center transition-opacity group-hover/sidebar:opacity-0">
                    <img
                      src={logoImg}
                      alt="MS-Agent"
                      className="h-9.5 w-9.5 select-none"
                      draggable={false}
                    />
                  </div>

                  <div className="absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover/sidebar:opacity-100">
                    <IconButton
                      variant="filled"
                      size="lg"
                      stopPropagation={false}
                      icon={
                        <SidebarToggleIcon className="h-6 w-6 rotate-180 text-msa-text-2" />
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
              onEditProject={openEditProject}
            />

            {/* Spacer pushes settings to the bottom */}
            <div className="min-h-0 flex-1" />

            {/* Settings + repo credit: one card, same as expanded mode */}
            <div className="shrink-0 rounded-[12px] bg-msa-fill-3 w-[40px]">
              <Tooltip title={t.nav.agentSettings} placement="right">
                <NavLink
                  to="/settings"
                  onClick={onNavigate}
                  className="flex flex-col items-center w-[40px] h-[40px] rounded-[12px] bg-msa-fill-0 transition-shadow hover:shadow-[0px_2px_32px_0px_rgba(39,37,76,0.08)]"
                >
                  <IconButton
                    variant="ghost"
                    stopPropagation={false}
                    icon={<SettingsIcon className="h-5 w-5" />}
                    className="w-full h-full"
                  />
                </NavLink>
              </Tooltip>
              <Tooltip title={t.nav.github} placement="right">
                <a
                  href={REPO_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="flex h-10 w-full items-center justify-center text-msa-text-3 transition-colors hover:text-msa-text-1"
                >
                  <GithubIcon className="h-5 w-5" />
                </a>
              </Tooltip>
            </div>
          </>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col gap-3">
            {/* Top card: brand + new chat + nav shortcuts */}
            <div className="shrink-0 rounded-[20px] bg-msa-fill-3 p-[8px]">
              <div className="flex items-center gap-2">
                {/* Logo / collapse toggle: on sidebar hover the logo morphs
                    into the collapse icon (same pattern as collapsed mode). */}
                <Tooltip title={t.nav.collapse} placement="bottom">
                  <div
                    className="relative flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-2xl bg-msa-fill-0"
                    onClick={onCollapse}
                  >
                    <img
                      src={logoImg}
                      alt="MS-Agent"
                      className="h-9.5 w-9.5 select-none transition-opacity group-hover/sidebar:opacity-0"
                      draggable={false}
                    />
                    <div className="absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover/sidebar:opacity-100">
                      <SidebarToggleIcon className="h-6 w-6 text-msa-text-2" />
                    </div>
                  </div>
                </Tooltip>
                <MsaButton
                  variant="primary"
                  block
                  icon={<NewChatIcon className="h-5 w-5" />}
                  onClick={openNewChat}
                  className="!flex !items-center !justify-center !gap-2 !rounded-xl !px-4 !py-2.5 !h-auto !font-medium !text-[13px] hover:!opacity-90"
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

            {/* Projects card. The card's own `p-3` is the ONE 12px inset for
                everything inside it — the title row and the list rows carry no
                edge padding of their own, so they share a single baseline. */}
            <div className="flex min-h-0 flex-1 flex-col rounded-2xl bg-msa-fill-0 p-3">
              <div className="flex shrink-0 items-center justify-between">
                <span className="text-[13px] text-msa-text-3">
                  {t.nav.projectsTitle}
                </span>
                <Tooltip title={t.nav.newProject}>
                  <IconButton
                    variant="tonal"
                    size="sm"
                    onClick={openCreateProject}
                    icon={<NewProjectIcon className="h-5 w-5" />}
                    className="text-msa-text-2 hover:bg-msa-fill-2"
                  />
                </Tooltip>
              </div>
              {/* `-mx-3` full-bleeds the scroll box to both card borders so the
                  scrollbar sits flush right; `pad` then puts the rows back on the
                  card's own 12px inset — and holds them there whether or not the
                  scrollbar takes space (12 is where the two edges balance, see
                  ScrollArea). */}
              {/* When empty, turn the scroll box into a flex column so the empty
                  state can center with `m-auto`: a percentage `h-full` child does
                  not resolve to fill this flex-grown, overflow-auto box, which
                  left the placeholder pinned to the top. */}
              <ScrollArea
                pad={12}
                className={`mt-1 -mx-3 flex-1${
                  orderedProjects.length === 0 ? ' flex flex-col' : ''
                }`}
              >
                {orderedProjects.length === 0 ? (
                  <ProjectsEmpty onCreateProject={openCreateProject} />
                ) : (
                  <div className="space-y-1">
                    {orderedProjects.map((p) => (
                      <ProjectGroup
                        key={p.id}
                        project={p}
                        sessions={sessionsByProject.get(p.id) ?? []}
                        defaultOpen={p.id === autoOpenProjectId}
                        onNavigate={onNavigate}
                        onEditProject={openEditProject}
                      />
                    ))}
                  </div>
                )}
              </ScrollArea>
            </div>

            {/* One card wrapping both: the settings row keeps its own rounded
                corners and the credit row shows the wrapper's fill. The row
                hover lifts with a soft shadow rather than a fill change:
                `hover:!bg-msa-fill-0` cancels the base row's
                `hover:bg-msa-fill-2`, and `!transition-shadow` retargets the
                base's colour transition onto the shadow (nothing else moves). */}
            <div className="shrink-0 rounded-[12px] bg-msa-fill-3">
              <SidebarNavItem
                to="/settings"
                label={t.nav.agentSettings}
                icon={<SettingsIcon className="h-5 w-5" />}
                onNavigate={onNavigate}
                className="bg-msa-fill-0 rounded-[12px] !text-[13px] !font-normal !transition-shadow hover:!bg-msa-fill-0 hover:shadow-[0px_2px_32px_0px_rgba(39,37,76,0.08)]"
              />
              <a
                href={REPO_URL}
                target="_blank"
                rel="noreferrer"
                className="flex h-10 items-center justify-center gap-1.5 whitespace-nowrap text-xs text-msa-text-3! transition-colors hover:text-msa-text-1!"
              >
                <span>{t.nav.poweredBy}</span>
                <GithubIcon className="h-3.5 w-3.5 shrink-0" />
                <span>MS-Agent</span>
              </a>
            </div>
          </div>
        )}
      </aside>

      {/* Project create/edit modal */}
      <NewProjectModal
        open={projectModalOpen}
        project={editingProject ?? undefined}
        onClose={() => setProjectModalOpen(false)}
        onCreated={async (p) => {
          setProjectModalOpen(false)
          // Awaited before navigating: the app layout skips revalidation on a
          // route change (see its `shouldRevalidate`), and a navigation started
          // in the same tick would interrupt this refresh — leaving the brand-new
          // project missing from the list we are about to navigate into.
          await revalidator.revalidate()
          navigate(`/projects/${p.id}`)
        }}
        onUpdated={() => {
          // Deliberately not awaited, unlike create above: no navigation follows,
          // so there is nothing to sequence against. Should the user click away
          // while it is in flight, the app layout re-issues it — see its
          // `recoverInterruptedRefresh`.
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
      className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13px] font-medium text-msa-text-1 transition-colors hover:bg-msa-fill-2 ${className || ''}`}
    >
      <span className="shrink-0 flex items-center">{icon}</span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
    </NavLink>
  )
}

/** The project row's two actions (new chat + rename/delete menu), shared by the
 * expanded sidebar row and the collapsed sidebar's popover row so both offer the
 * same thing. `pinned` keeps them visible instead of hover-revealed — used on the
 * row whose project page is open, which is already highlighted. */
function ProjectRowActions({
  project,
  pinned,
  onNavigate,
  onEditProject
}: {
  project: Project
  pinned: boolean
  onNavigate?: () => void
  onEditProject?: (p: Project) => void
}) {
  const { t } = useT()
  const { modal } = App.useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const revalidator = useRevalidator()

  const handleDeleteProject = () => {
    modal.confirm({
      title: t.sidebar.deleteProject,
      content: t.sidebar.confirmDeleteProject,
      okText: t.sidebar.confirmOk,
      cancelText: t.sidebar.confirmCancel,
      okButtonProps: { danger: true },
      onOk: async () => {
        await api.deleteProject(project.id)
        // Awaited: see the create handler — a navigation in the same tick would
        // interrupt this refresh, and the route change itself no longer triggers
        // one, so the deleted project would linger in the sidebar.
        await revalidator.revalidate()
        if (location.pathname.startsWith(`/projects/${project.id}`))
          navigate('/')
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

  const actionClass = `!shrink-0 !transition-opacity hover:!text-msa-purple-5 ${
    pinned ? '' : '!opacity-0 group-hover:!opacity-100'
  }`

  return (
    <>
      <Tooltip title={t.nav.newChat}>
        <IconButton
          icon={<AddIcon className="h-4 w-4" />}
          variant="ghost"
          size="xs"
          className={actionClass}
          onClick={() => {
            navigate(`/projects/${project.id}/new`)
            onNavigate?.()
          }}
        />
      </Tooltip>
      {/* More menu — opens on hover, so no tooltip (one would just cover the
          menu it announces); the i18n label moves to `aria-label`, which is what
          keeps this icon-only button readable to screen readers.
          The wrapper still swallows clicks: hover-triggered menus ignore them,
          so without it a click on the button would fall through to the row. */}
      <span onClick={(e) => e.stopPropagation()}>
        <Dropdown
          menu={projectMenu}
          trigger={['hover']}
          placement="bottomRight"
        >
          <IconButton
            aria-label={t.resources.more}
            icon={<MoreIcon className="h-4 w-4" />}
            variant="ghost"
            size="xs"
            className={actionClass}
          />
        </Dropdown>
      </span>
    </>
  )
}

/**
 * The "finished while you were away" marker: a turn ended with nobody watching
 * and the conversation has not been opened since. Deliberately the running
 * spinner's colour at a smaller size — it takes over that exact slot once the
 * spinner disappears, and reads as "something new here", not as an error (a
 * background turn that FAILED gets the same dot: the user still has to go look).
 *
 * `label` is the tooltip, which differs between a session row ("this chat") and
 * a project row ("something in here"). Omit it on the collapsed rail's popover
 * trigger, where a tooltip would race the popover for the same hover.
 *
 * `spinnerSlot` centres the dot in a spinner-sized (12px) box. Needed wherever
 * it takes over from the spinner: equal widths keep the swap from nudging the
 * title or the actions beside it, and the box gives the 6px dot a real hover
 * target for its tooltip.
 */
function UnreadDot({
  label,
  spinnerSlot = false,
  className = ''
}: {
  label?: string
  spinnerSlot?: boolean
  className?: string
}) {
  const dot = (
    <span
      className={`h-1.5 w-1.5 shrink-0 rounded-full bg-msa-text-brand1 ${className}`}
    />
  )
  const body = spinnerSlot ? (
    <span className="flex h-3 w-3 shrink-0 items-center justify-center">
      {dot}
    </span>
  ) : (
    dot
  )
  return label ? <Tooltip title={label}>{body}</Tooltip> : body
}

function CollapsedProjectList({
  projects,
  sessionsByProject,
  onNavigate,
  onEditProject
}: {
  projects: Project[]
  sessionsByProject: Map<string, Session[]>
  onNavigate?: () => void
  onEditProject?: (p: Project) => void
}) {
  // This popover trigger is the ONLY way into any project while the sidebar is
  // collapsed, so an unread session anywhere has to surface on the icon itself
  // — dots inside the popover only exist once the user already hovered it.
  const hasUnread = projects.some((p) =>
    (sessionsByProject.get(p.id) ?? []).some((s) => s.unread)
  )
  const content = (
    // 16px on all four sides, including the popover container's own 4px.
    <ScrollArea pad={12} className="max-h-[60vh] w-56 py-3 space-y-1">
      {projects.map((p) => (
        <CollapsedProjectGroup
          key={p.id}
          project={p}
          sessions={sessionsByProject.get(p.id) ?? []}
          onNavigate={onNavigate}
          onEditProject={onEditProject}
        />
      ))}
    </ScrollArea>
  )

  return (
    <div className="relative flex shrink-0 flex-col items-center justify-center rounded-[12px] bg-msa-fill-0.5 w-[40px] h-[40px] bg-msa-fill-0 hover:bg-msa-fill-3">
      <Popover
        content={content}
        placement="rightTop"
        trigger="hover"
        arrow={false}
        styles={{
          // Match the expanded sidebar's project card surface (fill-0) instead of
          // antd's elevated default. In DARK mode `colorBgElevated` is fill-2 —
          // the very colour SessionItem paints its active row with — so the
          // highlight rendered with zero contrast and only the bolder, brighter
          // TEXT showed. (Hover, also fill-2, was invisible for the same
          // reason.) Aligning the surface is what makes the shared row component
          // actually look identical in both places, which was the point of
          // reusing it. Light mode already used fill-0 here and was unaffected.
          container: {
            padding: 4,
            background: 'var(--msa-fill-0)',
            border: '1px solid var(--msa-line-1)'
          }
        }}
      >
        <IconButton
          variant="ghost"
          size="sm"
          icon={<MoreChatsIcon className="h-5 w-5" />}
          stopPropagation={false}
        />
      </Popover>
      {/* Outside the trigger, so it never moves the icon or intercepts the
          hover that opens the popover. */}
      {hasUnread && (
        <UnreadDot className="pointer-events-none absolute right-1.5 top-1.5" />
      )}
    </div>
  )
}

/** Collapsed sidebar popover: single project group with expand/collapse */
function CollapsedProjectGroup({
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
  const location = useLocation()
  const navigate = useNavigate()
  const isActiveProject = location.pathname.startsWith(
    `/projects/${project.id}`
  )
  const isProjectPage =
    location.pathname.replace(/\/+$/, '') === `/projects/${project.id}`
  const [open, setOpen] = useState(isActiveProject)
  // Only while the group hides its rows — same rule as the expanded sidebar.
  const hasUnread = !open && sessions.some((s) => s.unread)

  const projectName = project.name

  return (
    <div>
      {/* Project header — mirrors the expanded row: the row toggles the group,
          the NAME enters the project. Without that click the collapsed sidebar
          had no way into a project's own page at all. */}
      <div
        className={`group flex cursor-pointer items-center gap-2 h-10 rounded-md px-2 transition-colors hover:bg-msa-fill-2 ${
          isProjectPage ? 'bg-msa-fill-2' : ''
        }`}
        onClick={() => setOpen(!open)}
      >
        <span className="flex h-4 w-4 shrink-0 items-center justify-center text-[10px] text-msa-neutral-3">
          <ExpandIcon
            className={`h-3.5 w-3.5 transition-transform ${open ? '' : 'rotate-180'}`}
          />
        </span>
        <div
          className="flex-1 w-0 py-2 flex items-center"
          onClick={(e) => {
            e.stopPropagation()
            navigate(`/projects/${project.id}`)
            onNavigate?.()
          }}
        >
          <span
            className={`min-w-0 truncate text-[13px] font-semibold text-msa-text-1`}
            title={projectName}
          >
            {projectName}
          </span>
          <span className="shrink-0 rounded-[12px] mx-1.5 px-1.5 py-px font-medium text-xs tabular-nums text-msa-text-1 bg-msa-fill-3">
            {sessions.length}
          </span>
          {hasUnread && <UnreadDot label={t.sidebar.unreadProject} />}
        </div>
        <ProjectRowActions
          project={project}
          pinned={isProjectPage}
          onNavigate={onNavigate}
          onEditProject={onEditProject}
        />
      </div>
      {/* Sessions — the SAME row component the expanded sidebar uses, so the
          rename/delete menu, running spinner and active highlight behave
          identically here. This popover previously hand-rolled the row and its
          "more" glyph was a bare <span> with no Dropdown and no handler, i.e. a
          decoration that looked clickable but did nothing. */}
      {open && sessions.length > 0 && (
        <div className="py-0.5">
          {sessions.map((s) => (
            <SessionItem
              key={s.id}
              session={s}
              projectId={project.id}
              onNavigate={onNavigate}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function ProjectsEmpty({ onCreateProject }: { onCreateProject: () => void }) {
  const { t } = useT()
  return (
    <EmptyState
      size="sm"
      art="box"
      className="m-auto h-full"
      description={t.nav.projectsEmpty}
      action={
        // EmptyStateAction hardcodes `h-auto px-6 py-2`, so the antd `size` prop
        // has no visible effect; shrink it with `!` overrides like the compact
        // model CTAs so the pill fits the narrow sidebar.
        <EmptyStateAction
          className="!px-4 !py-1.5 !text-xs"
          onClick={onCreateProject}
        >
          {t.nav.newProject}
        </EmptyStateAction>
      }
    />
  )
}

function ProjectGroup({
  project,
  sessions,
  defaultOpen = false,
  onNavigate,
  onEditProject
}: {
  project: Project
  sessions: Session[]
  /**
   * Start expanded even though the route points elsewhere. INITIAL only, by
   * design: the parent recomputes it as you navigate, but honouring that later
   * would re-open a group the user just collapsed.
   */
  defaultOpen?: boolean
  onNavigate?: () => void
  onEditProject?: (p: Project) => void
}) {
  const { t } = useT()
  const location = useLocation()
  const navigate = useNavigate()

  const isActiveProject = location.pathname.startsWith(
    `/projects/${project.id}`
  )
  const [open, setOpen] = useState(isActiveProject || defaultOpen)
  // Roll the group's unread sessions up to its header, but only while it hides
  // them: collapsed is the state where a finished background turn would
  // otherwise be invisible. Expanded, the rows carry their own dots and a
  // second one up here would just double-count them.
  const hasUnread = !open && sessions.some((s) => s.unread)

  useEffect(() => {
    if (isActiveProject) setOpen(true)
  }, [isActiveProject])

  // All sessions are shown directly (no secondary fold / "show all" toggle).
  const visibleSessions = sessions

  const projectName = project.name
  // EXACTLY this project's own detail page — not one of its sessions, not its
  // "new chat" route. Only this pins the row's highlight and its two actions;
  // `isActiveProject` (any descendant route) still colors the name and keeps the
  // group expanded, which is the "you are inside this project" cue.
  const isProjectPage =
    location.pathname.replace(/\/+$/, '') === `/projects/${project.id}`

  return (
    <div>
      {/* Project header row. `gap-2` after the 16px chevron puts the name on
          32px — the same line as SessionItem's `pl-8` title. */}
      <div
        className={`group flex cursor-pointer items-center gap-2 h-10 rounded-lg px-2 transition-colors hover:bg-msa-fill-2 ${isProjectPage ? 'bg-msa-fill-2' : ''}`}
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
            className={`h-3.5 w-3.5 transition-transform ${open ? '' : 'rotate-180'}`}
          />
        </span>
        {/* Project name — click to enter project detail */}
        <div
          className="flex-1 w-0 py-2 flex items-center"
          onClick={(e) => {
            e.stopPropagation()
            navigate(`/projects/${project.id}`)
            onNavigate?.()
          }}
        >
          <span
            className={`min-w-0 truncate text-[13px] font-semibold text-msa-text-1`}
            title={projectName}
          >
            {projectName}
          </span>
          <span className="shrink-0 rounded-[12px] mx-1.5 px-1.5 py-px font-medium text-xs tabular-nums text-msa-text-1 bg-msa-fill-3">
            {sessions.length}
          </span>
          {hasUnread && <UnreadDot label={t.sidebar.unreadProject} />}
        </div>
        <ProjectRowActions
          project={project}
          pinned={isProjectPage}
          onNavigate={onNavigate}
          onEditProject={onEditProject}
        />
      </div>

      {/* Session list */}
      {open && (
        <div className="space-y-1 py-1">
          {sessions.length === 0 ? (
            // The shared empty state, `art="none"`: inside the cramped sidebar
            // group the illustration crowds the layout, so this is just the copy
            // and the CTA that fixes the emptiness (same pill as ProjectsEmpty),
            // opening this project's new-chat page.
            <EmptyState
              size="sm"
              art="none"
              description={t.sidebar.noSessions}
              action={
                // EmptyStateAction bakes in `px-6 py-2`, too wide for the narrow
                // sidebar, so shrink it with `!` overrides like ProjectsEmpty.
                <EmptyStateAction
                  className="!px-4 !py-1.5 !text-xs"
                  onClick={() => {
                    navigate(`/projects/${project.id}/new`)
                    onNavigate?.()
                  }}
                >
                  {t.projectDetail.startChat}
                </EmptyStateAction>
              }
            />
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
  const { message, modal } = App.useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const revalidator = useRevalidator()
  const { running, seeded } = usePresence()
  // Presence is the authority once it has answered; `session.running` is only a
  // loader snapshot, covering the frames before the first heartbeat lands so a
  // genuinely running row doesn't have to wait a round-trip for its spinner.
  // Kept strictly subordinate: a snapshot cannot expire by itself, so honouring
  // it after the poll has spoken is what kept spinners turning on rows whose
  // turn had long since finished (nothing was left to contradict the snapshot).
  const isRunning = running.has(session.id) || (!seeded && !!session.running)
  const [renameOpen, setRenameOpen] = useState(false)
  const [renameValue, setRenameValue] = useState('')

  const handleRename = async () => {
    const title = renameValue.trim()
    if (!title || title === session.title) {
      setRenameOpen(false)
      return
    }
    await api.updateSession(session.id, { title })
    // Deliberately not awaited, unlike delete below: nothing follows it here, so
    // awaiting would only delay this handler's own promise, which no caller
    // consumes. A refresh lost to the user navigating away mid-flight is
    // re-issued by the app layout (`recoverInterruptedRefresh`).
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
        // Awaited for the same reason as project delete: the route change that
        // follows no longer revalidates on its own.
        await revalidator.revalidate()
        const isActive = location.pathname.includes(`/sessions/${session.id}`)
        if (isActive) navigate(`/projects/${projectId}`)
      }
    })
  }

  const handleExport = async (
    format: SessionExportFormat,
    detail: SessionExportDetail
  ) => {
    try {
      await downloadSessionExport(session, format, detail)
      message.success(t.sidebar.exportSuccess)
    } catch (error) {
      message.error(
        error instanceof DownloadUnauthorizedError
          ? t.workspace.downloadUnauthorized
          : t.sidebar.exportFailed
      )
    }
  }

  const exportDetailItems = (
    format: SessionExportFormat
  ): MenuProps['items'] => [
    {
      key: `${format}-full`,
      label: t.sidebar.exportFull,
      onClick: () => void handleExport(format, 'full')
    },
    {
      key: `${format}-compact`,
      label: t.sidebar.exportCompact,
      onClick: () => void handleExport(format, 'compact')
    },
    {
      key: `${format}-user-only`,
      label: t.sidebar.exportConversationOnly,
      onClick: () => void handleExport(format, 'user-only')
    }
  ]

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
        key: 'export',
        label: t.sidebar.exportSession,
        children: [
          {
            key: 'export-markdown',
            label: t.sidebar.exportMarkdown,
            children: exportDetailItems('markdown')
          },
          {
            key: 'export-html',
            label: t.sidebar.exportHtml,
            children: exportDetailItems('html')
          }
        ]
      },
      {
        key: 'delete',
        label: t.sidebar.deleteSession,
        danger: true,
        onClick: handleDeleteSession
      }
    ],
    expandIcon: <ExpandIcon className="h-3.5 w-3.5 rotate-90 text-msa-text-3" />
  }

  // Bind the active highlight to the real browser URL (not NavLink's router
  // `isActive`), so a session opened via the chat's mid-stream replaceState is
  // highlighted immediately — the router location can lag the address bar.
  const to = `/projects/${projectId}/sessions/${session.id}`
  const active = useUrlPath() === to
  // Hover-revealed by default; pinned visible on the open session — same rule as
  // the project row above, so the highlighted row always carries its actions.
  const rowActionClass = `!shrink-0 !transition-opacity ${
    active ? '' : '!opacity-0 group-hover:!opacity-100'
  }`
  return (
    <>
      <NavLink
        to={to}
        end
        onClick={onNavigate}
        className={`group flex h-10 items-center gap-1 truncate rounded-lg pl-8 pr-2 text-[13px] transition-colors ${
          active
            ? 'bg-msa-fill-2 font-medium text-msa-text-1'
            : 'text-msa-text-2 hover:bg-msa-fill-2'
        }`}
        title={session.title}
      >
        {/* Title and indicator travel together, trailing the text the way the
            project row's count badge does. `flex-1` belongs to this wrapper and
            NOT to the title: on the title it stretches to fill the row and
            strands the indicator against the right edge, far from the words it
            refers to. The wrapper still absorbs the same slack, so the more-menu
            stays pinned right. */}
        <span className="flex min-w-0 flex-1 items-center gap-1">
          <span className="min-w-0 truncate">{session.title}</span>
          {/* Spinner while the turn runs, dot once it has finished unwatched —
              the same slot, never both: the dot exists precisely because the
              spinner went away with nothing left to say the answer arrived. */}
          {isRunning ? (
            <SpinnerIcon className="h-3 w-3 shrink-0 animate-spin text-msa-text-brand1" />
          ) : session.unread ? (
            <UnreadDot spinnerSlot label={t.sidebar.unreadSession} />
          ) : null}
        </span>
        {/* More menu — hover-triggered, hence no tooltip (it would sit on top of
            the menu); the label lives on `aria-label` instead. The wrapper keeps
            a click on the button from reaching the row's link, which a hover
            menu no longer intercepts. */}
        <span onClick={(e) => e.stopPropagation()}>
          <Dropdown
            menu={sessionMenu}
            trigger={['hover']}
            placement="bottomRight"
          >
            <IconButton
              aria-label={t.resources.more}
              icon={<MoreIcon className="h-3.5 w-3.5" />}
              variant="ghost"
              size="xs"
              className={rowActionClass}
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
