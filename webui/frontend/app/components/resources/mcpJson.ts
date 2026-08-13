import type { Mcp, McpTransport } from '~/lib/types'

/**
 * Standard `mcp.json` shape used by Claude / Cursor / etc. We translate to/from
 * this when the user wants to edit MCP configuration as raw JSON.
 *
 * Dialect tolerance: the transport may arrive as `type` (Claude/Cursor) or
 * `transport` (ms-agent / VS Code); enablement as `disabled` (Claude) or
 * `enabled` (ms-agent). Both are accepted on parse; we emit `type` +
 * `disabled` (the widest-understood spelling). `headers` (remote auth) and
 * `env` (stdio child environment) round-trip verbatim — values like
 * `${DASHSCOPE_API_KEY}` stay as placeholders on disk and are expanded only
 * at connection time by the runtime.
 */
export interface McpServerConfig {
  type?: 'streamable_http' | 'sse' | 'stdio' | 'http'
  transport?: string
  command?: string
  args?: string[]
  url?: string
  env?: Record<string, string>
  headers?: Record<string, string>
  enabled?: boolean
  disabled?: boolean
  description?: string
  autoApprove?: string[]
}

export interface McpServersFile {
  mcpServers: Record<string, McpServerConfig>
}

export function toMcpServers(items: Mcp[]): McpServersFile {
  const result: Record<string, McpServerConfig> = {}
  for (const m of items) {
    const entry: McpServerConfig = { disabled: !m.enabled }
    if (m.description) entry.description = m.description
    if (m.transport === 'stdio') {
      const parts = m.endpoint.split(/\s+/).filter(Boolean)
      entry.command = parts[0] ?? ''
      if (parts.length > 1) entry.args = parts.slice(1)
      if (m.env && Object.keys(m.env).length > 0) entry.env = m.env
    } else {
      entry.type = m.transport === 'sse' ? 'sse' : 'streamable_http'
      entry.url = m.endpoint
      if (m.headers && Object.keys(m.headers).length > 0)
        entry.headers = m.headers
    }
    result[m.name] = entry
  }
  return { mcpServers: result }
}

export interface ParsedMcp {
  name: string
  description: string
  transport: McpTransport
  endpoint: string
  enabled: boolean
  env?: Record<string, string>
  headers?: Record<string, string>
}

function remoteTransport(cfg: McpServerConfig): McpTransport {
  const raw = String(cfg.type ?? cfg.transport ?? '').toLowerCase()
  if (raw === 'sse') return 'sse'
  if (raw === 'streamable_http' || raw === 'http' || raw === '') return 'http'
  return 'http'
}

function isEnabled(cfg: McpServerConfig): boolean {
  // Explicit `enabled` wins; else Claude-style `disabled`; else on.
  if (typeof cfg.enabled === 'boolean') return cfg.enabled
  if (typeof cfg.disabled === 'boolean') return !cfg.disabled
  return true
}

export function fromMcpServers(text: string): ParsedMcp[] {
  const parsed = JSON.parse(text) as McpServersFile
  if (!parsed || typeof parsed !== 'object' || !parsed.mcpServers) {
    throw new Error('Missing top-level "mcpServers" object')
  }
  const out: ParsedMcp[] = []
  for (const [name, cfg] of Object.entries(parsed.mcpServers)) {
    const enabled = isEnabled(cfg)
    if (cfg.url) {
      const item: ParsedMcp = {
        name,
        description: cfg.description ?? '',
        transport: remoteTransport(cfg),
        endpoint: cfg.url,
        enabled
      }
      if (cfg.headers && Object.keys(cfg.headers).length > 0)
        item.headers = cfg.headers
      out.push(item)
    } else {
      const endpoint = [cfg.command ?? '', ...(cfg.args ?? [])]
        .join(' ')
        .trim()
      const item: ParsedMcp = {
        name,
        description: cfg.description ?? '',
        transport: 'stdio',
        endpoint,
        enabled
      }
      if (cfg.env && Object.keys(cfg.env).length > 0) item.env = cfg.env
      out.push(item)
    }
  }
  return out
}
