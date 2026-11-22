import { App, Button } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRevalidator } from 'react-router'
import { StableSender as Sender } from '~/components/common/StableSender'
import { api } from '~/lib/api'
import { dispatchUrlChange, dispatchSessionDone, dispatchSessionStarted, dispatchWorkspaceChanged, useOnWorkspaceChanged } from '~/lib/events'
import { useT } from '~/lib/i18n'
import { useHydrated } from '~/lib/useHydrated'
import { useSessionChat } from '~/lib/sessionChat'
import { ArtifactDeletedProvider } from '~/lib/workspaceFiles'
import { MessageList, type MessageListHandle } from '~/components/messages/MessageList'
import { MessageListSkeleton } from '~/components/messages/MessageListSkeleton'
import { MessageNavRail } from '~/components/messages/MessageNavRail'
import { PendingInputs } from './PendingInputs'
import type { AgentMessage, ChatFileRef, MessageSegment } from '~/lib/agentProvider'
import type { Artifact, SessionPlan, SessionPlanTask, ReasoningEffort } from '~/lib/types'
import type { ArtifactRef, OnOpenStep, OnOpenFile } from '~/components/messages/types'
import type { ThinkingFile, ThinkingState, ThinkingTask } from '~/components/common/Composer'

export type { ArtifactRef }

export interface ChatComposerCtx {
  refreshMessages: () => void
  submit: (
    text: string,
    files?: ChatFileRef[],
    segments?: MessageSegment[]
  ) => Promise<void>
  loading: boolean
  abort: () => void
  /** Update the project context (only meaningful when sessionId is null). */
  setProjectOverride: (projectId: string | null) => void
  /** Live thinking state derived from the latest assistant message. */
  thinking: ThinkingState | null
  /** Jump the message list to the latest message (e.g. when the user types). */
  scrollToBottom: () => void
}

interface ChatPanelProps {
  sessionId: string | null
  prepareModel?: () => Promise<{ modelId: string; reasoningEffort?: ReasoningEffort }>
  projectId: string | null
  /**
   * Whether the workspace rail is open in side-by-side (lg) mode. When true
   * the content column narrows to w-[80%]; otherwise it fills the width
   * (w-full). Its width transition is kept in sync with the rail's own width
   * animation (same 300ms cubic-bezier) so the combined motion — this
   * percentage shrinking × the section being squeezed — stays continuous and
   * strictly monotonic (no brief grow).
   */
  workspaceOpen?: boolean
  /** Fired when a step card is clicked (host opens the workspace rail). */
  onOpenStep?: OnOpenStep
  /** Fired when a user-attached file card is clicked (host opens the rail and
   * selects that workspace file). */
  onOpenFile?: OnOpenFile
  /**
   * Custom composer rendered in place of the default Welcome+Sender empty
   * state. Receives the session's durable submission callback.
   */
  renderEmpty?: (ctx: ChatComposerCtx) => React.ReactNode
  /**
   * Custom sender rendered at the bottom in the message-list state. Passing
   * this also forces the message-list layout — useful when the host wants the
   * "chat" look even before any messages exist (e.g. session view).
   */
  renderSender?: (ctx: ChatComposerCtx) => React.ReactNode
  /**
   * Submit this message exactly once on mount. Used by ProjectOverview to
   * carry a draft over when creating a new session.
   */
  autoSubmitMessage?: string
  /**
   * Files attached to the auto-submitted message (carried from ProjectOverview
   * when a draft with uploads created the session). Uploaded already, so these
   * are workspace-relative refs the turn sends straight through.
   */
  autoSubmitFiles?: ChatFileRef[]
  /** Ordered text+skill-pill segments of the carried draft (skill pills only). */
  autoSubmitSegments?: MessageSegment[]
  /**
   * History messages to seed the message list with when entering an existing
   * session. Re-seeded whenever the session (or its loaded history) changes.
   */
  initialMessages?: AgentMessage[]
  /**
   * The session's todo plan resolved by the route loader, used to seed the
   * pinned plan box on the SSR first paint so it doesn't flicker in after a
   * client fetch. Refreshed client-side on mount / submit / stream updates.
   */
  initialPlan?: SessionPlan | null
  /** Session artifacts from the route loader, so the composer file list is
   * present in the SSR first paint instead of popping in after a fetch. */
  initialArtifacts?: Artifact[]
  /**
   * Whether this session has a turn in flight (continued in the background
   * after its viewer left). Triggers an immediate live re-attach on mount so
   * the in-progress answer streams in instead of a blank assistant area.
   */
  initialRunning?: boolean
  /**
   * Fired when the backend has created the session for a homepage new chat
   * (early `session` frame). The URL is switched via replaceState WITHOUT a
   * router navigation (so the live stream isn't interrupted), which means the
   * host must be told explicitly to leave "new chat" mode — hiding the project
   * picker and revealing the project workspace.
   */
  onSessionStarted?: (sessionId: string, projectId: string) => void
}

/** Session artifacts → composer file-list rows (deleted ones keep a badge). */
function toThinkingFiles(artifacts: Artifact[]): ThinkingFile[] {
  return artifacts.map((a) => ({
    id: a.id,
    name: a.name || a.path.split('/').pop() || a.path,
    type: 'file' as const,
    path: a.path,
    deleted: a.deleted
  }))
}

/** Map the backend plan items (session todo plan) to composer thinking tasks. */
function toThinkingTasks(tasks: SessionPlanTask[]): ThinkingTask[] {
  return tasks.map((task) => ({
    id: task.id,
    label: task.label,
    status: task.status as ThinkingTask['status']
  }))
}

export function ChatPanel({
  sessionId, prepareModel, projectId, workspaceOpen, onOpenStep, onOpenFile,
  renderEmpty, renderSender, autoSubmitMessage, autoSubmitFiles,
  autoSubmitSegments, initialMessages, initialPlan, initialArtifacts,
  initialRunning, onSessionStarted
}: ChatPanelProps) {
  const { t } = useT()
  const { message: toast } = App.useApp()
  const revalidator = useRevalidator()
  const revalidateRef = useRef(revalidator.revalidate)
  revalidateRef.current = revalidator.revalidate
  const hydrated = useHydrated()
  const listRef = useRef<MessageListHandle>(null)
  const [projectOverride, setProjectOverride] = useState<string | null>(null)
  const [startedSessionId, setStartedSessionId] = useState<string | null>(null)
  const sid = sessionId ?? startedSessionId
  const effectiveProject = projectOverride ?? projectId
  const chat = useSessionChat(sid, initialMessages)
  const { state } = chat
  const items = useMemo(() => [...state.history, ...state.active], [state.history, state.active])
  const [stopping, setStopping] = useState(false)
  const loading = state.running || state.stopping || stopping || (!state.history.length && !!initialRunning && !sid)
  const [plan, setPlan] = useState<SessionPlan | null>(initialPlan ?? null)
  const [artifacts, setArtifacts] = useState<Artifact[]>(initialArtifacts ?? [])
  const refreshPlan = useCallback(() => {
    if (sid) void api.getSessionPlan(sid).then(setPlan).catch(() => {})
  }, [sid])
  const refreshArtifacts = useCallback(() => {
    if (sid) void api.listArtifacts(sid).then(setArtifacts).catch(() => {})
  }, [sid])
  useEffect(refreshPlan, [refreshPlan])
  useEffect(refreshArtifacts, [refreshArtifacts])
  useOnWorkspaceChanged(refreshArtifacts)

  const latest = [...state.active].reverse().find(item => item.message.role === 'assistant')?.message
  const tasks = [...(latest?.parts ?? [])].reverse().find(part => part.kind === 'tasks')
  const thinking: ThinkingState | null = tasks || plan?.tasks.length || artifacts.length
    ? {
        tasks: tasks?.kind === 'tasks' ? tasks.tasks : toThinkingTasks(plan?.tasks ?? []),
        planActive: !!(state.running && (tasks || plan?.active)),
        files: toThinkingFiles(artifacts)
      } : null
  const artifactDeleted = useMemo(() => new Map(artifacts.map(item => [item.path, !!item.deleted])), [artifacts])
  const filePaths = (latest?.parts ?? []).flatMap(part =>
    part.kind === 'step' && ['file_write', 'file_edit'].includes(part.step.kind)
      && !['running', 'skipped', 'error'].includes(String(part.step.meta.status))
      ? [String(part.step.meta.path ?? '')] : [])
  const fileSignature = filePaths.join('|')
  useEffect(() => {
    if (!fileSignature) return
    dispatchWorkspaceChanged(fileSignature.split('|'))
    const timer = setTimeout(refreshArtifacts, 400)
    return () => clearTimeout(timer)
  }, [fileSignature, refreshArtifacts])

  const wasRunning = useRef(false)
  useEffect(() => {
    if (!sid) return
    if (state.running && !wasRunning.current) dispatchSessionStarted(sid)
    else if (!state.running && wasRunning.current) {
      dispatchSessionDone(sid)
      revalidateRef.current()
      refreshPlan()
      refreshArtifacts()
      dispatchWorkspaceChanged()
    }
    wasRunning.current = state.running
  }, [sid, state.running, refreshPlan, refreshArtifacts])

  const handleSubmit = async (value: string, files?: ChatFileRef[], segments?: MessageSegment[]) => {
    if (chat.submitting) return
    const text = value.trim()
    if (!text && !files?.length && !segments?.length) return
    // Session model controls already persist selection. Steer never overrides
    // the active task's model; queued inputs keep their admission-time choice.
    const selection = sid ? undefined : await prepareModel?.()
    const receipt = await chat.submit({
      session_id: sid, project_id: effectiveProject,
      model_id: selection?.modelId, reasoning_effort: selection?.reasoningEffort,
      message: { role: 'user', content: segments?.length ? segments : text, files }
    })
    if (!sid) {
      setStartedSessionId(receipt.session_id)
      window.history.replaceState(window.history.state, '',
        `/projects/${receipt.project_id}/sessions/${receipt.session_id}`)
      dispatchUrlChange()
      onSessionStarted?.(receipt.session_id, receipt.project_id)
      revalidator.revalidate()
    }
    refreshPlan()
  }

  const stop = async () => {
    if (!sid || stopping) return
    setStopping(true)
    try { await api.interruptChat(sid, state.turn_id) }
    catch (error) { toast.error(error instanceof Error ? error.message : t.errors.requestFailed) }
    finally { setStopping(false); chat.refresh() }
  }

  const autoSent = useRef(false)
  const [autoFailed, setAutoFailed] = useState(false)
  const submitPrefill = async () => {
    setAutoFailed(false)
    try { await handleSubmit(autoSubmitMessage ?? '', autoSubmitFiles, autoSubmitSegments) }
    catch { setAutoFailed(true); toast.error(t.errors.requestFailed) }
  }
  useEffect(() => {
    if (autoSent.current || (!autoSubmitMessage && !autoSubmitSegments?.length && !autoSubmitFiles?.length)) return
    autoSent.current = true
    void submitPrefill()
    // The carried draft belongs to this keyed ChatPanel, exactly once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSubmitMessage, autoSubmitSegments, autoSubmitFiles])

  const ctx: ChatComposerCtx = {
    refreshMessages: chat.refresh, submit: handleSubmit, loading,
    abort: () => { void stop() }, setProjectOverride, thinking,
    scrollToBottom: () => listRef.current?.scrollToBottom()
  }
  if (!items.length && !state.pending.length && !loading && renderEmpty) {
    return <div className="flex min-h-0 flex-1 flex-col rounded-[16px] bg-msa-fill-0">{renderEmpty(ctx)}</div>
  }
  const columnCls = `mx-auto flex w-full flex-col transition-[width] duration-300 ${!workspaceOpen ? 'xl:w-[80%]' : ''}`
  return (
    <div className="flex min-h-0 flex-1 flex-col py-[14px]">
      <div className="relative flex min-h-0 flex-1 flex-col px-4 sm:px-9">
        {hydrated && <MessageNavRail items={items} listRef={listRef} />}
        <div className={`${columnCls} min-h-0 flex-1`}>
          {hydrated ? <ArtifactDeletedProvider value={artifactDeleted}>
            <MessageList ref={listRef} items={items} sessionId={sid}
              onOpenStep={onOpenStep} onOpenFile={onOpenFile} />
          </ArtifactDeletedProvider> : <MessageListSkeleton items={items} />}
        </div>
      </div>
      <div className="px-4 sm:px-9">
        <div className={columnCls}>
          {sid && <PendingInputs sessionId={sid} inputs={state.pending} onSend={handleSubmit} />}
          {(chat.confirming || chat.connectionError) && <p role="status" className="mb-2 text-xs text-msa-text-3">
            {chat.confirming ? t.followUp.confirming : t.followUp.reconnecting}
          </p>}
          {state.failure && <p role="alert" className="mb-2 text-sm text-msa-text-2">{state.failure}</p>}
          {autoFailed && <div role="alert" className="mb-3 rounded-lg border border-msa-line-1 p-3 text-sm">
            <p className="whitespace-pre-wrap">{autoSubmitMessage}</p>
            <p>{autoSubmitFiles?.map(file => file.name).join(', ')}</p>
            <Button onClick={() => void submitPrefill()}>{t.home.send}</Button>
          </div>}
          {renderSender ? renderSender(ctx) : <div className="px-3 py-2 sm:px-4 sm:py-3">
            <Sender onSubmit={text => { void handleSubmit(text).catch(() => toast.error(t.errors.requestFailed)) }} placeholder={t.chat.placeholder} autoSize={{ minRows: 1, maxRows: 6 }} />
            {loading && <Button type="text" onClick={() => void stop()}>{t.home.stop}</Button>}
          </div>}
        </div>
      </div>
    </div>
  )
}
