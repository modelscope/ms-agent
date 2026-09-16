import { SERVER_API_BASE } from './env'
import type {
  AgentSettings,
  Artifact,
  GenerationDefaults,
  Instruction,
  Mcp,
  McpHealth,
  MemoryBackend,
  MemoryDoc,
  MemoryItem,
  MemoryRebuildResult,
  MemoryStatus,
  Model,
  Profile,
  Project,
  Provider,
  Scope,
  SearchProvider,
  SearchSettings,
  SearchSettingsUpdate,
  Session,
  SessionMessage,
  SessionPlan,
  Skill,
  WorkspaceFile
} from './types'

// On the server (loaders/SSR) there is no page origin, so relative `/api` paths
// can't be fetched; `SERVER_API_BASE` resolves them against the backend and is
// empty in the browser, where a same-origin proxy handles routing (vite's in
// dev, `frontend/server.js` in production).
// Declared in `env.ts` — the single place this app reads `process.env`.
const resolve = (input: RequestInfo): RequestInfo =>
  SERVER_API_BASE && typeof input === 'string' && input.startsWith('/')
    ? SERVER_API_BASE + input
    : input

/**
 * Uniform response envelope every non-chat backend endpoint returns:
 * `{ code, message, data }`. `code === 0` means success; anything else is an
 * error whose `message` is safe to surface to the user.
 */
export interface ApiEnvelope<T = unknown> {
  code: number
  message: string
  data: T
}

export interface RecoveryStatus {
  required: boolean
  backup_path: string | null
  error: 'backup_failed' | 'repair_failed' | 'startup_failed' | null
}

/**
 * Error thrown by the REST client when a request fails (non-2xx, envelope
 * `code !== 0`, or a network/parse failure). Carries the resolved,
 * user-facing `message` and the HTTP `status` for call-site branching.
 */
export class ApiError extends Error {
  status: number
  code: number
  /** HTTP reason phrase (`Bad Gateway`), the only human-readable text a failure
   * from IN FRONT of our backend carries. Best-effort: HTTP/2 dropped reason
   * phrases, so behind an h2 gateway browsers report it as ''. Never rely on it
   * being there. */
  statusText: string
  constructor(
    message: string,
    status: number,
    code: number,
    statusText = ''
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.statusText = statusText
  }
}

// Global error reporter, registered once in the browser by the app shell (see
// root.tsx). Lets the API layer surface a single, consistent toast for every
// failed request without each call site repeating `message.error(...)`. Stays
// null during SSR so loaders just throw (handled by route ErrorBoundary).
type ApiErrorReporter = (message: string, err: ApiError) => void
let reportError: ApiErrorReporter | null = null

export function registerApiErrorReporter(fn: ApiErrorReporter | null): void {
  reportError = fn
}

interface JsonOpts {
  // Suppress the global error toast for this call. `true` suppresses every
  // failure (best-effort loads / background helpers); a status-code list
  // suppresses only those codes (e.g. `[409]` to ignore an idempotent
  // create-conflict while still surfacing genuine failures).
  silent?: boolean | number[]
}

/** Per-call options shared by REST methods that support silencing errors. */
export type ApiCallOpts = JsonOpts

const suppresses = (opts: JsonOpts | undefined, status: number): boolean => {
  if (opts?.silent === true) return true
  if (Array.isArray(opts?.silent)) return opts.silent.includes(status)
  return false
}

function isEnvelope(v: unknown): v is ApiEnvelope {
  return (
    typeof v === 'object' &&
    v !== null &&
    'code' in v &&
    'message' in v &&
    'data' in v
  )
}

/** Failure declared by a body's own non-zero `code`, whether or not it carries
 * a `data` key.
 *
 * Our backend always answers with the full `{ code, message, data }` envelope,
 * but a request can be answered by something sitting IN FRONT of it: the
 * ModelScope gateway rejects a request whose content trips its security
 * inspection with `{ code: 400, message }` — no `data` at all.
 * Requiring `data` to recognise an envelope meant such a body was not an
 * envelope, so its message never reached the toast; and since a non-zero code
 * was only ever read on a non-2xx response, a rejection delivered with a 2xx
 * status passed as SUCCESS — the error object itself became the payload and
 * nothing was reported to the user.
 *
 * Exported because the streaming paths (POST /api/chat and /api/chat/attach)
 * bypass `json()` entirely yet face the same gateway — see `assertChatStream`. */
export function readFailure(
  v: unknown
): { code: number; message: string } | null {
  if (typeof v !== 'object' || v === null) return null
  const { code, message } = v as { code?: unknown; message?: unknown }
  if (typeof code !== 'number' || code === 0) return null
  return { code, message: typeof message === 'string' ? message : '' }
}

// De-duplicate concurrent identical GETs. On a session open several components
// (e.g. two Composer instances + pills) each fetch models/mcps/skills/settings
// at once; sharing one in-flight request per URL avoids a request storm and the
// latency it adds. Browser-only (a module-level map must not be shared across
// SSR requests) and in-flight only (cleared on settle → later fetches are
// fresh, so mutations + refetches still see up-to-date data).
const inflightGets = new Map<string, Promise<unknown>>()

async function json<T>(
  input: RequestInfo,
  init?: RequestInit,
  opts?: JsonOpts
): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase()
  const key =
    typeof window !== 'undefined' &&
    method === 'GET' &&
    typeof input === 'string'
      ? input
      : null
  if (key) {
    const pending = inflightGets.get(key)
    if (pending) return pending as Promise<T>
  }
  const run = (async () => {
    let res: Response
    try {
      res = await fetch(resolve(input), {
        headers: { 'Content-Type': 'application/json' },
        ...init
      })
    } catch {
      // Network / connection failure — no HTTP response at all.
      const err = new ApiError('', 0, -1)
      if (!suppresses(opts, 0)) reportError?.('', err)
      throw err
    }

    // Parse the body once; every endpoint returns the JSON envelope (204s and
    // empty bodies are tolerated for safety).
    const text = await res.text()
    let body: unknown = undefined
    if (text) {
      try {
        body = JSON.parse(text)
      } catch {
        body = undefined
      }
    }

    // A failure is either transport-level (non-2xx) or declared by the body
    // itself through a non-zero `code` — an intercepting gateway may report its
    // rejection with a 2xx status, and that is still a failure, not a payload.
    const failure = readFailure(body)
    if (!res.ok || failure) {
      const message = failure?.message ?? ''
      const err = new ApiError(
        message,
        res.status,
        failure?.code ?? res.status,
        res.statusText
      )
      if (!suppresses(opts, res.status)) reportError?.(message, err)
      throw err
    }

    if (isEnvelope(body)) return body.data as T
    // Fallback: bodiless success or a non-enveloped payload.
    return (body as T) ?? (undefined as T)
  })()
  if (key) {
    inflightGets.set(key, run)
    // `then(f, f)` rather than `finally`: a derived promise from `.finally()`
    // re-throws the rejection with nobody to catch it, so every failed deduped
    // GET logged an "Uncaught (in promise)" even though the caller handled it.
    const clear = () => {
      if (inflightGets.get(key) === run) inflightGets.delete(key)
    }
    run.then(clear, clear)
  }
  return run
}

const q = (params: Record<string, string | undefined>) => {
  const usp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined) usp.set(k, v)
  }
  const s = usp.toString()
  return s ? `?${s}` : ''
}

const pid = (id: string) => encodeURIComponent(id)
// Memory/workspace files allow slashes — encode each segment individually so
// `path/to/file.md` survives intact.
const fp = (path: string) =>
  path
    .split('/')
    .map((seg) => encodeURIComponent(seg))
    .join('/')

/**
 * Stateless REST helpers. The chat stream is owned by AgentChatProvider +
 * useXChat (see app/lib/agentProvider.ts), not this module.
 */
export const api = {
  getRecoveryStatus: () => json<RecoveryStatus>('/api/recovery', undefined, { silent: true }),
  repairDefaultProject: () =>
    json<RecoveryStatus>('/api/recovery/default-project', {
      method: 'POST',
      body: JSON.stringify({ confirm: true })
    }, { silent: true }),
  // Projects
  listProjects: () => json<Project[]>('/api/projects'),
  createProject: (body: {
    name: string
    description?: string
    local_path?: string
    memory_enabled?: boolean
    memory_backend?: MemoryBackend
  }) =>
    json<Project>('/api/projects', {
      method: 'POST',
      body: JSON.stringify(body)
    }),
  getProject: (id: string) => json<Project>(`/api/projects/${pid(id)}`),
  updateProject: (
    id: string,
    body: Partial<{
      name: string
      description: string
      local_path: string
      memory_enabled: boolean
      // Accepted only while the project has never had memory enabled; the
      // server answers 400 for a change once it is locked.
      memory_backend: MemoryBackend
      mcp_auto_attach: boolean
      skill_auto_attach: boolean
      permission_mode: 'restricted' | 'auto'
    }>
  ) =>
    json<Project>(`/api/projects/${pid(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(body)
    }),
  deleteProject: (id: string) =>
    json<void>(`/api/projects/${pid(id)}`, { method: 'DELETE' }),

  // Sessions
  listSessions: (projectId?: string) =>
    json<Session[]>(`/api/sessions${q({ project_id: projectId })}`),
  getSession: (id: string, opts?: ApiCallOpts) =>
    json<Session>(`/api/sessions/${pid(id)}`, {}, opts),
  listSessionMessages: (id: string, opts?: ApiCallOpts) =>
    json<SessionMessage[]>(`/api/sessions/${pid(id)}/messages`, {}, opts),
  getSessionPlan: (id: string, opts?: ApiCallOpts) =>
    json<SessionPlan>(`/api/sessions/${pid(id)}/plan`, {}, opts),
  createSession: (body: {
    title: string
    project_id?: string
    preview?: string
    model_id?: string
  }) =>
    json<Session>('/api/sessions', {
      method: 'POST',
      body: JSON.stringify(body)
    }),
  updateSessionModel: (id: string, modelId: string) =>
    json<{ session: Session; settings: AgentSettings }>(`/api/sessions/${pid(id)}/model`, {
      method: 'PATCH',
      body: JSON.stringify({ model_id: modelId })
    }),
  deleteSession: (id: string) =>
    json<void>(`/api/sessions/${pid(id)}`, { method: 'DELETE' }),
  updateSession: (id: string, body: { title?: string }) =>
    json<Session>(`/api/sessions/${pid(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(body)
    }),
  /** Acknowledge a turn that finished unwatched, clearing the sidebar's unread
   * dot. Silent: this is a background bookkeeping write the user never asked
   * for, so a failure must not raise a toast over the conversation. */
  markSessionRead: (id: string) =>
    json<void>(
      `/api/sessions/${pid(id)}/read`,
      { method: 'POST' },
      { silent: true }
    ),
  listArtifacts: (sessionId: string) =>
    json<Artifact[]>(`/api/sessions/${pid(sessionId)}/artifacts`),
  // Browser-only URL for a credentialed Blob download (see download.ts).
  sessionExportUrl: (
    sessionId: string,
    format: 'markdown' | 'html',
    detail: 'full' | 'compact' | 'user-only'
  ) =>
    `/api/sessions/${pid(sessionId)}/export${q({ format, detail })}`,

  // MCPs
  listMcps: (scope?: Scope) => json<Mcp[]>(`/api/mcps${q({ scope })}`),
  createMcp: (body: Omit<Mcp, 'id' | 'created_at'>) =>
    json<Mcp>('/api/mcps', { method: 'POST', body: JSON.stringify(body) }),
  /** Replace a scope's servers with exactly `servers`, in this order — one
   * atomic call for the raw-JSON editor, whose document IS the whole scope.
   * Doing it client-side (delete every server, then re-create) lost everything
   * whenever a later create was rejected. */
  replaceMcps: (scope: Scope, servers: Omit<Mcp, 'id' | 'created_at'>[]) =>
    json<Mcp[]>('/api/mcps', {
      method: 'PUT',
      body: JSON.stringify({ scope, servers })
    }),
  updateMcp: (
    id: string,
    body: Partial<Omit<Mcp, 'id' | 'created_at' | 'scope'>>
  ) =>
    json<Mcp>(`/api/mcps/${pid(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(body)
    }),
  deleteMcp: (id: string) =>
    json<void>(`/api/mcps/${pid(id)}`, { method: 'DELETE' }),
  checkMcpHealth: (id: string) =>
    json<McpHealth>(`/api/mcps/${pid(id)}/health`),
  /** Reachability of every ENABLED server, across scopes. Cached server-side,
   *  but only 60 s for a reachable server and 10 s for a dead one (a pinned
   *  failure withholds its tools from a whole conversation), so a miss costs
   *  the full probe — go through `lib/mcpHealth`, which shares one sweep across
   *  every surface, rather than calling this per mount. */
  listMcpHealth: () => json<McpHealth[]>('/api/mcps/health'),

  // Skills
  listSkills: (scope?: Scope) => json<Skill[]>(`/api/skills${q({ scope })}`),
  /** Real file listing of a skill's on-disk directory (detail viewer tree). */
  listSkillFiles: (id: string) =>
    json<{ path: string; size?: number | null }[]>(
      `/api/skills/${encodeURIComponent(id)}/files`
    ),
  /** One skill file's UTF-8 content; `content: null` marks a binary file. */
  getSkillFile: (id: string, path: string) =>
    json<{ path: string; content: string | null }>(
      `/api/skills/${encodeURIComponent(id)}/file?path=${encodeURIComponent(path)}`
    ),
  /** URL for a skill file's raw bytes — what a previewed document in the skill
   * viewer loads its images and styles from. Browser-only usage. */
  skillFileRawUrl: (id: string, path: string) =>
    `/api/skills/${encodeURIComponent(id)}/raw/${fp(path)}`,
  createSkill: (
    body: Omit<Skill, 'id' | 'created_at' | 'origin' | 'removable'> & {
      /** Bundle imports only: replace a same-named skill in this scope instead
       * of being rejected with 409. */
      overwrite?: boolean
    },
    opts?: ApiCallOpts
  ) =>
    json<Skill>(
      '/api/skills',
      { method: 'POST', body: JSON.stringify(body) },
      opts
    ),
  importSkillsFromPath: (
    body: { path: string; scope: Scope; overwrite?: boolean },
    opts?: ApiCallOpts
  ) =>
    json<Skill[]>(
      '/api/skills/import-path',
      { method: 'POST', body: JSON.stringify(body) },
      opts
    ),
  updateSkill: (
    id: string,
    body: Partial<Omit<Skill, 'id' | 'created_at' | 'scope'>>
  ) =>
    json<Skill>(`/api/skills/${pid(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(body)
    }),
  deleteSkill: (id: string) =>
    json<void>(`/api/skills/${pid(id)}`, { method: 'DELETE' }),

  // Memory — project-scoped items. 400s when the project has memory off.
  // The vector card renders load failures itself (a misconfigured vector
  // backend is a legible state, not a transient error), so it passes
  // `{ silent: true }` to keep the global toast out of it.
  listMemoryItems: (projectId: string, opts?: ApiCallOpts) =>
    json<MemoryItem[]>(
      `/api/projects/${pid(projectId)}/memory/items`,
      {},
      opts
    ),
  deleteMemoryItem: (projectId: string, itemId: string) =>
    json<void>(`/api/projects/${pid(projectId)}/memory/items/${pid(itemId)}`, {
      method: 'DELETE'
    }),
  // Memory health: resolved embedder identity, why vector memory is unusable
  // (machine-readable code), last background-ingest outcome.
  getMemoryStatus: (projectId: string, opts?: ApiCallOpts) =>
    json<MemoryStatus>(
      `/api/projects/${pid(projectId)}/memory/status`,
      {},
      opts
    ),
  // Re-embed the store with the current embedder (the remedy for an embedder
  // mismatch): entries are carried over, the old store is kept as a backup, and
  // the swap happens only once the new one is complete. 409 if one is running.
  rebuildMemory: (projectId: string) =>
    json<MemoryRebuildResult>(
      `/api/projects/${pid(projectId)}/memory/rebuild`,
      { method: 'POST' }
    ),

  // Memory as ONE markdown document — file backend only (vector rejects with
  // 400). Same store as the item endpoints above, viewed wholesale.
  getMemoryDoc: (projectId: string, opts?: ApiCallOpts) =>
    json<MemoryDoc>(`/api/projects/${pid(projectId)}/memory/doc`, {}, opts),
  putMemoryDoc: (projectId: string, content: string) =>
    json<MemoryDoc>(`/api/projects/${pid(projectId)}/memory/doc`, {
      method: 'PUT',
      body: JSON.stringify({ content })
    }),

  // Workspace files
  listWorkspaceFiles: (projectId: string, opts?: ApiCallOpts) =>
    json<WorkspaceFile[]>(
      `/api/projects/${pid(projectId)}/workspace/files`,
      undefined,
      opts
    ),
  createWorkspaceFile: (
    projectId: string,
    body: { path: string; content?: string; kind?: string; size?: number },
    opts?: ApiCallOpts
  ) =>
    json<WorkspaceFile>(
      `/api/projects/${pid(projectId)}/workspace/files`,
      {
        method: 'POST',
        body: JSON.stringify(body)
      },
      opts
    ),
  getWorkspaceFile: (projectId: string, path: string, opts?: ApiCallOpts) =>
    json<WorkspaceFile>(
      `/api/projects/${pid(projectId)}/workspace/files/${fp(path)}`,
      undefined,
      opts
    ),
  // Binary-safe upload via multipart/form-data. `path` (optional) sets the
  // destination relative path; otherwise the browser file name is used. When
  // `dedup` is set, a same-named-but-different file is auto-suffixed server-side
  // (chat attachments into user_files/) and the returned `path` is the real,
  // deduped location. The empty `headers` lets the browser set multipart
  // Content-Type + boundary.
  uploadWorkspaceFile: (
    projectId: string,
    file: File,
    path?: string,
    opts?: ApiCallOpts & { dedup?: boolean }
  ) => {
    const form = new FormData()
    form.append('file', file)
    if (path) form.append('path', path)
    if (opts?.dedup) form.append('dedup', 'true')
    return json<WorkspaceFile>(
      `/api/projects/${pid(projectId)}/workspace/files/upload`,
      { method: 'POST', body: form, headers: {} },
      opts
    )
  },
  // URL for raw file bytes (media <img>/<video>/<audio> src, an HTML preview's
  // iframe, or download). Relative so the same-origin proxy routes it;
  // browser-only usage. The path is the URL tail so a previewed document's own
  // relative references resolve back into this route.
  workspaceFileRawUrl: (projectId: string, path: string) =>
    `/api/projects/${pid(projectId)}/workspace/raw/${fp(path)}`,
  // URL for a zip of the workspace, or of one folder in it. The server builds
  // and streams the archive; `path` is omitted for the whole workspace. Not
  // under `/files/` — that route's catch-all would swallow the segment.
  workspaceArchiveUrl: (projectId: string, path?: string) =>
    `/api/projects/${pid(projectId)}/workspace/archive${
      path ? `?path=${encodeURIComponent(path)}` : ''
    }`,
  deleteWorkspaceFile: (projectId: string, path: string, opts?: ApiCallOpts) =>
    json<void>(
      `/api/projects/${pid(projectId)}/workspace/files/${fp(path)}`,
      {
        method: 'DELETE'
      },
      opts
    ),
  putWorkspaceFile: (projectId: string, path: string, content: string) =>
    json<WorkspaceFile>(
      `/api/projects/${pid(projectId)}/workspace/files/${fp(path)}`,
      {
        method: 'PUT',
        body: JSON.stringify({ content })
      }
    ),
  // Rename or move a file/folder within the workspace (both paths are
  // workspace-relative). Folder moves carry their children server-side.
  moveWorkspaceFile: (
    projectId: string,
    src: string,
    dst: string,
    opts?: ApiCallOpts
  ) =>
    json<WorkspaceFile>(
      `/api/projects/${pid(projectId)}/workspace/files/move`,
      {
        method: 'POST',
        body: JSON.stringify({ src, dst })
      },
      opts
    ),

  // Instructions (single blob per scope). Used by the personalization page +
  // the project rail's InstructionsCard.
  getInstruction: (scope: Scope) =>
    json<Instruction>(`/api/instructions${q({ scope })}`),
  putInstruction: (scope: Scope, content: string) =>
    json<Instruction>(`/api/instructions${q({ scope })}`, {
      method: 'PUT',
      body: JSON.stringify({ content })
    }),

  // Profile (global singleton — user.md analogue)
  getProfile: () => json<Profile>('/api/profile'),
  putProfile: (
    body: Partial<Pick<Profile, 'agent_calls_user' | 'description'>>
  ) =>
    json<Profile>('/api/profile', {
      method: 'PUT',
      body: JSON.stringify(body)
    }),

  // Providers + Models
  listProviders: () => json<Provider[]>('/api/providers'),
  createProvider: (body: {
    id: string
    /** Optional — the server falls back to the id. */
    name?: string
    base_url?: string
    protocol?: 'openai' | 'anthropic'
    default_generation_params?: Record<string, unknown>
  }) =>
    json<Provider>('/api/providers', {
      method: 'POST',
      body: JSON.stringify(body)
    }),
  updateProvider: (
    id: string,
    body: Partial<{
      name: string
      base_url: string
      api_key: string
      protocol: 'openai' | 'anthropic'
      enabled: boolean
      default_generation_params: Record<string, unknown>
    }>
  ) =>
    json<Provider>(`/api/providers/${pid(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(body)
    }),
  deleteProvider: (id: string) =>
    json<void>(`/api/providers/${pid(id)}`, { method: 'DELETE' }),
  listProviderModels: (id: string, opts?: ApiCallOpts) =>
    json<string[]>(
      `/api/providers/${pid(id)}/available-models`,
      undefined,
      opts
    ),

  listModels: (providerId?: string) =>
    json<Model[]>(`/api/models${q({ provider_id: providerId })}`),
  /** What the runtime will send for this provider/model before any override. */
  getGenerationDefaults: (
    providerId: string,
    model: string,
    opts?: ApiCallOpts
  ) =>
    json<GenerationDefaults>(
      `/api/models/generation-defaults${q({ provider_id: providerId, model })}`,
      undefined,
      opts
    ),
  createModel: (body: {
    provider_id: string
    name: string
    display_name?: string
    advanced_params?: Record<string, unknown>
    supports_vision?: boolean | null
  }) =>
    json<Model>('/api/models', { method: 'POST', body: JSON.stringify(body) }),
  updateModel: (
    id: string,
    body: Partial<{
      display_name: string
      advanced_params: Record<string, unknown>
      supports_vision: boolean | null
    }>
  ) =>
    json<Model>(`/api/models/${pid(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(body)
    }),
  deleteModel: (id: string) =>
    json<void>(`/api/models/${pid(id)}`, { method: 'DELETE' }),
  /** Forget that this model was seen refusing images, and try again.
   *
   * The runtime remembers a refusal so a conversation stops paying for a
   * request it expects to fail — but that record is a cache, and a rate limit
   * or a gateway hiccup can write one. Before this existed the only way to
   * revoke it was restarting the backend. */
  retryVision: (id: string) =>
    json<Model>(`/api/models/${pid(id)}/vision/retry`, { method: 'POST' }),

  getAgentSettings: () => json<AgentSettings>('/api/agent-settings'),
  putAgentSettings: (body: Partial<AgentSettings>) =>
    json<AgentSettings>('/api/agent-settings', {
      method: 'PUT',
      body: JSON.stringify(body)
    }),

  listSearchProviders: () =>
    json<SearchProvider[]>('/api/search-settings/providers'),
  getSearchSettings: () => json<SearchSettings>('/api/search-settings'),
  putSearchSettings: (body: SearchSettingsUpdate) =>
    json<SearchSettings>('/api/search-settings', {
      method: 'PUT',
      body: JSON.stringify(body)
    }),

  // Chat permission (restricted mode): answer an authorization step card. The
  // agent turn is suspended on request_id until resolved (or times out to deny).
  resolvePermission: (body: {
    session_id: string
    request_id: string
    action: 'allow_once' | 'allow_always' | 'deny'
  }) =>
    json<{ resolved: boolean }>('/api/chat/permission', {
      method: 'POST',
      body: JSON.stringify(body)
    }),

  // Explicitly stop a session's in-flight turn (the composer Stop button).
  // Distinct from merely closing the SSE (navigating away), which keeps the turn
  // running in the background; only this cancels it and seals it as interrupted.
  interruptChat: (sessionId: string) =>
    json<{ stopped: boolean }>('/api/chat/interrupt', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId })
    }),

  // Browser presence heartbeat (~10s cadence, sent by the app shell). Keeps
  // background turns alive across refresh/navigation and returns the sessions
  // with a turn in flight (drives the sidebar running spinners).
  postPresence: () =>
    json<{ running: string[] }>('/api/presence', { method: 'POST' })
}

/** Status a loader failure reaches the error page as.
 *
 * `Response` rejects anything outside 200-599, and an `ApiError` may carry no
 * HTTP status (0 when the backend is unreachable) or a 2xx for a body-declared
 * rejection. 502 stands for "no answer from the backend"; the error page turns
 * it back into the network message. */
function errorPageStatus(status: number): number {
  if (status === 0) return 502
  return status >= 400 && status <= 599 ? status : 500
}

/**
 * Turn an API failure inside a route loader into a thrown `Response`.
 *
 * A raw `ApiError` cannot survive the SSR boundary: React Router serializes a
 * loader error to the client as a plain Error, dropping both the class and the
 * `status`. The error page would then render 404 on the server and "unexpected
 * error" after hydration — a visible downgrade. A thrown Response carries its
 * status across intact, so both sides agree. Every server-side loader must go
 * through here, `Promise.all` batches included.
 */
export async function orThrow<T>(promise: Promise<T>): Promise<T> {
  try {
    return await promise
  } catch (err) {
    if (err instanceof ApiError)
      throw new Response(err.message, { status: errorPageStatus(err.status) })
    throw err
  }
}
