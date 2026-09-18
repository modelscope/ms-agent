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
  /** True once memory has been saved as enabled at least once: the backend
   * choice is frozen from then on (it decides the on-disk storage layout).
   * Toggling `memory_enabled` itself stays allowed. */
  memory_backend_locked: boolean
  /** Project-owned memory-model group (materialized from global defaults at
   * creation; global changes never touch existing projects). */
  memory_llm_provider_id: string | null
  memory_llm_model: string | null
  memory_embed_mode: 'provider' | 'local'
  memory_embed_provider_id: string | null
  memory_embed_model: string | null
  memory_recall_top_k: number | null
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
  /** A turn finished with nobody watching, and the session has not been opened
   * since. Once the spinner goes away nothing else says the answer is ready, so
   * this drives the sidebar's unread dot; cleared by `markSessionRead`. */
  unread?: boolean
  // Agent-assigned topic category (backend ms_agent/titler.CATEGORIES); '' or
  // undefined until the session's first message is classified. Drives the
  // recent-conversations topic icon.
  category?: string
  // The model this session last ran on; reopening it selects that model again.
  model_id?: string
}

export interface ForkOrigin {
  session_id: string
  project_id: string
  title: string
  assistant_seq: number
  available: boolean
}

export interface SessionMessage {
  log_seq?: number | null
  fork_after_seq?: number | null
  fork_origin?: ForkOrigin | null
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
    // Images only: what the model actually received when this turn was
    // answered. Same union as ChatFileRef so history and live turns are one
    // type at every consumer.
    delivery?: 'delivered' | 'degraded' | 'unreadable'
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
  origin: 'managed' | 'legacy-path' | 'standard' | 'external' | 'content'
  removable: boolean
}

export interface MemoryItem {
  id: string
  project_id: string
  content: string
  updated_at: string
}

/** The whole file-backend memory document (`MEMORY.md`). Only meaningful when
 * `memory_backend === 'file'`, where memory IS one markdown file: the UI
 * previews and edits it as a document instead of line-by-line items. */
export interface MemoryDoc {
  project_id: string
  content: string
  updated_at: string
}

/** Which embedding model a vector project's store runs on. */
export interface MemoryEmbedderInfo {
  mode: 'provider' | 'local'
  provider: string | null
  model: string | null
  dimension: number | null
  /** Set when the default resolution had to fall back (e.g. the conversation
   * provider serves no embeddings) — shown verbatim to explain the choice. */
  fallback_reason: string | null
}

/** Why vector memory is unusable right now; `code` picks the remedy the UI
 * offers (a rebuild button for `embedder_mismatch`, an install hint for
 * `local_missing`). */
export interface MemoryErrorInfo {
  code: 'embedder_mismatch' | 'embed_unavailable' | 'local_missing' | string
  message: string
}

/** Last background-ingest outcome of the live runtime. */
export interface MemoryIngestInfo {
  state: 'idle' | 'scheduled' | 'running' | 'ok' | 'error' | string
  at: string | null
  count: number | null
  error: string | null
  pending: number
}

export interface MemoryStatus {
  project_id: string
  backend: 'file' | 'vector'
  embedder: MemoryEmbedderInfo | null
  error: MemoryErrorInfo | null
  ingest: MemoryIngestInfo | null
  local_embed_available: boolean
  /** A re-embedding rebuild is running; embedder/error are withheld until it
   * finishes, since neither the old nor the new one is the truth mid-flight. */
  rebuilding: boolean
}

/** What a rebuild actually did: `migrated` entries were re-embedded with the
 * current model, or `reused` when the store already spoke it and was untouched. */
export interface MemoryRebuildResult {
  project_id: string
  migrated: number
  reused: boolean
  status: MemoryStatus
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
  /**
   * Whether this model may be shown image attachments. Tri-state: `null` means
   * nobody has said, and the SDK decides (provider capability, then learning
   * from a refusal). Not a boolean — collapsing "unset" into `false` would make
   * a vision-capable model silently ignore attachments.
   */
  supports_vision: boolean | null
  created_at: string
}

/**
 * Read-only preview of what the runtime will send for a provider/model before
 * the user overrides anything. Only about thinking on purpose: sampling knobs
 * are ignored by reasoning models, so surfacing them would advertise settings
 * that do nothing.
 */
export interface GenerationDefaults {
  /** Canonical knob value currently in effect (`auto` unless configured). */
  effort: string
  /** Accepted values, weakest to strongest. */
  effort_options: string[]
  /** `effort` after clamping to what this endpoint supports. */
  effective: string
  /** What actually goes on the wire; `{}` means the model's own default. */
  wire_params: Record<string, unknown>
  /** Endpoint dialect: `dashscope`, `deepseek`, `unknown`, ... */
  family: string
  /** Raw keys this endpoint also accepts, shown as an example. */
  extra_hint: string
}

export interface AgentSettings {
  default_provider_id: string | null
  default_model_id: string | null
  default_memory_enabled: boolean
  default_memory_backend: MemoryBackend
  /** Vector-memory model choices. All null = follow the conversation model;
   * explicit values pin extraction / embeddings independently of chat. */
  memory_llm_provider_id: string | null
  memory_llm_model: string | null
  memory_embed_mode: 'provider' | 'local'
  memory_embed_provider_id: string | null
  memory_embed_model: string | null
  memory_recall_top_k: number | null
  global_mcp_auto_attach: boolean
  global_skill_auto_attach: boolean
}

/** A web-search engine the installed SDK accepts. */
export interface SearchProvider {
  id: string
  label: string
  /** arXiv takes no credential, so its key field is hidden entirely. */
  requires_key: boolean
  /** Works with no key, on a reduced free tier (Tavily's keyless mode). Not the
   * inverse of `requires_key`: a key is still accepted and lifts the quota, so
   * the field stays visible — this only means "unconfigured is a working
   * state", which is why no warning is shown for it. */
  supports_keyless?: boolean
}

/** Global web-search config. The key itself is never returned — `has_key` is
 * all the UI needs for its status tag and placeholder. It reflects the stored
 * config only: a key the SDK might pick up from the environment is not counted,
 * since this page can neither show nor clear one. */
export interface SearchSettings {
  enabled: boolean
  provider: string
  has_key: boolean
  /** Whether the SELECTED provider runs without a key. */
  supports_keyless?: boolean
}

export interface SearchSettingsUpdate {
  enabled: boolean
  provider: string
  /** Omit to keep the stored key, '' to clear it, text to replace it. */
  api_key?: string
}
