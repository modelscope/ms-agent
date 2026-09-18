import { StableSender as Sender } from '~/components/common/StableSender'
import { XRequest, useXChat } from '@ant-design/x-sdk'
import { App, Button } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRevalidator } from 'react-router'
import {
  AgentChatProvider,
  applyChunk,
  assertChatStream,
  CHAT_STREAM_ERROR,
  historyToAgentMessages,
  parseChunk,
  type AgentInput,
  type AgentMessage,
  type AgentOutput,
  type ChatFileRef,
  type HistoryMessage,
  type MessageSegment
} from '~/lib/agentProvider'
import { ApiError, api, describeFailure } from '~/lib/api'
import {
  dispatchUrlChange,
  dispatchSessionDone,
  dispatchSessionStarted,
  dispatchWorkspaceChanged,
  useOnWorkspaceChanged
} from '~/lib/events'
import { useT } from '~/lib/i18n'
import {
  claimQuestion,
  forgetQuestion,
  pendingQuestion,
  rememberQuestion
} from '~/lib/pendingTurn'
import { usePresence } from '~/lib/presenceContext'
import type { Artifact, SessionPlan, SessionPlanTask } from '~/lib/types'
import { useHydrated } from '~/lib/useHydrated'
import { ArtifactDeletedProvider } from '~/lib/workspaceFiles'
import { MessageList } from '~/components/messages/MessageList'
import { MessageListSkeleton } from '~/components/messages/MessageListSkeleton'
import { MessageNavRail } from '~/components/messages/MessageNavRail'
import type {
  ChatMessageItem,
  MessageListHandle
} from '~/components/messages/MessageList'
import type {
  ArtifactRef,
  OnOpenStep,
  OnOpenFile
} from '~/components/messages/types'
import type {
  ThinkingFile,
  ThinkingState,
  ThinkingTask
} from '~/components/common/Composer'

export type { ArtifactRef }

export interface ChatComposerCtx {
  submit: (
    text: string,
    files?: ChatFileRef[],
    segments?: MessageSegment[]
  ) => void
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
  prepareModel?: () => Promise<string>
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
   * state. Receives a `submit(text)` callback wired to the same useXChat
   * instance so the transition from empty → message list happens naturally.
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
  sessionId,
  prepareModel,
  projectId,
  workspaceOpen,
  onOpenStep,
  onOpenFile,
  renderEmpty,
  renderSender,
  autoSubmitMessage,
  autoSubmitFiles,
  autoSubmitSegments,
  initialMessages,
  initialPlan,
  initialArtifacts,
  initialRunning,
  onSessionStarted
}: ChatPanelProps) {
  const { t } = useT()
  // Aliased: `message` is shadowed all over this file by per-message callback
  // params, so the toast handle gets an unambiguous name.
  const { message: toast } = App.useApp()
  // A failed chat turn reads the same as a failed REST call: its rejection
  // carries an ApiError (status + any backend message), so `describeFailure`
  // yields the status-first, server-vs-client line; a non-HTTP error (a bare
  // network blip) keeps its own message.
  const failureText = (error: unknown): string =>
    error instanceof ApiError
      ? describeFailure(error, {
          server: t.errors.server,
          requestFailed: t.errors.requestFailed,
          network: t.errors.network
        })
      : `${t.chat.requestFailed}: ${(error as Error)?.message ?? ''}`
  const hydrated = useHydrated()
  const listRef = useRef<MessageListHandle>(null)
  const [projectOverride, setProjectOverride] = useState<string | null>(null)
  const effectiveProjectId = projectOverride ?? projectId

  const [provider] = useState(
    () =>
      new AgentChatProvider({
        request: XRequest<AgentInput, AgentOutput, AgentMessage>('/api/chat', {
          manual: true,
          // Reject anything that is not our SSE stream BEFORE XRequest routes on
          // content-type, so a rejection surfaces its own reason instead of an
          // opaque status (non-2xx) or an empty reply bubble (2xx + JSON).
          middlewares: { onResponse: assertChatStream }
        })
      })
  )

  // Effective backend session id: the prop for an existing session, or the id
  // the backend assigns to a new chat, captured from the terminal `done` frame.
  // Used so later turns reuse the same session (no splitting) and Stop can
  // target it. The panel is remounted per session (keyed by sessionId), so this
  // ref is fresh per session; keep it in sync if the prop ever changes.
  const sidRef = useRef<string | null>(sessionId)
  // Reactive mirror of the session id a brand-new chat acquired mid-turn
  // (replaceState keeps the prop null — no remount), so id-dependent UI in
  // the message list (the plan chip) works on that very first turn too.
  const [startedSessionId, setStartedSessionId] = useState<string | null>(null)
  const revalidator = useRevalidator()
  // Guards the one-time early address-bar sync (see onSessionStart).
  const urlSyncedRef = useRef(false)
  useEffect(() => {
    sidRef.current = sessionId
  }, [sessionId])
  useEffect(() => {
    // The moment the server has created the session (early `session` frame):
    // (1) refresh the lists so it shows up right away, and (2) reflect it in
    // the URL via history.replaceState. This is a single, seamless transition
    // — replaceState updates the address bar WITHOUT a router navigation, so the
    // route doesn't remount and the live reply keeps streaming. We deliberately
    // do NOT navigate again at `done` (that remount/reload was a jarring second
    // jump); the sidebar highlight tracks the real URL via useUrlPath, and a
    // reload/next navigation resolves cleanly to the session route.
    provider.onSessionStart = (id, pid) => {
      sidRef.current = id
      setStartedSessionId(id)
      // The question was sent before this id existed; file it under the id now,
      // so leaving and coming back can still render it (see lib/pendingTurn).
      claimQuestion(id)
      // A brand-new chat has no id until this frame, so this is the earliest
      // point its sidebar spinner can light up.
      dispatchSessionStarted(id)
      revalidator.revalidate()
      if (sessionId === null && !urlSyncedRef.current) {
        const proj = pid ?? effectiveProjectId
        if (proj && typeof window !== 'undefined') {
          urlSyncedRef.current = true
          window.history.replaceState(
            window.history.state,
            '',
            `/projects/${proj}/sessions/${id}`
          )
          // Notify route-bound UI (e.g. the sidebar active highlight) since
          // replaceState doesn't fire a navigation event.
          dispatchUrlChange()
          // The host still thinks it's a new chat (no navigation happened):
          // tell it the session context so it switches to session mode.
          onSessionStarted?.(id, proj)
        }
      }
    }
    provider.onSessionId = (id) => {
      sidRef.current = id
      setStartedSessionId(id)
      // The turn is over, so the server has the question whatever the outcome
      // (failed turns are sealed too). Unconditional, unlike the refresh-time
      // cleanup, so a refresh that bailed out cannot leave the copy behind.
      forgetQuestion(id)
      // Immediately clear the sidebar running spinner.
      dispatchSessionDone(id)
      revalidator.revalidate()
      // Refresh canonical history from the server. The seedLen bump happens
      // INSIDE the refresh callback (after setDisplayHistory) so there's no
      // frame where newEntries is empty but displayHistory is stale (no flash).
      refreshMessages()
      // Workspace may have new/modified files from this turn.
      dispatchWorkspaceChanged()
    }
    // Title/category generated (at `done`): refresh again so the summarized
    // title + topic icon replace the cheap first-line title in the lists.
    provider.onSessionMeta = () => {
      revalidator.revalidate()
    }
  }, [provider, revalidator, sessionId, effectiveProjectId, onSessionStarted])

  const {
    messages,
    onRequest,
    isRequesting,
    abort,
    // True while the store is still resolving `defaultMessages`. That init is
    // ASYNC and finishes with a full `setMessages(defaults)`, which would wipe
    // any entry added before it lands — so the auto-submit must wait for it.
    isDefaultMessagesRequesting
  } = useXChat({
    provider,
    // Seed the store at construction so history is present from the first
    // render (the route loader already resolved it before this renders).
    // Seeding post-mount via setMessages instead races the store's async
    // default-message initialization, which clobbers it back to an empty list.
    defaultMessages: (initialMessages ?? []).map((message) => ({
      message,
      status: 'success' as const
    })),
    // Insert an empty assistant message the moment a request is sent, so the
    // reply area immediately shows Bubble's built-in loading indicator instead
    // of staying blank while the backend "thinks" before the first chunk. It
    // carries status 'loading' + empty body, which MessageList maps to the
    // Bubble `loading` state; the first streamed chunk replaces it.
    requestPlaceholder: (): AgentMessage => ({
      role: 'assistant',
      content: ''
    }),
    requestFallback: (_, { error, messageInfo }): AgentMessage => {
      if (error?.name === 'AbortError') {
        // On manual stop, keep whatever was streamed so far as-is (no local
        // sealing/badges). refreshMessages() will immediately bring the
        // canonical server version with proper interrupted markers.
        const streamed = messageInfo?.message as AgentMessage | undefined
        return streamed && (streamed.content || streamed.parts?.length)
          ? streamed
          : ({ role: 'assistant', content: '' } as AgentMessage)
      }
      return {
        role: 'assistant',
        content: failureText(error)
      }
    }
  })

  // Fire-once auto-submit (for prefill carried over from ProjectOverview).
  // Routed through `handleSubmit` rather than calling `onRequest` directly, so a
  // carried draft behaves EXACTLY like one typed in this session: skill-pill
  // segments become structured content, the plan is refreshed, and the
  // turn-timing refs are reset. Hand-rolling the request here previously
  // dropped `segments`, silently turning a carried "/skill …" into plain text.
  //
  // GATED on the store finishing its async `defaultMessages` init: that init
  // ends with `setMessages(defaults)`, so submitting before it completed had the
  // user's own message wiped out of the list — the turn ran (the backend got the
  // text and streamed a reply) but the bubble for what they typed was gone.
  const autoSentRef = useRef(false)
  const [autoSubmitFailed, setAutoSubmitFailed] = useState(false)
  useEffect(() => {
    if (autoSentRef.current || isDefaultMessagesRequesting) return
    const text = (autoSubmitMessage ?? '').trim()
    const hasSegments = !!autoSubmitSegments?.length
    // A carried draft of only a skill pill (no typed text) is still valid.
    if (!text && !hasSegments) return
    autoSentRef.current = true
    void submitPrefill()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSubmitMessage, autoSubmitSegments, isDefaultMessagesRequesting])

  // The pinned composer plan box always mirrors the latest workspace plan.json
  // (GET /api/sessions/{id}/plan) — the live plan file (tool writes + manual
  // edits). It ignores the chat/session log entirely. Re-read on entering the
  // session, on submit, on each mid-stream task-update notification, and when a
  // turn finishes. Empty -> box hidden.
  //
  // liveTail is declared early (before the plan-sync logic) because the
  // plan-sync reads it: attach-rejoined turns flow into liveTail, not into
  // useXChat's `messages` — so the plan sync must see it.
  const [liveTail, setLiveTail] = useState<AgentMessage | null>(null)

  const [planTasks, setPlanTasks] = useState<ThinkingTask[]>(() =>
    toThinkingTasks(initialPlan?.tasks ?? [])
  )
  // Server-side truth: plan.json was written DURING the current running turn
  // (backend compares its mtime with the turn origin). Survives reloads AND
  // tab switch-backs — unlike inferring activity from the replayed stream,
  // which is racy right after a re-attach.
  const [planFileActive, setPlanFileActive] = useState(
    initialPlan?.active ?? false
  )
  // When props change (React Router reuses the component with new loader data
  // before the key-triggered unmount/remount fires), sync the plan state from
  // the fresh prop so the very first render frame is correct.
  useEffect(() => {
    setPlanTasks(toThinkingTasks(initialPlan?.tasks ?? []))
    setPlanFileActive(initialPlan?.active ?? false)
  }, [initialPlan])
  // The session id to read session-scoped data with. On a brand-new chat the
  // `sessionId` PROP stays null for the whole first turn: the id arrives on the
  // stream's `session` frame and the URL is updated with replaceState, which
  // deliberately does NOT remount the route (the reply must keep streaming), so
  // no new prop ever arrives. Reading the prop alone made the plan and the file
  // list clear themselves to empty for that entire turn — a file written on the
  // home page never showed up in the composer's file list.
  const liveSessionId = sessionId ?? startedSessionId

  const refreshPlan = useCallback(() => {
    if (!liveSessionId) {
      setPlanTasks([])
      setPlanFileActive(false)
      return
    }
    api
      .getSessionPlan(liveSessionId)
      .then((plan) => {
        setPlanTasks(toThinkingTasks(plan.tasks))
        setPlanFileActive(plan.active)
      })
      .catch(() => {})
  }, [liveSessionId])

  useEffect(() => {
    refreshPlan()
  }, [refreshPlan])

  // Session artifact ledger — every file the agent wrote/edited this session
  // (deleted ones included, flagged). Backend derives it from the session log,
  // so we just re-pull: on entry, when a file_write step streams in, and on
  // workspace changes (rename/delete flips the badge live).
  const [artifacts, setArtifacts] = useState<Artifact[]>(initialArtifacts ?? [])
  // Sync when props update (same React Router reuse issue as initialPlan).
  useEffect(() => {
    setArtifacts(initialArtifacts ?? [])
  }, [initialArtifacts])
  const refreshArtifacts = useCallback(() => {
    if (!liveSessionId) {
      setArtifacts([])
      return
    }
    api
      .listArtifacts(liveSessionId)
      .then(setArtifacts)
      .catch(() => {})
  }, [liveSessionId])
  useEffect(() => {
    refreshArtifacts()
  }, [refreshArtifacts])
  useOnWorkspaceChanged(refreshArtifacts)

  // Mid-stream the agent re-sends the whole plan as one task chunk per row on
  // every update. The stream IS the plan — we set planTasks directly from the
  // live tasks part, and only re-read plan.json once at turn end.
  // NOTE: attach streams write to `liveTail`, NOT to useXChat's `messages`.
  // We must check BOTH to cover the live-send and attach-rejoin paths.
  const lastAssistantForPlan =
    liveTail?.role === 'assistant'
      ? liveTail
      : ([...messages].reverse().find((it) => it.message.role === 'assistant')
          ?.message ?? null)
  // Plan blocks are frozen SNAPSHOTS appended per update — the LAST one is
  // the current plan state (the first would freeze the pinned panel at the
  // turn's opening 0/N snapshot).
  const tasksPart = [...(lastAssistantForPlan?.parts ?? [])]
    .reverse()
    .find((part) => part.kind === 'tasks')
  const planSignature =
    tasksPart && tasksPart.kind === 'tasks'
      ? tasksPart.tasks.map((task) => `${task.id}:${task.status}`).join('|')
      : ''
  // Sync planTasks directly from the stream (instant, same source as the
  // in-conversation TaskPlan — now both boxes show the same progress).
  useEffect(() => {
    if (tasksPart && tasksPart.kind === 'tasks') {
      setPlanTasks(
        tasksPart.tasks.map((task) => ({
          id: task.id,
          label: task.label,
          status: task.status as ThinkingTask['status']
        }))
      )
      setPlanFileActive(true) // tasks flowing in THIS turn = active
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- planSignature
    // covers the identity of the tasks part.
  }, [planSignature])

  // Any file_write step (the backend maps BOTH write_file and edit_file to
  // this kind) extends/updates the ledger — debounce a re-pull as the burst
  // settles. The signature carries the message id + step paths, not a bare
  // count: a new turn that edits the same number of files would otherwise
  // leave the count unchanged and skip the refresh.
  const fileWritePaths = (lastAssistantForPlan?.parts ?? [])
    .filter((part) => part.kind === 'step' && part.step.kind === 'file_write')
    .map((part) =>
      part.kind === 'step' ? String(part.step.meta.path ?? '') : ''
    )
  const artifactSignature = fileWritePaths.length
    ? `${liveTail ? 'attach' : 'live'}|${fileWritePaths.join('|')}`
    : ''
  const artifactDebounce = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined
  )
  useEffect(() => {
    if (!artifactSignature) return
    // Broadcast the just-written paths IMMEDIATELY (optimistic merge into the
    // shared workspace file set) — a brand-new file's step card must not
    // flash "deleted" while the stale set is being refetched.
    dispatchWorkspaceChanged(fileWritePaths)
    clearTimeout(artifactDebounce.current)
    artifactDebounce.current = setTimeout(refreshArtifacts, 400)
    return () => clearTimeout(artifactDebounce.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fileWritePaths
    // is rebuilt every render; the signature IS its stable identity.
  }, [artifactSignature, refreshArtifacts])

  // NOTE: the former pagehide → sendBeacon('/api/chat/cancel') cancel was
  // removed: pagehide also fires on a REFRESH, which must NOT stop the turn.
  // Product decision: leaving the page — navigation, refresh, or closing the
  // browser — always lets the turn run to completion in the background (come
  // back any time and re-attach / reload the answer). Only the explicit Stop
  // button cancels a turn.

  const handleSubmit = async (
    value: string,
    files?: ChatFileRef[],
    segments?: MessageSegment[]
  ) => {
    const modelId = await prepareModel?.()
    const text = value.trim()
    const attached = files?.length ? files : undefined
    setStoppedLocally(false)
    // A new turn: drop the previous turn's mirrored origin so a Stop on THIS
    // turn can never freeze a duration measured from the old one.
    turnOriginRef.current = 0
    // A bare skill pill is a valid submission (the backend answers with the
    // skill intro when there are no args).
    if (!text && !attached && !segments?.length) return
    // The plan may have been hand-edited since the last fetch; pull the latest
    // before this turn starts streaming its own updates.
    refreshPlan()
    // Configuration-style content: the composer already provides the ORDERED
    // segment array (text interleaved with skill pills); plain text stays a
    // string. The backend parses either.
    const content = segments?.length ? segments : text
    // Light up the sidebar spinner now instead of on the next presence
    // heartbeat. For a brand-new chat there is no id yet — `onSessionStart`
    // dispatches it as soon as the backend assigns one.
    if (sidRef.current) dispatchSessionStarted(sidRef.current)
    // Keep the question reachable from outside this component tree. The bubble
    // useXChat is about to add lives and dies with this mount, and for the next
    // second or two the server has no copy either — so without this, leaving the
    // conversation and coming back inside that window shows a turn in progress
    // with nothing to show what was asked (see lib/pendingTurn).
    rememberQuestion(sidRef.current, {
      role: 'user',
      content: text,
      files: attached,
      segments: segments?.length ? segments : undefined
    })
    onRequest({
      session_id: sidRef.current,
      project_id: effectiveProjectId,
      model_id: sidRef.current ? undefined : modelId,
      message: { role: 'user', content, files: attached }
    })
  }

  const submitPrefill = async () => {
    setAutoSubmitFailed(false)
    try {
      await handleSubmit(autoSubmitMessage ?? '', autoSubmitFiles, autoSubmitSegments)
    } catch {
      setAutoSubmitFailed(true)
      toast.error(t.errors.requestFailed)
    }
  }

  // --- live re-attach: rejoin a turn that kept running in the background ---
  // Entering a session whose turn is in flight used to show a blank assistant
  // area (history only has rows persisted at round boundaries) until the turn
  // finished AND the page was refreshed. Now we open POST /api/chat/attach:
  // the backend replays the turn's buffered events (full catch-up — thoughts
  // with real elapsed times, steps, the text so far) and then streams the live
  // tail; `liveTail` renders it as the in-progress assistant message.
  const { running: presenceRunning } = usePresence()
  // Derived as a boolean so the attach effect below doesn't re-run (and abort its
  // stream) merely because the heartbeat handed out a new Set instance.
  const presenceSaysRunning = !!sessionId && presenceRunning.has(sessionId)
  // True while the attach SSE is open: drives the composer into its loading
  // state so the Stop button is available for a rejoined turn too.
  const [attaching, setAttaching] = useState(false)
  // The question of the turn being re-attached, as the server reports it on the
  // `turn` frame. Covers the one case the out-of-tree copy cannot: a full page
  // reload landing mid-turn, which takes the module state with it.
  const [liveTurnUser, setLiveTurnUser] = useState<AgentMessage | null>(null)
  const attachCtrlRef = useRef<AbortController | null>(null)
  // One-shot latch per TURN: set once a turn we attached to ends (or is stopped),
  // so a stale heartbeat can't make us rejoin a finished turn. It is re-armed
  // when the heartbeat reports a NEW turn (not-running → running), otherwise the
  // next turn started from another tab would be invisible here — startAttach
  // would return early forever, leaving both the stream and the history refresh
  // unarmed. Keyed on the TRANSITION, not on "not running": re-arming the moment
  // a turn ends would let a still-true `initialRunning` (loader data lags by a
  // revalidation) open a pointless attach to the turn that just finished.
  const attachDoneRef = useRef(false)
  const prevPresenceRunningRef = useRef(false)
  useEffect(() => {
    const wasRunning = prevPresenceRunningRef.current
    prevPresenceRunningRef.current = presenceSaysRunning
    if (presenceSaysRunning && !wasRunning) attachDoneRef.current = false
  }, [presenceSaysRunning])

  // Turn-completion backstop for the artifact ledger: shell-created/deleted
  // files never emit a file_write step, so re-pull once streaming stops.
  const turnLive = isRequesting || attaching
  useEffect(() => {
    if (!turnLive) refreshArtifacts()
  }, [turnLive, refreshArtifacts])

  const startAttach = useCallback(() => {
    const sid = sessionId
    if (!sid || attachCtrlRef.current || attachDoneRef.current) return
    const ctrl = new AbortController()
    attachCtrlRef.current = ctrl
    setAttaching(true)
    // Re-read the plan immediately: a tab-switch-back lands on a stale loader
    // snapshot (active:false) while the turn has been making progress in the
    // background — planFileActive must reflect the current server truth before
    // any stream frames arrive.
    refreshPlan()
    // Re-read the HISTORY too, for the same reason: a turn we only learned about
    // from the heartbeat was started somewhere else (another tab), so this view's
    // history predates the user message that kicked it off. Attaching alone would
    // stream an assistant reply under a conversation that never shows the
    // question. A route revalidation does NOT fix this — `displayHistory` is
    // seeded from the loader once, at mount.
    //
    // No loop risk: this sits behind the same one-shot guard as the attach itself
    // (an already-open stream or an already-finished turn returned above), and
    // the state it writes is not in the attach effect's dependencies.
    refreshMessages()
    // Placeholder immediately (renders the loading bubble, not a blank area).
    setLiveTail({ role: 'assistant', content: '' })
    ;(async () => {
      let sawContent = false
      try {
        const resp = await fetch('/api/chat/attach', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sid }),
          signal: ctrl.signal
        })
        // A rejected response still HAS a body, so the reader below would happily
        // consume it and silently drop every line for lacking a `data:` prefix —
        // leaving the placeholder bubble loading forever.
        await assertChatStream(resp)
        const reader = resp.body?.getReader()
        if (!reader) throw new Error('no stream')
        const decoder = new TextDecoder()
        let buf = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const lines = buf.split('\n')
          buf = lines.pop() ?? ''
          for (const line of lines) {
            if (!line.startsWith('data:')) continue
            const chunk = parseChunk(line.slice(5).trim())
            if (!chunk) continue
            if (chunk.type === 'done') {
              attachDoneRef.current = true
              // Same reasoning as `onSessionId`: the turn ended, so the copy of
              // its question has served its purpose either way.
              forgetQuestion(sid)
              // Turn completed: refresh history from server, then clear the
              // attach stream. Through refreshMessages — not an inline fetch —
              // so the seed bump rides along: without it, entries severed from
              // a dropped live stream stayed in newEntries and the finished
              // turn rendered twice.
              revalidator.revalidate()
              dispatchSessionDone(sid)
              refreshPlan() // final plan state (active:false now)
              refreshArtifacts()
              refreshMessages()
                .then(() => {
                  setLiveTail(null)
                  // History now carries the question; the stand-ins for it can go.
                  setLiveTurnUser(null)
                })
                .catch(() => setLiveTail(null))
              return
            }
            // A `turn` frame only carries the turn's age (counter re-base) and
            // the turn's own question — it is not content, so it must not keep
            // an otherwise empty tail alive when the attach is aborted.
            if (chunk.type === 'turn') {
              const asked = (
                chunk.meta as {
                  user?: { content?: string; segments?: MessageSegment[] }
                } | undefined
              )?.user
              if (asked?.content)
                setLiveTurnUser({
                  role: 'user',
                  content: asked.content,
                  segments: asked.segments?.length ? asked.segments : undefined
                })
            } else {
              sawContent = true
            }
            setLiveTail((prev) =>
              applyChunk(prev ?? { role: 'assistant', content: '' }, chunk)
            )
          }
        }
      } catch (e) {
        // Aborted (stop/unmount) or unreachable: keep whatever streamed.
        if (!sawContent) setLiveTail(null)
        // Only a REJECTED response gets a toast. An abort is routine (stop /
        // navigation) and a network blip already reads as "nothing arrived", so
        // toasting those would be pure noise; a rejection is the one case where
        // the placeholder vanishing is otherwise unexplained.
        if ((e as Error)?.name === CHAT_STREAM_ERROR) {
          toast.error(failureText(e))
        }
      } finally {
        // Only clear attaching if THIS stream's ctrl is still the active one.
        // A stale finally (from a previous session's aborted attach) must not
        // flip the flag that belongs to the new session's live attach.
        if (attachCtrlRef.current === ctrl) {
          setAttaching(false)
          attachCtrlRef.current = null
        }
      }
    })()
  }, [sessionId])

  // Attach when the session is known to be running: the loader flag gives an
  // immediate join on navigation; the presence set (refreshing every beat)
  // covers turns that started elsewhere after mount. ALSO: on mount, directly
  // check the session's running state from the API — the loader result may be
  // stale (React Router caches loader data on back-navigation), so a fresh
  // check guarantees the same behavior as a full page refresh.
  //
  // This effect only ARMS the attach; tearing it down lives in its own effect
  // below. Aborting from here meant every change of a trigger flag killed a
  // healthy stream and reopened it: on a refresh mid-turn, `initialRunning`
  // attaches at mount and the first heartbeat then flips `presenceSaysRunning`
  // false→true, producing a second attach (plus a second plan + history read)
  // one beat later.
  useEffect(() => {
    if (!sessionId || isRequesting) return
    if (initialRunning || presenceSaysRunning) {
      startAttach()
      return
    }
    // Fallback: the loader might have returned stale data. Ask the server
    // directly (lightweight, single-field check).
    let cancelled = false
    api
      .getSession(sessionId, { silent: true })
      .then((s) => {
        if (!cancelled && s?.running) startAttach()
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [
    sessionId,
    isRequesting,
    initialRunning,
    // A BOOLEAN, not the presence Set: the set gets a new identity every
    // heartbeat, which would re-run this effect (and re-check the session) for
    // no reason.
    presenceSaysRunning,
    startAttach
  ])

  // Teardown, on its own: detach this viewer when the session changes or the
  // panel unmounts — nothing else. The backend then sees zero watchers; the turn
  // itself keeps running (only the Stop button cancels one). Keyed on sessionId,
  // which is also this panel's remount key, so in practice it fires on unmount.
  //
  // BOTH streams have to go, the live POST /api/chat one included: an in-flight
  // fetch is not tied to the React tree, so leaving it open kept the backend
  // counting a watcher for a conversation nobody was looking at any more — the
  // turn then ended on the "someone saw it" path and never got flagged unread.
  // Dropping it is also what re-attach was built for: coming back remounts with
  // a fresh store seeded from the loader and replays the turn via
  // POST /api/chat/attach, so nothing is lost by hanging up here.
  const abortRef = useRef(abort)
  abortRef.current = abort
  const requestingRef = useRef(isRequesting)
  requestingRef.current = isRequesting
  useEffect(
    () => () => {
      attachCtrlRef.current?.abort()
      attachCtrlRef.current = null
      if (requestingRef.current) abortRef.current()
    },
    [sessionId]
  )

  // Explicit stop: cancel the in-flight turn on the backend (which seals it as
  // interrupted) AND abort the local stream(s). A bare abort — or navigating
  // away — intentionally lets the turn keep running in the background, so Stop
  // must call interrupt to actually stop it. No-op targeting is fine when the
  // new chat's id isn't known yet (first turn); the abort still stops the UI.
  const stop = () => {
    // Mark first: this render already presents the turn as interrupted, so the
    // abort below can never expose a "processed" frame.
    stoppedAtRef.current = Date.now()
    setStoppedLocally(true)
    // Enter the stopping window: the composer stays disabled (see `stopping`)
    // until interrupt + history refresh both settle, so no turn can be started
    // while the seal/refresh is in flight.
    setStopping(true)
    const sid = sidRef.current ?? sessionId
    if (sid) {
      // Immediately clear the running spinner (the `done` frame won't arrive
      // because we're aborting the SSE stream).
      dispatchSessionDone(sid)
      // The backend seals the interrupted round (partial content + `interrupted`
      // flag) WHILE handling /interrupt — it cancels the driver, awaits its
      // unwind (which persists the partial round) and only then responds. So the
      // canonical history must be read AFTER that resolves; refreshing eagerly
      // races the seal and yields a turn with no interrupted badge — and since
      // nothing re-fetches later (and local sealing was removed), the badge
      // would stay missing until a manual reload.
      void api
        .interruptChat(sid)
        .catch(() => {})
        .finally(() => {
          revalidator.revalidate()
          // Refresh canonical history so the next send starts from clean state
          // (same as normal done — no complex splice of interrupted content).
          // Only leave the stopping window once it lands: sending is safe again.
          void refreshMessages().finally(() => setStopping(false))
          dispatchWorkspaceChanged()
        })
    } else {
      // No backend turn to interrupt yet (first turn, id not assigned): the
      // abort below stops the UI; don't leave the composer stuck disabled.
      setStopping(false)
    }
    if (attachCtrlRef.current) {
      // Stopping an attached (rejoined) turn: close the SSE and seal what we
      // have locally — same shape the faithful-interrupt replay produces.
      attachCtrlRef.current.abort()
      attachCtrlRef.current = null
      attachDoneRef.current = true
      setLiveTail(null)
      setLiveTurnUser(null)
      // Clear the flag HERE: the aborted stream's `finally` won't, because its
      // `attachCtrlRef.current === ctrl` guard now fails (we just nulled the
      // ref). Without this the composer stays in its loading state forever —
      // the Stop button never turns back into Send after stopping a turn that
      // was rejoined by a page refresh.
      setAttaching(false)
    }
    abort()
  }

  // Capture the seed length at mount — this is the number of messages useXChat
  // was seeded with (from the loader). Bumped after each turn completes so that
  // completed entries are treated as "history" and newEntries stays clean.
  const seedLenRef = useRef(initialMessages?.length ?? 0)

  // Canonical conversation history from the server. Initially from the route
  // loader; refreshed from the API after each turn completes (the user's ask:
  // "after each turn, re-fetch the message list"). Simple and always correct.
  const [displayHistory, setDisplayHistory] = useState<AgentMessage[]>(
    initialMessages ?? []
  )
  // Track the current messages length so refreshMessages can atomically bump
  // seedLen when the API response arrives (avoids the flash where newEntries
  // is empty but displayHistory hasn't updated yet).
  const messagesLenRef = useRef(messages.length)
  messagesLenRef.current = messages.length
  // The entries themselves, for refreshMessages' swallow guard below.
  const messagesRef = useRef(messages)
  messagesRef.current = messages

  // Stop was pressed for the turn still in `newEntries`. Aborting the stream
  // flips `streaming` to false one render BEFORE the server-sealed interrupted
  // marker arrives — without this flag that render would satisfy `loopDone`
  // and briefly show the "processed" fold + summary split, then snap back once
  // the marker landed. Setting it in the same tick as abort() keeps the turn in
  // its "processing" presentation, which is exactly what the reload shows.
  const [stoppedLocally, setStoppedLocally] = useState(false)
  // Wall-clock instant of the Stop press. The turn has no server loop_end, so
  // without a frozen number the header would fall back to a LIVE
  // `Date.now() - turnStartedAt`, which recomputes on every remount (the
  // canonical-history swap changes the item key) and thus keeps growing after
  // the turn already stopped. Freezing here pins "processing Ns" to the moment
  // the user actually stopped it.
  const stoppedAtRef = useRef(0)
  // Wall-clock origin of the turn currently streaming, mirrored out of the
  // message so it survives the message being REPLACED. On abort, useXChat drops
  // the in-flight entry and re-adds it through `requestFallback` under a fresh
  // id (x-chat: setMessages(ori.filter(…loading/updating…).concat(createMessage(
  // fallback,'abort')))). Reading `turnStartedAt` off that rebuilt message is
  // fragile — when it doesn't survive, the frozen duration comes out undefined
  // and the header falls back to a remount-fresh `elapsed` of 0, flashing
  // "processing 0s" until the server history lands with the real number.
  const turnOriginRef = useRef(0)

  // True from the Stop press until BOTH the /interrupt call and the canonical
  // history refresh have settled. Folded into the composer's loading state so a
  // next turn cannot be sent inside that window: if it were, the in-flight
  // refresh would bump seedLen past the newly-started turn and hide its reply,
  // and the backend could build a second runtime racing the interrupt seal.
  const [stopping, setStopping] = useState(false)

  const refreshMessages = useCallback(() => {
    const sid = sidRef.current
    if (!sid) return Promise.resolve()
    return api
      .listSessionMessages(sid)
      .then((msgs) => {
        // Guard against a stale refresh (e.g. from an earlier Stop) landing
        // after the user switched sessions: only apply while still on the
        // session this fetch was issued for, so it can't overwrite another
        // session's view or mis-bump its seed.
        if (sidRef.current !== sid) return
        const hist = historyToAgentMessages(msgs as unknown as HistoryMessage[])
        // Safety net: never trade local entries for NOTHING. The backend seals
        // failed turns so server history normally contains them, but if a turn
        // died before anything could be persisted, replacing the live view
        // with an empty history (and bumping the seed) would silently discard
        // the user's bubble and the error card — the message would look like
        // it was never sent. Keep the local view; the next successful refresh
        // takes over.
        if (hist.length === 0 && messagesLenRef.current > seedLenRef.current)
          return
        // Never trade a user bubble for a history that predates it. Mid-turn,
        // the user row is persisted only after the runtime finishes preparing
        // (seconds, on a cold build) — a refresh landing inside that window
        // (startAttach fires one) would replace the view with a snapshot that
        // does not contain the question, while the seed bump below hides the
        // optimistic bubble: the message looks like it was never sent, until
        // the turn completes and the next refresh finds it again. Skip; a
        // later refresh (attach done, turn end) takes over.
        //
        // `messagesRef` only holds entries of THIS mount, so after a navigation
        // away and back it is empty and the guard used to wave the stale history
        // straight through — the very window it exists for. The out-of-tree
        // question covers that case.
        const pending = messagesRef.current.slice(
          seedLenRef.current
        ) as ChatMessageItem[]
        const lastLocalUser = [...pending]
          .reverse()
          .find((e) => e.message?.role === 'user')
        const asked =
          lastLocalUser?.message.content ?? pendingQuestion(sid)?.content
        if (asked) {
          const lastHistUser = [...hist]
            .reverse()
            .find((m) => m.role === 'user')
          if (!lastHistUser || lastHistUser.content !== asked) return
        }
        // The server's own copy of the question is in, so the out-of-tree one
        // has nothing left to cover.
        forgetQuestion(sid)
        setDisplayHistory(hist)
        // Bump seed atomically with the history update: newEntries becomes
        // empty in the same render that displayHistory becomes fresh.
        seedLenRef.current = messagesLenRef.current
        // The canonical history now carries the real interrupted marker.
        setStoppedLocally(false)
      })
      .catch(() => {})
  }, [])

  // The turn an attach stream is replaying must not ALSO be rendered from
  // history. The agent persists each round as it closes, so a turn rejoined
  // mid-flight already has its finished rounds on disk — while the attach
  // replays that same turn IN FULL (from the buffer's first event, see
  // backend attach()). Rendering both showed the turn twice: its persisted half
  // as a finished "processed" card, the complete replay below it still
  // "processing" — which reads as the running header having jumped BELOW the
  // tool calls it belongs to.
  //
  // Which row that is, the server states outright: it marks the trailing row
  // `partial` while the turn is running. Older backends don't, so a missing
  // `loop_end` marker (→ `loopDurationMs`) remains the fallback reading.
  const lastHist = displayHistory[displayHistory.length - 1]
  const history =
    liveTail &&
    lastHist?.role === 'assistant' &&
    (lastHist.partial ?? lastHist.loopDurationMs == null)
      ? displayHistory.slice(0, -1)
      : displayHistory

  // Items computation: history + newEntries (current streaming turn) +
  // attachMessage (if re-attaching). No splice, no liveTail insertion.
  const newEntries = messages.slice(seedLenRef.current)
  let items: ChatMessageItem[]
  if (messages.length === 0 && displayHistory.length > 0) {
    // SSR / first-render fallback (useXChat seeds async).
    items = history.map((message, i) => ({
      id: `hist-${i}`,
      message,
      status: 'success' as const
    })) as ChatMessageItem[]
  } else if (newEntries.length > 0) {
    // Active turn: canonical history + the streaming entries from useXChat.
    items = [
      ...history.map((message, i) => ({
        id: `hist-${i}`,
        message,
        status: 'success' as const
      })),
      ...newEntries
    ] as ChatMessageItem[]
  } else {
    // Idle (between turns): show canonical history.
    items = history.map((message, i) => ({
      id: `hist-${i}`,
      message,
      status: 'success' as const
    })) as ChatMessageItem[]
  }
  // Attach streaming message (live re-attach to a background turn).
  if (liveTail) {
    // The attach stream replays the CURRENT turn from its first frame, so a
    // trailing assistant entry here is that same turn's first half — either
    // the mid-turn server snapshot (the SDK persists each finished round
    // while the loop runs) or a severed live stream. Left in place it renders
    // as a "processed" fold of half the turn stacked above the live one,
    // which reads as a stray previous answer. A genuinely finished turn is
    // recognizable by its persisted loop_end duration (or its interrupted
    // marker) and is never dropped.
    const last = items[items.length - 1]
    const lastMsg = last?.message as AgentMessage | undefined
    if (
      lastMsg?.role === 'assistant' &&
      lastMsg.loopDurationMs === undefined &&
      !lastMsg.parts?.some((p) => p.kind === 'interrupted')
    ) {
      items = items.slice(0, -1)
    }
  }
  // The question of the running turn, when this view has no other copy of it:
  // history hasn't caught up (the server writes that row a second or two into
  // the turn) and the local store has none either, which is every mount that
  // did not send it — a remount after navigating away, or a reload. Without
  // this the turn streams an answer under a conversation that never shows what
  // was asked.
  //
  // Gated on the turn actually being in flight, and de-duplicated by content
  // against whatever IS rendered: it retires the moment the real row arrives,
  // and a copy that somehow outlived its turn can never show up as a second
  // bubble under a finished conversation.
  const turnKnownRunning = turnLive || presenceSaysRunning || initialRunning
  const askedRow = turnKnownRunning
    ? pendingQuestion(sidRef.current ?? sessionId) ?? liveTurnUser
    : null
  if (askedRow) {
    const shownUser = [...items]
      .reverse()
      .find((it) => it.message?.role === 'user')
    if (shownUser?.message.content !== askedRow.content) {
      items = [
        ...items,
        {
          id: 'pending-user',
          message: askedRow,
          status: 'success' as const
        } as ChatMessageItem
      ]
    }
  }
  if (liveTail) {
    items = [
      ...items,
      {
        id: 'attach-live',
        message: liveTail,
        status: (liveTail.content || (liveTail.parts?.length ?? 0) > 0
          ? 'updating'
          : 'loading') as ChatMessageItem['status']
      } as ChatMessageItem
    ]
  }
  // The reply slot for a turn we know is running but have no stream for yet.
  // `liveTail` only appears once the attach has been OPENED, which on a remount
  // lags by a second or two: the loader flag comes back stale on a back
  // navigation, so the attach waits on the direct running-state check, and the
  // backend then holds the stream until the runtime is built. Until then the
  // conversation ended on the question with nothing under it — no bubble, no
  // dots — while the composer sat in its running state.
  //
  // Self-limiting instead of timed: it is only added when the last row IS the
  // question, so any assistant row at all takes its place (the attach's first
  // frame, a history refresh, the local send placeholder), and a finished
  // conversation — which ends on an assistant row — can never grow a spinner
  // out of a stale `initialRunning`.
  if (turnKnownRunning && !liveTail) {
    const last = items[items.length - 1]
    if (last?.message.role === 'user') {
      items = [
        ...items,
        {
          id: 'awaiting-reply',
          message: { role: 'assistant', content: '' },
          status: 'loading' as const
        } as ChatMessageItem
      ]
    }
  }

  // Mirror the streaming turn's origin while it is still intact, so Stop can
  // freeze a correct duration even if the abort rebuild drops the field.
  // Cleared on a fresh send (handleSubmit) rather than here, so it stays
  // readable through the stop → seal → refresh window.
  if (!stoppedLocally) {
    const liveOrigin = items.reduce<number>((acc, it) => {
      const t = it.message.turnStartedAt
      return it.message.role === 'assistant' && typeof t === 'number' ? t : acc
    }, 0)
    if (liveOrigin) turnOriginRef.current = liveOrigin
  }

  // Local stop: stamp the interrupted marker onto the turn's last assistant
  // entry right away (copy, never mutate state) so this very render shows the
  // interrupted presentation. The server-sealed history replaces it moments
  // later with the identical shape, so nothing moves on screen.
  if (stoppedLocally && items.length > 0) {
    const lastIdx = items.reduce(
      (acc, it, i) => (it.message.role === 'assistant' ? i : acc),
      -1
    )
    const last = lastIdx >= 0 ? items[lastIdx] : null
    if (last && !last.message.parts?.some((p) => p.kind === 'interrupted')) {
      items = items.map((it, i) =>
        i === lastIdx
          ? {
              ...it,
              status: 'success' as const,
              message: {
                ...it.message,
                // Freeze the elapsed time at the stop instant unless the server
                // already reported a loop duration. The backend records a
                // matching loop_end on interrupt, so the reloaded page shows
                // the same number — no jump between live and replay.
                loopDurationMs:
                  it.message.loopDurationMs ??
                  // Prefer the message's own origin; fall back to the mirrored
                  // ref for the case where the abort rebuild lost it.
                  ((it.message.turnStartedAt ?? turnOriginRef.current)
                    ? Math.max(
                        0,
                        stoppedAtRef.current -
                          (it.message.turnStartedAt ?? turnOriginRef.current)
                      )
                    : undefined),
                // A cut-short thought block gets closed but NOT given a
                // duration: the SDK only finalizes one when thinking ends
                // normally, so history has none either — inventing a number
                // here would vanish on the next reload.
                parts: [
                  ...(it.message.parts ?? []).map((p) =>
                    p.kind === 'thought' && !p.done ? { ...p, done: true } : p
                  ),
                  { kind: 'interrupted' as const }
                ]
              }
            }
          : it
      )
    }
  }

  const thinkingFiles = toThinkingFiles(artifacts)
  // The authoritative deleted state for the top-of-message "N files changed"
  // cards: same ledger the bottom file list uses (real `os.stat`), so the two
  // can never disagree (a live file no longer shows as "deleted" up top just
  // because the fuzzy workspace path-set lagged or used a different root).
  const artifactDeleted = useMemo(
    () => new Map(artifacts.map((a) => [a.path, !!a.deleted])),
    [artifacts]
  )
  // Whether a task is actually being worked on RIGHT NOW. Two truth sources,
  // either suffices:
  // - planFileActive (server GET /plan → active:true when the turn is alive
  //   AND plan.json was written during it — authoritative, independent of the
  //   viewer's attach/stream state, survives reload & tab-switch)
  // - a tasks part seen in this turn's stream (instant, no fetch round-trip)
  const lastStreamAssistant = [...items]
    .reverse()
    .find((it) => it.message.role === 'assistant')
  const planActive =
    // The server says the plan is actively being worked on (stable across
    // navigation, reloads, and re-attaches — no stream frame needed):
    planFileActive ||
    // OR the stream itself reported plan activity this turn:
    ((isRequesting || attaching) &&
      !!lastStreamAssistant?.message.parts?.some((p) => p.kind === 'tasks'))
  const thinking: ThinkingState | null =
    planTasks.length > 0 || thinkingFiles.length > 0
      ? {
          tasks: planTasks,
          planActive,
          files: thinkingFiles.length > 0 ? thinkingFiles : undefined
        }
      : null
  const ctx: ChatComposerCtx = {
    submit: handleSubmit,
    // A rejoined (attached) turn counts as loading too, so the composer shows
    // the Stop control for it and blocks a concurrent send from this view.
    // `stopping` keeps it disabled through the Stop→seal→refresh window.
    loading: isRequesting || attaching || stopping,
    abort: stop,
    setProjectOverride,
    thinking,
    scrollToBottom: () => listRef.current?.scrollToBottom()
  }

  // renderEmpty takes priority when there are no messages (new-chat mode, or a
  // session with no persisted history).
  if (items.length === 0 && renderEmpty) {
    return (
      <div className="flex min-h-0 flex-1 flex-col bg-msa-fill-0 rounded-[16px]">
        {renderEmpty(ctx)}
      </div>
    )
  }

  // Centered content column. Fills the width when the workspace rail is closed
  // and narrows to 80% when it opens, leaving ~20% whitespace on the right. The
  // width transition is kept perfectly in sync with the rail's own animation
  // (same 300ms cubic-bezier), so the combined motion — this percentage shrinking
  // × the section being squeezed — stays continuous and strictly monotonic (no
  // brief grow). Shared by the list and the composer so they stay aligned.
  const columnCls = `mx-auto flex w-full flex-col transition-[width] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] ${
    !workspaceOpen ? 'xl:w-[80%]' : ''
  }`

  return (
    <div className="flex min-h-0 flex-1 flex-col py-[14px]">
      {/*
        List row: spans the FULL width but only the LIST's height, and is the
        positioning context for the conversation navigator. Both facts matter —
        the navigator pins to the far left of the panel (not of the centred
        column, which on wide screens would leave it floating in the middle of
        the conversation) and centres/caps itself against the list alone (not the
        composer), by CSS with no measuring. The horizontal padding lives here
        rather than on the outer container so it doubles as the RESERVED GUTTER
        the navigator sits in: `absolute` offsets resolve against the padding
        box, so `left-1` lands beside the padding, clear of the bubbles (whose
        role classNames deliberately have no left padding).

        Gated on `hydrated` because the navigator drives the list through
        `listRef`, which only exists once the real MessageList is mounted.
      */}
      <div className="relative flex min-h-0 flex-1 flex-col px-9">
        {hydrated && <MessageNavRail items={items} listRef={listRef} />}
        <div className={`${columnCls} min-h-0 flex-1`}>
          {/*
            Only the message list is client-only: XMarkdown parses on the client
            (e.g. wrapping text in <p>), so server-rendering it would cause a
            hydration mismatch. The composer/sender below is SSR-safe, so we keep
            the full chat layout and swap just the list for a matching skeleton
            until hydration. useHydrated is module-level, so client-side
            navigations (no SSR) see the real list immediately with no flash.
          */}
          {hydrated ? (
            <ArtifactDeletedProvider value={artifactDeleted}>
              <MessageList
                ref={listRef}
                items={items}
                sessionId={sessionId ?? startedSessionId}
                onOpenStep={onOpenStep}
                onOpenFile={onOpenFile}
              />
            </ArtifactDeletedProvider>
          ) : (
            <MessageListSkeleton items={items} />
          )}
        </div>
      </div>
      <div className="px-9">
        <div className={columnCls}>
          {autoSubmitFailed && (
            <div role="alert" className="mb-3 rounded-lg border border-msa-line-1 p-3 text-sm">
              <p className="whitespace-pre-wrap">{autoSubmitMessage}</p>
              <p>{autoSubmitFiles?.map(file => file.name).join(', ')}</p>
              <Button onClick={() => void submitPrefill()}>{t.home.send}</Button>
            </div>
          )}
          {renderSender ? (
            renderSender(ctx)
          ) : (
            <div className="px-3 py-2 sm:px-4 sm:py-3">
              <Sender
                loading={isRequesting || attaching || stopping}
                onChange={() => listRef.current?.scrollToBottom()}
                onSubmit={(text) => handleSubmit(text)}
                onCancel={stop}
                placeholder={t.chat.placeholder}
                autoSize={{ minRows: 1, maxRows: 6 }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
