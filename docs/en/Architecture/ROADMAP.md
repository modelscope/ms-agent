---
slug: roadmap
title: Architecture Roadmap
description: The macro architectural direction of the MS-Agent framework — direction themes, motivation and status, with rfcs/ carrying the concrete proposals.
---

# Architecture Roadmap

This document records the **macro, architectural** directions of the MS-Agent framework: each "direction theme" gives a goal/motivation, a one-line status, and links to related proposals. It is a skeleton for collaborating with contributors and does **not** list fine-grained tasks (those belong to issues / RFCs).

- Current implementation is in [ARCHITECTURE](./ARCHITECTURE.md).
- Proposals are in `rfcs/` ([plugins](./rfcs/plugins.md), [hooks-executors](./rfcs/hooks-executors.md), [mcp-runtime-api](./rfcs/mcp-runtime-api.md)), each with a status banner.

## Maintenance conventions

- **When architecture lands** → write it back into `ARCHITECTURE.md`, and update the corresponding theme's status here to "shipped/partially shipped".
- **New proposals** → file them under `rfcs/` first (with a status banner: Draft / Accepted / In Progress / Done / Superseded), then register them here as a direction theme or under an existing one.
- **This document only adds/removes "directions"**, not task-level progress; one direction may relate to 0..N RFCs.

---

## Direction themes

### 1. Shared Service Contracts Across Interfaces

- **Motivation**: CLI, TUI, and WebUI already reuse SDK execution, permission, and session services. Stable event, error, and session-control contracts would make third-party interfaces and automation easier to integrate.
- **Status**: WebUI adapts the SDK through FastAPI, `SessionRuntime`, and streamed events. Versioned contracts for external services need further work.
- **Related**: MCP runtime and Plugins management proposals should reuse existing services and avoid duplicate storage or execution logic.

### 2. MCP runtime to production

- **Motivation**: `MCPRuntime` already provides a full connect/health/degrade/tool-sync state machine (see ARCHITECTURE Appendix C); it needs to be wired to the real entry point, replacing the legacy direct `MCPClient` path, and complemented with a Server-facing management API and failure-event persistence.
- **Status**: the runtime capability is ready; the outward API surface, session-level override persistence, and failure-event persistence are proposals.
- **Related**: [rfcs/mcp-runtime-api.md](./rfcs/mcp-runtime-api.md).

### 3. Hooks executor extensions

- **Motivation**: only the `command` executor is implemented today; HTTP / Prompt / Agent executors would cover scenarios like "remote policy", "lightweight LLM judgment", and "multi-step validation", and the config fields and decision pipeline already reserve room for them.
- **Status**: `http/prompt/agent` config can be parsed but the backends are not registered; `SubagentStop` is configurable but not triggered.
- **Related**: [rfcs/hooks-executors.md](./rfcs/hooks-executors.md).

### 4. Plugins ecosystem completion

- **Motivation**: the plugin system can already assemble skills/commands/agents/hooks/mcp/bin/settings/userConfig (see ARCHITECTURE §9.4); the next step is to complete "per-plugin incremental hot reload, an online install & management UI, supply-chain security (verification/signing)" into a full ecosystem loop.
- **Status**: assembly and basic runtime operations have landed; incremental hot reload, the management API/UI, and some security hardening are proposals.
- **Related**: [rfcs/plugins.md](./rfcs/plugins.md).

### 5. Memory project isolation and backend matrix

- **Motivation**: memory needs clear isolation across multiple projects/working directories and support for on-demand switching among backends like "file / vector", ensuring portability and cleanability under long-running use.
- **Status**: memory is already isolated per project/working directory and supports file and vector backends; cross-backend consistency and migration tooling can still be polished.

### 6. Converging the legacy LLM Provider layer

- **Motivation**: the Provider layer is already a data-driven facade (`ProviderSpec` + routing + transport); the goal is to gradually converge the legacy direct implementations into the registry, reducing dual-path maintenance and unifying retry/interrupt/thinking-block semantics.
- **Status**: by default, `modelscope/openai/anthropic/dashscope` retain the legacy path and other registered providers use the Provider layer. `use_provider_router` provides an explicit override.

### 7. Permission-validation residual gaps

- **Motivation**: the safety baseline is grounded in the code (see ARCHITECTURE Appendix A); a few config fields and coverage areas still have gaps — small but important hardening.
- **Status (gaps)**:
  - `safety_rules.dangerous_removal_paths` YAML config is not yet fully effective on the validation path (currently relying mostly on built-in defaults).
  - `sensitive_paths` coverage of shell write paths is still incomplete (file-tool coverage is fairly complete).
- **Note**: small in size, tracked as hardening items under this theme rather than a standalone RFC.
