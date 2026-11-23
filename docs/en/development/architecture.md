# Architecture overview

MS-Agent organizes models, tools, context, permissions, and persistence around task execution. CLI, TUI, WebUI, and protocol services adapt interaction; execution and management live in the Python SDK.

This page explains responsibilities and trade-offs. Core modules contain configuration and extension details. Design proposals (RFCs) describe future work, not automatically available features.

## Layers and dependencies

```{mermaid}
flowchart TD
 A[CLI / TUI / WebUI / ACP / A2A] --> B[Agents and workflows]
 A --> C[Project, session and configuration services]
 B --> D[Model and tool execution]
 B --> E[Context and memory]
 D --> F[Permissions and hooks]
 D --> G[Providers / MCP / local tools]
 E --> C
```

Interfaces translate requests into SDK calls and events into display/protocol responses. They should not duplicate session storage or the agent loop, so extensions remain reusable across entry points.

## Request to result

1. Load configuration and select workspace, model, and interaction mode.
2. Assemble models, tools, permissions, hooks, plugins, skills, and memory.
3. Load the session and construct the system prompt/model-visible context.
4. Generate a reply or tool call; authorize execution and return results to context.
5. Record messages/artifacts, schedule conditional memory ingestion, and handle further input or completion.
6. Failure and cancellation also require faithful state recording and resource cleanup.

[Agents](../core/agents.md) own model/tool loops, [workflows](../core/workflows.md) define stages, and [subagents](../core/subagents.md) support autonomous delegation. These are not interchangeable orchestration models.

## Separate history, context, and memory

| Layer | Retains | Why |
| --- | --- | --- |
| SessionLog | Original messages, results, compaction events | Traceability and recovery |
| ContextAssembler | Current model-visible window | Budget control without overwriting history |
| MemoryBackend | Reusable cross-task knowledge | Replaceable implementations behind one contract |

Context strategies implement `ViewStrategy` and run in order. The memory orchestrator delegates through `MemoryBackend`. Both are extensible, but not every custom implementation can be loaded through an arbitrary YAML name. See [Context](../core/context.md) and [Memory](../core/memory.md).

Memory ingestion is conditional and asynchronous, not guaranteed to finish before summarization. Some domain applications still use older compressors; migrations must preserve their custom behavior.

## Tools, permissions, and extensions

`ToolManager` is the entry point for managed calls. Inner SafetyGuard checks paths/commands; outer PermissionEnforcer handles modes, rules, remembered authorization, and confirmation. Hooks extend event boundaries.

Permissions are not OS isolation. Direct tool objects, trusted hook scripts, and remote MCP internals have different boundaries. Explicit safety lists replace defaults; empty lists are not additive customization.

[Callbacks](../core/callbacks.md) extend Python lifecycle behavior, [hooks](../core/hooks.md) provide event/script contracts, [plugins](../core/plugins.md) assemble resources, and [skills](../core/skills.md) supply on-demand task knowledge. Keeping these separate makes behavior easier to validate.

## Coexisting paths and contracts

- Four traditional model services retain legacy adapters by default; other registered services use the provider layer, with an explicit routing override. See [Models](../core/models.md).
- `Config.from_task()` loads task configuration; `ConfigResolver` supports layered service configuration. The latter does not replace every former call.
- MCP has direct clients, configuration management, and on-demand probes. A separate MCPRuntime state machine does not mean every session already consumes it. See the [MCP RFC](rfcs/mcp-runtime-api.md).
- WebUI uses shared SDK services and session runtimes with event streaming. Existing `/api/mcps` endpoints differ from RFC proposals.
- ACP connects interactive clients, A2A exchanges remote tasks, and Agent Hub converts assets. They serve different purposes.

## Find the implementation

| Area | Code | Read more |
| --- | --- | --- |
| Execution/orchestration | agent, workflow | [Agents](../core/agents.md), [Workflows](../core/workflows.md) |
| Configuration/state | config, project, session | [Configuration](../core/configuration.md), [Storage](storage.md) |
| Input/output | ui, llm | [Messages and events](../core/messages-events.md) |
| Extensions | tools, skill, hooks, plugins | [Tools](../core/tools.md), [Plugins](../core/plugins.md) |
| Long-running work | memory, cron | [Memory](../core/memory.md), [Scheduling](../core/scheduling.md) |
| Interoperability | acp, a2a, agent_hub, capabilities | [ACP](../core/acp.md), [A2A](../core/a2a.md), [Agent Hub](../core/agent-hub.md) |

Check all consumers when changing events/lifecycles, including completion, failure, and interruption. Adapters should not bypass SDK persistence. Fields live in the [configuration reference](configuration-reference.md); future designs belong in status-labelled RFCs.
