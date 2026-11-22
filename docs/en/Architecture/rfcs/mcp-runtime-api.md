---
slug: rfc-mcp-runtime-api
title: "RFC: MCP Runtime Outward API and Production Rollout"
description: Complete the Server-facing management API for MCPRuntime, the legacy-interface migration path, and the Phase 3 wrap-up — failure-event persistence, session-level overrides, Plugin-MCP, OAuth.
---

# RFC: MCP Runtime Outward API and Production Rollout

> **Status: Draft (proposal)** · Related current state [ARCHITECTURE Appendix C](../ARCHITECTURE.md#appendix-c-mcp-runtime-state-machine-and-configuration) · ROADMAP theme 2
>
> Current state: `MCPRuntime`'s state machine, failure classification/degradation, public API, and the `MCPConfigManager` config model are **implemented** (Appendix C). This RFC covers the **unshipped** outward API surface, integration with existing APIs, and subsequent work.

## Background and motivation

The current WebUI provides `/api/mcps` configuration CRUD, scoped management, and on-demand connectivity probes through SDK configuration services. A probe opens a temporary connection; it does not represent an active session’s connection state, failure history, or tool synchronization state.

`MCPRuntime` implements these runtime mechanisms, but ordinary entry points still use `MCPClient` by default. This proposal connects existing configuration management to session runtime state. The `/api/mcp/*` paths below are candidates: implementation should first consider extending `/api/mcps` before introducing new routes.

## 1. Outward API surface (proposal)

| Method | Path | Purpose |
|--------|------|------|
| GET | `/api/mcp/servers` | Merged servers + runtime state |
| POST | `/api/mcp/servers` | Create a server (written at project scope) |
| PATCH | `/api/mcp/servers/{name}` | Update config / `enabled` |
| DELETE | `/api/mcp/servers/{name}` | Delete a project-level entry |
| POST | `/api/mcp/servers/{name}/reload` | Hot-reload a single server |
| POST | `/api/mcp/import` | Import a Cursor / Claude `mcp.json` |
| GET | `/api/mcp/status` | Aggregate connection health |

Response shape of `GET /api/mcp/servers` (example):

```json
{
  "servers": [
    {
      "name": "fetch", "enabled": true, "status": "degraded",
      "source": "global", "tool_count": 1, "tools": ["fetch---fetch"],
      "last_error": "...", "last_failure_at": "...", "last_success_at": "...",
      "consecutive_failures": 2,
      "failure_history": [
        {"at": "...", "phase": "call_tool", "tool_name": "fetch", "message": "..."}
      ]
    }
  ]
}
```

The UI shows the last 5 `failure_history` entries + a **Reconnect** action (mapping to the runtime `reconnect_server`).

**Config-change pipeline (proposal)**: `MCPConfigManager` → `ConfigResolver.resolve_mcp()` → `MCPRuntime.apply_config()` → `sync_tools()`. Runtime fields come from `MCPRuntime.list_servers()`.

## 2. Integration with Existing APIs

| Stage | Configuration management | Runtime management |
|------|----------|-----------|
| Current | `/api/mcps`, with scoped configuration and on-demand probes | Ordinary sessions use `MCPClient` by default |
| Integration target | Reuse current services and APIs | Inject `MCPRuntime` into sessions; expose connection state and reconnect |
| Further work | Preserve existing clients while extending response fields as needed | Persistent failure history, hot reload, and session-level overrides |

The `/config/mcp` endpoint from earlier designs is not the current WebUI API or the starting point for this migration.

## 3. Phase 3 wrap-up (unfinished items)

- **Failure-event persistence**: write failure events to `sessions/<id>/mcp_events.jsonl` (aligned with the SessionLog sidecar idea) for replay and diagnosis.
- **Session-level override persistence**: the merge logic already supports a session-level `enabled` override parameter, but it is not yet wired to `session.json` persistence.
- **Plugin-MCP**: registering MCP servers declared in a plugin's `tools/` directory (the assembly side is wired; the full lifecycle rollout is pending).
- **OAuth**: a backend-handled auth-redirect flow.

## Open questions

- The request/response schemas for `/api/mcp/*` POST/PATCH/DELETE/import/status need refining (only the list and the `GET servers` example exist so far).
- How should session-level overrides vs project/global config precedence be presented and explained in the UI?
- What retention policy (rotation/cleanup) should the failure-event jsonl have, and should it share one mechanism with `session_log`?
