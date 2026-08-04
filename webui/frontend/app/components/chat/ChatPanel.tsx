import { StableSender as Sender } from '~/components/common/StableSender'
import { XRequest, useXChat } from '@ant-design/x-sdk'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useRevalidator } from 'react-router'
import {
  AgentChatProvider,
  applyChunk,
  historyToAgentMessages,
  parseChunk,
  type AgentInput,
  type AgentMessage,
  type AgentOutput,
  type ChatFileRef,
  type HistoryMessage,
  type MessageSegment
} from '~/lib/agentProvider'
import { api } from '~/lib/api'
import {
  dispatchUrlChange,
  dispatchSessionDone,
  dispatchWorkspaceChanged,
  useOnWorkspaceChanged
} from '~/lib/events'
import { useT } from '~/lib/i18n'
import { usePresence } from '~/lib/presenceContext'
import type { Artifact, SessionPlan, SessionPlanTask } from '~/lib/types'
import { useHydrated } from '~/lib/useHydrated'
import { MessageList } from '~/components/messages/MessageList'
import { MessageListSkeleton } from '~/components/messages/MessageListSkeleton'
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
  projectId,
  workspaceOpen,
  onOpenStep,
  onOpenFile,
  renderEmpty,
  renderSender,
  autoSubmitMessage,
  autoSubmitFiles,
  initialMessages,
  initialPlan,
  initialArtifacts,
  initialRunning,
  onSessionStarted
}: ChatPanelProps) {
  const { t } = useT()
  const hydrated = useHydrated()
  const listRef = useRef<MessageListHandle>(null)
  const [projectOverride, setProjectOverride] = useState<string | null>(null)
  const effectiveProjectId = projectOverride ?? projectId

  const [provider] = useState(
    () =>
      new AgentChatProvider({
        request: XRequest<AgentInput, AgentOutput, AgentMessage>('/api/chat', {
          manual: true
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

  const { messages, onRequest, isRequesting, abort } = useXChat({
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
        content: `${t.chat.requestFailed}: ${error?.message ?? ''}`
      }
    }
  })

  // Fire-once auto-submit (for prefill carried over from ProjectOverview).
  const autoSentRef = useRef(false)
  useEffect(() => {
    if (autoSentRef.current || !autoSubmitMessage) return
    const text = autoSubmitMessage.trim()
    if (!text) return
    autoSentRef.current = true
    onRequest({
      session_id: sidRef.current,
      project_id: effectiveProjectId,
      message: {
        role: 'user',
        content: text,
        files: autoSubmitFiles?.length ? autoSubmitFiles : undefined
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSubmitMessage])

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
  const refreshPlan = useCallback(() => {
    if (!sessionId) {
      setPlanTasks([])
      setPlanFileActive(false)
      return
    }
    api
      .getSessionPlan(sessionId)
      .then((plan) => {
        setPlanTasks(toThinkingTasks(plan.tasks))
        setPlanFileActive(plan.active)
      })
      .catch(() => {})
  }, [sessionId])

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
    if (!sessionId) {
      setArtifacts([])
      return
    }
    api
      .listArtifacts(sessionId)
      .then(setArtifacts)
      .catch(() => {})
  }, [sessionId])
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

  const handleSubmit = (
    value: string,
    files?: ChatFileRef[],
    segments?: MessageSegment[]
  ) => {
    const text = value.trim()
    const attached = files?.length ? files : undefined
    setStoppedLocally(false)
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
    onRequest({
      session_id: sidRef.current,
      project_id: effectiveProjectId,
      message: { role: 'user', content, files: attached }
    })
  }

  // --- live re-attach: rejoin a turn that kept running in the background ---
  // Entering a session whose turn is in flight used to show a blank assistant
  // area (history only has rows persisted at round boundaries) until the turn
  // finished AND the page was refreshed. Now we open POST /api/chat/attach:
  // the backend replays the turn's buffered events (full catch-up — thoughts
  // with real elapsed times, steps, the text so far) and then streams the live
  // tail; `liveTail` renders it as the in-progress assistant message.
  const { running: presenceRunning } = usePresence()
  // True while the attach SSE is open: drives the composer into its loading
  // state so the Stop button is available for a rejoined turn too.
  const [attaching, setAttaching] = useState(false)
  const attachCtrlRef = useRef<AbortController | null>(null)
  const attachDoneRef = useRef(false)

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
              // Turn completed: refresh history from server, then clear the
              // attach stream in the SAME render (no flash/gap).
              revalidator.revalidate()
              dispatchSessionDone(sid)
              refreshPlan() // final plan state (active:false now)
              refreshArtifacts()
              api
                .listSessionMessages(sid)
                .then((msgs) => {
                  setDisplayHistory(
                    historyToAgentMessages(msgs as unknown as HistoryMessage[])
                  )
                  setLiveTail(null)
                })
                .catch(() => setLiveTail(null))
              return
            }
            // A `turn` frame only carries the turn's age (counter re-base) —
            // it is not content, so it must not keep an otherwise empty tail
            // alive when the attach is aborted.
            if (chunk.type !== 'turn') sawContent = true
            setLiveTail((prev) =>
              applyChunk(prev ?? { role: 'assistant', content: '' }, chunk)
            )
          }
        }
      } catch {
        // Aborted (stop/unmount) or unreachable: keep whatever streamed.
        if (!sawContent) setLiveTail(null)
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
  // The CLEANUP of this effect aborts any in-flight attach SSE (the backend
  // then sees zero watchers; the turn itself keeps running). Tying the abort
  // to this effect instead of a separate [] cleanup avoids the race where
  // React’s StrictMode double-mount (or a same-cycle re-render) abort the
  // signal immediately after starting it.
  useEffect(() => {
    if (!sessionId || isRequesting) return
    if (initialRunning || presenceRunning.has(sessionId)) {
      startAttach()
    } else {
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
        attachCtrlRef.current?.abort()
        attachCtrlRef.current = null
      }
    }
    return () => {
      attachCtrlRef.current?.abort()
      attachCtrlRef.current = null
    }
  }, [sessionId, isRequesting, initialRunning, presenceRunning, startAttach])

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
        setDisplayHistory(
          historyToAgentMessages(msgs as unknown as HistoryMessage[])
        )
        // Bump seed atomically with the history update: newEntries becomes
        // empty in the same render that displayHistory becomes fresh.
        seedLenRef.current = messagesLenRef.current
        // The canonical history now carries the real interrupted marker.
        setStoppedLocally(false)
      })
      .catch(() => {})
  }, [])

  // Items computation: displayHistory + newEntries (current streaming turn) +
  // attachMessage (if re-attaching). No splice, no liveTail insertion.
  const newEntries = messages.slice(seedLenRef.current)
  let items: ChatMessageItem[]
  if (messages.length === 0 && displayHistory.length > 0) {
    // SSR / first-render fallback (useXChat seeds async).
    items = displayHistory.map((message, i) => ({
      id: `hist-${i}`,
      message,
      status: 'success' as const
    })) as ChatMessageItem[]
  } else if (newEntries.length > 0) {
    // Active turn: canonical history + the streaming entries from useXChat.
    items = [
      ...displayHistory.map((message, i) => ({
        id: `hist-${i}`,
        message,
        status: 'success' as const
      })),
      ...newEntries
    ] as ChatMessageItem[]
  } else {
    // Idle (between turns): show canonical history.
    items = displayHistory.map((message, i) => ({
      id: `hist-${i}`,
      message,
      status: 'success' as const
    })) as ChatMessageItem[]
  }
  // Attach streaming message (live re-attach to a background turn).
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
                  (it.message.turnStartedAt
                    ? Math.max(0, stoppedAtRef.current - it.message.turnStartedAt)
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

  return (
    <div className="flex min-h-0 flex-1 flex-col p-[14px]">
      {/*
        Centered content column. Fills the width when the workspace rail is
        closed (w-full) and narrows to w-[80%] when it opens, leaving ~20%
        whitespace on the right. The width transition is kept perfectly in
        sync with the rail's own animation (same 300ms cubic-bezier), so the
        combined motion — this percentage shrinking × the section being
        squeezed — stays continuous and strictly monotonic (no brief grow).
      */}
      <div
        className={`mx-auto flex min-h-0 flex-1 flex-col transition-[width] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] ${
          !workspaceOpen ? 'w-full xl:w-[80%]' : 'w-full'
        }`}
      >
        {/*
          Only the message list is client-only: XMarkdown parses on the client
          (e.g. wrapping text in <p>), so server-rendering it would cause a
          hydration mismatch. The composer/sender below is SSR-safe, so we keep
          the full chat layout and swap just the list for a matching skeleton
          until hydration. useHydrated is module-level, so client-side
          navigations (no SSR) see the real list immediately with no flash.
        */}
        {hydrated ? (
          <MessageList
            ref={listRef}
            items={items}
            sessionId={sessionId ?? startedSessionId}
            onOpenStep={onOpenStep}
            onOpenFile={onOpenFile}
          />
        ) : (
          <MessageListSkeleton items={items} />
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
  )
}
