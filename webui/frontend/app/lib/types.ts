/**
 * REST schemas mirrored from backend/app/schemas. The agent chat wire format
 * lives in agentProvider.ts since it's tightly coupled to the SSE pipeline.
 */

export type MemoryBackend = 'file' | 'vector'

/** Project-level tool authorization: 'restricted' = every non-whitelisted
 * tool asks (default), 'auto' = full access, no asks. */
export type PermissionMode = 'restricted' | 'auto'

export interface Project {
  id: string
  name: string
  description: string
  local_path: string
  is_default: boolean
  memory_enabled: boolean
  memory_backend: MemoryBackend
  mcp_auto_attach: boolean
  skill_auto_attach: boolean
  permission_mode: PermissionMode
  created_at: string
}

export interface Session {
  id: string
  title: string
  project_id?: string | null
  updated_at: string
  preview?: string
  /** True while the session has a turn in flight (live or background). */
  running?: boolean
  // Agent-assigned topic category (backend ms_agent/titler.CATEGORIES); '' or
  // undefined until the session's first message is classified. Drives the
  // recent-conversations topic icon.
  category?: string
}

export interface SessionMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  // Ordered turn view-model rebuilt by the backend from the session log (mirrors
  // schemas/session.py::SessionMessage) so history echoes the same interleaving
  // as a live turn. kind:"thought" replays a persisted reasoning block (no
  // duration — the log has no elapsed time). A failed tool step carries
  // meta.status="error"; a kind:"error" part is an API/turn error
  // (recoverable=false).
  parts?: {
    kind: 'text' | 'thought' | 'tasks' | 'error'
    text?: string
    recoverable?: boolean
    tasks?: {
      id: string
      label: string
      status: string
      steps: { kind: string; meta: Record<string, unknown> }[]
    }[]
  }[]
  // User turns only: files attached to the message, reconstructed by the backend
  // from the persisted attachment block. `exists` is false when the workspace
  // file has since been deleted.
  files?: {
    name: string
    path: string
    url?: string
    type?: 'file' | 'image' | 'audio' | 'video'
    size?: number
    exists?: boolean
  }[]
  // Configuration-style content echo (user rows only): same segment shape the
  // composer sends, rebuilt by the backend so skill pills re-render on replay.
  segments?: { type: 'text' | 'skill'; text?: string; id?: string; name?: string }[]
}

/** One item of a session's live todo plan, read from the workspace plan.json
 * (mirrors schemas/session.py::SessionTask). status: pending|running|done. */
export interface SessionPlanTask {
  id: string
  label: string
  status: string
}

/** The session's live plan plus whether it belongs to the CURRENT running
 * turn — the server-side truth for animating "running" rows (stable across
 * reloads and tab switch-backs; a stale in_progress row stays inactive).
 * Mirrors schemas/session.py::SessionPlan. */
export interface SessionPlan {
  tasks: SessionPlanTask[]
  active: boolean
}

export interface Artifact {
  id: string
  session_id: string
  path: string
  /** Basename for display. */
  name: string
  kind: string
  size: number
  updated_at: string
  /** Agent wrote it during the session but it's gone from disk now. */
  deleted?: boolean
  preview?: string | null
}

export type Scope = 'global' | `project:${string}`

export type McpTransport = 'stdio' | 'http' | 'sse' | 'streamable_http'

export interface Mcp {
  id: string
  name: string
  description: string
  transport: McpTransport
  endpoint: string
  enabled: boolean
  scope: Scope
  /** stdio env vars / remote auth headers (ms_agent backend round-trips these). */
  env?: Record<string, string>
  headers?: Record<string, string>
  created_at: string
}

export interface McpHealth {
  id: string
  name: string
  scope: string
  healthy: boolean
  error?: string | null
}

export interface Skill {
  id: string
  name: string
  kind: string
  content: string
  enabled: boolean
  scope: Scope
  created_at: string
}

export interface MemoryItem {
  id: string
  project_id: string
  content: string
  updated_at: string
}

export interface WorkspaceFile {
  project_id: string
  path: string
  kind: string
  size: number
  updated_at: string
  preview?: string | null
  // Full text content, only present on single-file GET (null for binary/folders).
  content?: string | null
  // Best-effort MIME type (from the extension). Used to pick the preview:
  // text -> Monaco, image/video/audio -> media element, else -> unsupported.
  content_type?: string | null
}

export interface Instruction {
  scope: Scope
  content: string
  updated_at: string
}

export interface Profile {
  agent_calls_user: string
  description: string
  updated_at: string
}

export type ProviderKind = 'builtin' | 'custom'
export type Protocol = 'openai' | 'anthropic'

export interface Provider {
  id: string
  kind: ProviderKind
  name: string
  base_url: string
  api_key_masked: string
  protocol: Protocol
  enabled: boolean
  default_generation_params: Record<string, unknown>
  created_at: string
}

export interface Model {
  id: string
  provider_id: string
  name: string
  display_name: string
  is_builtin: boolean
  advanced_params: Record<string, unknown>
  created_at: string
}

export interface AgentSettings {
  default_provider_id: string | null
  default_model_id: string | null
  default_memory_enabled: boolean
  default_memory_backend: MemoryBackend
  global_mcp_auto_attach: boolean
  global_skill_auto_attach: boolean
}
