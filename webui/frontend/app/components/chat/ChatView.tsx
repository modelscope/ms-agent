import { Button } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router'
import { ChatBackdrop } from '~/components/chat/ChatBackdrop'
import { ChatPanel } from '~/components/chat/ChatPanel'
import type { ChatComposerCtx } from '~/components/chat/ChatPanel'
import { Composer } from '~/components/common/Composer'
import { SessionRightRail } from '~/components/session/SessionRightRail'
import { RailDrawer } from '~/components/common/RailDrawer'
import { StepDetailRail } from '~/components/messages/StepDetailRail'
import type { AgentStep } from '~/components/messages/types'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import { WorkspaceFilesProvider } from '~/lib/workspaceFiles'
import { useMatchMedia } from '~/lib/useMatchMedia'
import type { Project } from '~/lib/types'
import type { AgentMessage } from '~/lib/agentProvider'
import type { ChatFileRef, MessageSegment } from '~/lib/agentProvider'
import type { SessionPlan, Artifact } from '~/lib/types'
import WorkspaceIcon from '~/assets/icons/workspace.svg?react'

interface Props {
  /** Fixed project context. `null` = homepage new chat (project picker shown). */
  project: Project | null
  /** `null` = new-chat mode; a string = existing session (detail) mode. */
  sessionId: string | null
  /** Auto-submit this message once on mount (carried draft from overview). */
  autoSubmitMessage?: string
  /** Files attached to the auto-submitted draft (carried from overview). */
  autoSubmitFiles?: ChatFileRef[]
  /** Ordered text+skill-pill segments of the auto-submitted draft. Present
   * only when the carried draft used at least one skill pill. */
  autoSubmitSegments?: MessageSegment[]
  /** History messages to seed the chat with (existing-session detail mode). */
  initialMessages?: AgentMessage[]
  /** Todo plan to seed the pinned plan box on SSR (existing-session mode). */
  initialPlan?: SessionPlan | null
  /** Session artifacts to seed the composer file list on SSR (no flicker). */
  initialArtifacts?: Artifact[]
  /** Whether a turn is in flight for this session (background-continued):
   * triggers an immediate live re-attach on mount. */
  initialRunning?: boolean
}

export function ChatView({
  project,
  sessionId,
  autoSubmitMessage,
  autoSubmitFiles,
  autoSubmitSegments,
  initialMessages,
  initialPlan,
  initialArtifacts,
  initialRunning
}: Props) {
  const { t } = useT()
  const location = useLocation()
  const prefill =
    autoSubmitMessage ??
    (location.state as { prefill?: string } | null)?.prefill
  const prefillFiles =
    autoSubmitFiles ??
    (location.state as { prefillFiles?: ChatFileRef[] } | null)?.prefillFiles
  const prefillSegments =
    autoSubmitSegments ??
    (location.state as { prefillSegments?: MessageSegment[] } | null)
      ?.prefillSegments

  // The carried draft lives in the history entry's state, which survives a
  // browser refresh — and ChatPanel's fire-once guard resets on a full reload,
  // so an unstripped prefill would silently re-submit the first message on
  // every refresh (and on back/forward). Strip it from the entry once
  // consumed; React Router's in-memory location.state keeps the value for
  // this mount, so the auto-submit itself is unaffected.
  useEffect(() => {
    const hs = window.history.state as {
      usr?: {
        prefill?: unknown
        prefillFiles?: unknown
        prefillSegments?: unknown
      }
    } | null
    if (
      hs?.usr?.prefill == null &&
      hs?.usr?.prefillFiles == null &&
      hs?.usr?.prefillSegments == null
    )
      return
    window.history.replaceState(
      {
        ...hs,
        usr: {
          ...hs.usr,
          prefill: undefined,
          prefillFiles: undefined,
          prefillSegments: undefined
        }
      },
      ''
    )
  }, [])

  // A homepage new chat creates its session mid-stream and only swaps the URL
  // via replaceState (no navigation, so this component is NOT remounted). Track
  // that transition here so the view leaves new-chat mode right away: project
  // picker hidden, workspace available — exactly like the session route.
  const [startedProject, setStartedProject] = useState<Project | null>(null)
  const [startedSessionId, setStartedSessionId] = useState<string | null>(null)
  const handleSessionStarted = useCallback((sid: string, pid: string) => {
    setStartedSessionId(sid)
    api
      .getProject(pid)
      .then(setStartedProject)
      .catch(() => {})
  }, [])

  const activeProject = project ?? startedProject
  const activeSessionId = sessionId ?? startedSessionId
  const isNewChat = activeSessionId === null
  const showWorkspace = activeProject !== null

  const projectId = project?.id ?? null
  const isLg = useMatchMedia('(min-width: 1280px)')
  const [railOpen, setRailOpen] = useState(false)
  const [railDrawer, setRailDrawer] = useState(false)

  // Clicking a step card shows its detail in the right rail. The rail is a
  // single squeezable slot shared by the file workspace and the step detail:
  // `railOpen`/`railDrawer` track whether it's open (side-by-side ≥xl vs overlay
  // <xl); `detailStep` decides its content (a clicked step's detail, else the
  // workspace).
  const [detailStep, setDetailStep] = useState<AgentStep | null>(null)
  // External "open this file in the workspace" request (a click on a file card
  // in a chat bubble). Nonce bumps per click so re-clicking the same file after
  // closing the rail re-selects it.
  const [openFileReq, setOpenFileReq] = useState<{
    path: string
    nonce: number
  } | null>(null)
  // True while the squeezable panel's width transition is running (either
  // direction), so the rail content is clipped (overflow hidden) and doesn't
  // reflow / flash a scrollbar mid-animation. Cleared on transition end.
  const [animating, setAnimating] = useState(false)
  const openRail = () => {
    if (isLg) {
      if (!railOpen) setAnimating(true)
      setRailOpen(true)
    } else setRailDrawer(true)
  }
  // Start the collapse animation but keep `detailStep` (the rail content) intact
  // until the animation finishes — cleared by the panel's onTransitionEnd / the
  // drawer's afterOpenChange — so the content doesn't swap mid-animation.
  const closeRail = () => {
    if (railOpen) setAnimating(true)
    setRailOpen(false)
    setRailDrawer(false)
  }
  // Workspace toggle button: show the file workspace (clearing any step detail).
  const toggleRail = () => {
    setDetailStep(null)
    if (isLg) {
      setAnimating(true)
      setRailOpen((p) => !p)
    } else setRailDrawer((p) => !p)
  }
  // Clicking a step card opens its detail in the rail (a dedicated component,
  // not the file workspace).
  const openStepDetail = (step: AgentStep) => {
    setDetailStep(step)
    openRail()
  }
  // Clicking a file card in a chat bubble opens the file workspace (clearing any
  // step detail) and selects that path for preview.
  const openWorkspaceFile = (path: string) => {
    setDetailStep(null)
    setOpenFileReq((prev) => ({ path, nonce: (prev?.nonce ?? 0) + 1 }))
    openRail()
  }

  // Pin the rail content to its open pixel width so it doesn't reflow while the
  // container collapses (the width animates 0 <-> min(920px,60%); a percentage
  // child would squeeze the text). Measured from the stable flex parent, which
  // keeps its width as the rail expands/collapses.
  const railRef = useRef<HTMLDivElement>(null)
  const [contentWidth, setContentWidth] = useState(0)
  // Parent width, for clamping a user-dragged rail width.
  const [parentWidth, setParentWidth] = useState(0)
  useEffect(() => {
    const parent = railRef.current?.parentElement
    if (!parent) return
    const update = () => {
      setParentWidth(parent.clientWidth)
      setContentWidth(Math.min(920, parent.clientWidth * 0.6))
    }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(parent)
    return () => ro.disconnect()
  }, [showWorkspace])

  // User-resizable rail: dragging the handle on the panel's left edge
  // overrides the default width (null = the min(920px,60%) formula above).
  // Clamped to [RAIL_MIN, railMax] so neither side collapses; transition is
  // suspended while dragging so the panel tracks the pointer.
  const RAIL_MIN = 480
  const railMax = Math.max(
    RAIL_MIN,
    Math.min(1400, (parentWidth || Infinity) - 360)
  )
  const [railWidth, setRailWidth] = useState<number | null>(null)
  const effectiveRailWidth = Math.min(railWidth ?? contentWidth, railMax)
  const [railDragging, setRailDragging] = useState(false)
  const railDragStart = useRef({ x: 0, w: 0 })
  const onRailHandlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    railDragStart.current = { x: e.clientX, w: effectiveRailWidth }
    setRailDragging(true)
  }
  const onRailHandlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!railDragging) return
    const next = railDragStart.current.w + (railDragStart.current.x - e.clientX)
    setRailWidth(Math.min(railMax, Math.max(RAIL_MIN, next)))
  }
  const onRailHandlePointerUp = () => setRailDragging(false)

  // While the rail is open, Esc closes it (the antd overlay Drawer already
  // handles Esc; this also covers the side-by-side `railOpen` card).
  useEffect(() => {
    if (!railOpen && !railDrawer) return
    const closeOnEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeRail()
    }
    window.addEventListener('keydown', closeOnEsc)
    return () => window.removeEventListener('keydown', closeOnEsc)
  }, [railOpen, railDrawer])

  // Switching conversations resets a STEP-DETAIL rail back to the file
  // workspace: the detail belonged to a step in the session being left, so it
  // is meaningless in another chat — but the rail stays OPEN, just showing the
  // (per-project) workspace instead. Only `detailStep` is cleared; railOpen /
  // railDrawer are untouched, so there is no close animation. Keyed on the
  // committed route `sessionId` (not `activeSessionId`), so a brand-new chat
  // committing its own id isn't treated as a switch.
  useEffect(() => {
    setDetailStep(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  // If the viewport crosses the xl breakpoint while the rail is open, migrate it
  // between the two presentations instead of leaving a side-by-side panel that
  // crushes the chat column on a now-narrow page: squeezing below xl turns an
  // open workspace/detail into the overlay drawer, and widening back to ≥xl
  // restores the side-by-side panel. `detailStep` (the rail content) is kept
  // across the swap — the two content-clearing callbacks below are guarded so a
  // migration close doesn't wipe it.
  useEffect(() => {
    if (isLg && railDrawer) {
      setAnimating(true)
      setRailDrawer(false)
      setRailOpen(true)
    } else if (!isLg && railOpen) {
      setAnimating(true)
      setRailOpen(false)
      setRailDrawer(true)
    }
  }, [isLg, railOpen, railDrawer])

  // Unified empty state (design spec): left-aligned two-line welcome pinned to
  // the top of the column over the themed backdrop, with the composer below.
  // Same layout for both new-chat and detail modes — the only difference
  // between pages is the workspace button (owned by the detail-mode section).
  const renderEmpty = (ctx: ChatComposerCtx) => (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden justify-center px-4 sm:px-[24px]">
      <div
        className={`mx-auto flex transition-[width] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] ${
          railOpen ? 'w-full' : 'w-full xl:w-[80%]'
        } flex-col`}
      >
        <ChatBackdrop className="mb-10 w-full">
          <h1 className="text-3xl font-bold text-msa-text-1 sm:text-4xl">
            Hi <span className="inline-block">👋</span>
          </h1>
          <p className="mt-2 text-2xl font-bold text-msa-text-1 sm:text-3xl">
            {t.home.welcome}
          </p>
        </ChatBackdrop>
        <Composer
          project={activeProject}
          onSubmit={ctx.submit}
          loading={ctx.loading}
          onCancel={ctx.abort}
          onType={ctx.scrollToBottom}
          onProjectChange={isNewChat ? ctx.setProjectOverride : undefined}
          thinking={ctx.thinking}
          onOpenFile={openWorkspaceFile}
          autoSize={{
            minRows: 2,
            maxRows: 6
          }}
        />
      </div>
    </div>
  )
  const renderSender = (ctx: ChatComposerCtx) => (
    <div>
      <Composer
        project={activeProject}
        onSubmit={ctx.submit}
        loading={ctx.loading}
        onCancel={ctx.abort}
        onType={ctx.scrollToBottom}
        onProjectChange={isNewChat ? ctx.setProjectOverride : undefined}
        thinking={ctx.thinking}
        onOpenFile={openWorkspaceFile}
      />
    </div>
  )
  const chatPanel = (
    <ChatPanel
      // Remount per session so each conversation gets a fresh useXChat store
      // seeded with its own history (project-session reuses this route module
      // across :sessionId, so without a key the store would keep the previous
      // session's messages).
      key={sessionId ?? 'new'}
      sessionId={sessionId}
      projectId={projectId}
      workspaceOpen={railOpen}
      autoSubmitMessage={prefill}
      autoSubmitFiles={prefillFiles}
      autoSubmitSegments={prefillSegments}
      initialMessages={initialMessages}
      initialPlan={initialPlan}
      initialArtifacts={initialArtifacts}
      initialRunning={initialRunning}
      onOpenStep={openStepDetail}
      onOpenFile={openWorkspaceFile}
      onSessionStarted={handleSessionStarted}
      renderEmpty={renderEmpty}
      renderSender={renderSender}
    />
  )

  // Right-rail content: a clicked step's detail takes precedence; otherwise the
  // file workspace (detail mode only — new chat has no project/workspace).
  const railBody = detailStep ? (
    <StepDetailRail step={detailStep} onClose={closeRail} clip={animating} />
  ) : activeProject ? (
    <SessionRightRail
      project={activeProject}
      active={railOpen || railDrawer}
      openFile={openFileReq ?? undefined}
      onClose={closeRail}
    />
  ) : null

  // Squeezable rail (≥xl): a right-side card that pushes the chat with a width
  // transition — same behavior as the workspace. The inner content is pinned to
  // its open pixel width so it slides out (clipped) instead of reflowing; the
  // detail content is cleared only once the collapse transition ends.
  const railPanel = (
    <div
      ref={railRef}
      onTransitionEnd={(e) => {
        if (e.propertyName !== 'width' || e.target !== e.currentTarget) return
        setAnimating(false)
        // Clear the content only on a genuine close (both presentations shut),
        // never during a breakpoint migration that hands off to the drawer.
        if (!railOpen && !railDrawer) setDetailStep(null)
      }}
      className={`overflow-hidden shrink-0 ${
        railDragging
          ? ''
          : 'transition-[width] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]'
      }`}
      style={{ width: railOpen ? effectiveRailWidth : 0 }}
    >
      <div
        className="relative flex h-full shrink-0 flex-col p-[24px] pl-0"
        style={effectiveRailWidth ? { width: effectiveRailWidth } : undefined}
      >
        {/* Invisible resize zone: drag the rail's left edge to resize
            (min/max clamped) — no visible handle, just the col-resize cursor.
            Transition is off while dragging so the panel follows the pointer
            1:1. */}
        <div
          onPointerDown={onRailHandlePointerDown}
          onPointerMove={onRailHandlePointerMove}
          onPointerUp={onRailHandlePointerUp}
          className="absolute bottom-[24px] left-0 top-[24px] z-10 w-2 cursor-col-resize"
        />
        <div className="flex h-full flex-col overflow-hidden rounded-3xl border border-msa-line-1 bg-msa-fill-0">
          {railBody}
        </div>
      </div>
    </div>
  )

  // Overlay rail (<xl): a right drawer instead of squeezing the narrow page.
  const railDrawerEl = (
    <RailDrawer
      rootClassName="xl:hidden"
      open={railDrawer}
      onClose={closeRail}
      afterOpenChange={(open) => {
        // Clear the content only on a genuine close, not when a breakpoint
        // migration hands the drawer's content off to the side-by-side panel.
        if (!open && !railOpen) setDetailStep(null)
      }}
    >
      {railBody}
    </RailDrawer>
  )

  // New-chat mode: no file workspace, but a clicked step still opens the
  // squeezable detail rail beside the chat.
  if (!showWorkspace) {
    return (
      <WorkspaceFilesProvider projectId={null}>
        <div className="flex h-full min-h-0">
          <section className="relative flex min-h-0 min-w-0 flex-1">
            <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
              {chatPanel}
            </div>
            {railPanel}
          </section>
          {railDrawerEl}
        </div>
      </WorkspaceFilesProvider>
    )
  }

  // Detail mode: chat + collapsible right rail (workspace or step detail).
  return (
    <WorkspaceFilesProvider projectId={activeProject?.id ?? null}>
      <div className="flex h-full min-h-0">
        <section className="relative flex min-h-0 min-w-0 flex-1 rounded-xl bg-msa-fill-0">
          {/* Chat area */}
          <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
            {!railOpen && (
              <Button
                shape="round"
                icon={<WorkspaceIcon className="h-4 w-4" />}
                onClick={toggleRail}
                className="absolute right-3 top-3 z-10 !rounded-full !border-msa-line-1 !bg-msa-bg-1 !text-msa-text-1 hover:!bg-msa-fill-2"
                classNames={{
                  icon: 'flex items-center justify-center leading-none'
                }}
              >
                {t.session.workspaceTitle}
              </Button>
            )}
            {chatPanel}
          </div>

          {/* Right rail: workspace or step detail, width transition. */}
          {railPanel}
        </section>

        {railDrawerEl}
      </div>
    </WorkspaceFilesProvider>
  )
}
