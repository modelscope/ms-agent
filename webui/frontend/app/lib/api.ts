import type {
  AgentSettings,
  Artifact,
  Instruction,
  Mcp,
  McpHealth,
  MemoryBackend,
  MemoryItem,
  Model,
  Profile,
  Project,
  Provider,
  Scope,
  Session,
  SessionMessage,
  SessionPlan,
  Skill,
  WorkspaceFile
} from './types'

// On the server (loaders/SSR) there is no page origin, so relative `/api`
// paths can't be fetched. Resolve them against the backend directly. In the
// browser this stays empty so the same-origin proxy / nginx handles routing.
const SERVER_API_BASE =
  typeof window === 'undefined'
    ? (process.env.API_BASE_URL ?? 'http://127.0.0.1:8000')
    : ''

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

/**
 * Error thrown by the REST client when a request fails (non-2xx, envelope
 * `code !== 0`, or a network/parse failure). Carries the resolved,
 * user-facing `message` and the HTTP `status` for call-site branching.
 */
export class ApiError extends Error {
  status: number
  code: number
  constructor(message: string, status: number, code: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
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

    if (!res.ok) {
      const message = isEnvelope(body) ? body.message : ''
      const code = isEnvelope(body) ? body.code : res.status
      const err = new ApiError(message, res.status, code)
      if (!suppresses(opts, res.status)) reportError?.(message, err)
      throw err
    }

    if (isEnvelope(body)) return body.data as T
    // Fallback: bodiless success or a non-enveloped payload.
    return (body as T) ?? (undefined as T)
  })()
  if (key) {
    inflightGets.set(key, run)
    void run.finally(() => {
      if (inflightGets.get(key) === run) inflightGets.delete(key)
    })
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
  }) =>
    json<Session>('/api/sessions', {
      method: 'POST',
      body: JSON.stringify(body)
    }),
  deleteSession: (id: string) =>
    json<void>(`/api/sessions/${pid(id)}`, { method: 'DELETE' }),
  updateSession: (id: string, body: { title?: string }) =>
    json<Session>(`/api/sessions/${pid(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(body)
    }),
  listArtifacts: (sessionId: string) =>
    json<Artifact[]>(`/api/sessions/${pid(sessionId)}/artifacts`),

  // MCPs
  listMcps: (scope?: Scope) => json<Mcp[]>(`/api/mcps${q({ scope })}`),
  createMcp: (body: Omit<Mcp, 'id' | 'created_at'>) =>
    json<Mcp>('/api/mcps', { method: 'POST', body: JSON.stringify(body) }),
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
  checkMcpHealth: (id: string) => json<McpHealth>(`/api/mcps/${pid(id)}/health`),

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
  createSkill: (body: Omit<Skill, 'id' | 'created_at'>) =>
    json<Skill>('/api/skills', { method: 'POST', body: JSON.stringify(body) }),
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

  // Memory — project-scoped items. Default project rejects (400).
  listMemoryItems: (projectId: string) =>
    json<MemoryItem[]>(`/api/projects/${pid(projectId)}/memory/items`),
  createMemoryItem: (projectId: string, content: string) =>
    json<MemoryItem>(`/api/projects/${pid(projectId)}/memory/items`, {
      method: 'POST',
      body: JSON.stringify({ content })
    }),
  updateMemoryItem: (projectId: string, itemId: string, content: string) =>
    json<MemoryItem>(
      `/api/projects/${pid(projectId)}/memory/items/${pid(itemId)}`,
      {
        method: 'PUT',
        body: JSON.stringify({ content })
      }
    ),
  deleteMemoryItem: (projectId: string, itemId: string) =>
    json<void>(`/api/projects/${pid(projectId)}/memory/items/${pid(itemId)}`, {
      method: 'DELETE'
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
  // URL for raw file bytes (media <img>/<video>/<audio> src, or download).
  // Relative so the same-origin proxy routes it; browser-only usage.
  workspaceFileRawUrl: (projectId: string, path: string) =>
    `/api/projects/${pid(projectId)}/workspace/files/${fp(path)}/raw`,
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
    name: string
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
  createModel: (body: {
    provider_id: string
    name: string
    display_name?: string
    advanced_params?: Record<string, unknown>
  }) =>
    json<Model>('/api/models', { method: 'POST', body: JSON.stringify(body) }),
  updateModel: (
    id: string,
    body: Partial<{
      display_name: string
      advanced_params: Record<string, unknown>
    }>
  ) =>
    json<Model>(`/api/models/${pid(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(body)
    }),
  deleteModel: (id: string) =>
    json<void>(`/api/models/${pid(id)}`, { method: 'DELETE' }),

  getAgentSettings: () => json<AgentSettings>('/api/agent-settings'),
  putAgentSettings: (body: AgentSettings) =>
    json<AgentSettings>('/api/agent-settings', {
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
