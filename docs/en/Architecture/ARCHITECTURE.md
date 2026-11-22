---
slug: architecture
title: Architecture Overview
description: The MS-Agent framework architecture reference — design principles and philosophy, runtime core, tools and safety, session and memory, configuration system, core module design, and development guide.
---

# MS-Agent Architecture Overview

Complex tasks require agents to keep progressing across model calls, tool execution, and human feedback. This guide follows that execution process to explain how MS-Agent organizes its runtime, manages context and permissions, and shares its SDK across the CLI, TUI, and WebUI.

It is intended for developers customizing agents or integrating the framework, and describes mechanisms implemented in the current source. See the [roadmap](./ROADMAP.md) for future directions and the [Plugins](./rfcs/plugins.md), [Hooks executors](./rfcs/hooks-executors.md), and [MCP runtime API](./rfcs/mcp-runtime-api.md) proposals for designs not yet implemented. Chinese and English pages are maintained together.

---

## Contents

1. [What MS-Agent Is](#1-what-ms-agent-is)
2. [Design Principles and Philosophy](#2-design-principles-and-philosophy)
3. [Overall Layered Architecture](#3-overall-layered-architecture)
4. [Runtime Core: the LLMAgent Lifecycle](#4-runtime-core-the-llmagent-lifecycle)
5. [Tool Calls and Safety: Dual-layer Permissions + Hooks](#5-tool-calls-and-safety-dual-layer-permissions--hooks)
6. [System Prompt Assembly](#6-system-prompt-assembly)
7. [Session and Context: SessionLog / ContextAssembler / Memory](#7-session-and-context-sessionlog--contextassembler--memory)
8. [Configuration System](#8-configuration-system)
9. [Core Module Design](#9-core-module-design)
10. [On-disk Storage Layout](#10-on-disk-storage-layout)
11. [Extension and Development Guide](#11-extension-and-development-guide)
12. [Glossary](#12-glossary)
- [Appendix A: Permission and Shell Safety Validation Reference](#appendix-a-permission-and-shell-safety-validation-reference)
- [Appendix B: Hooks Protocol and Events Reference](#appendix-b-hooks-protocol-and-events-reference)
- [Appendix C: MCP Runtime State Machine and Configuration](#appendix-c-mcp-runtime-state-machine-and-configuration)
- [Appendix D: Configuration Field Reference](#appendix-d-configuration-field-reference)

---

## 1. What MS-Agent Is

MS-Agent is a framework for agents that perform complex tasks. Compose models, tools, skills, and sub-agents; organize work through autonomous delegation or explicit workflows; and add context management, permission decisions, and feedback checks. Together, these mechanisms form a customizable **Agent Harness** around the model.

The architecture addresses three engineering questions:

- **How is complex work organized?** `LLMAgent` manages model and tool interaction, sub-agents handle specialist tasks, and `ChainWorkflow` / `DagWorkflow` express explicit stages and dependencies.
- **How does task state persist?** Session logs preserve execution records, the context assembler compacts model input when needed, and memory backends retain information for later tasks. Cron schedules recurring and one-time jobs.
- **How do applications integrate?** CLI, TUI, and WebUI reuse SDK execution, configuration, project, and session services, with input and event interfaces adapting interaction. MCP, ACP, A2A, and Agent Hub connect external tools, services, and resources across frameworks.

Research, coding, financial analysis, and video applications combine these mechanisms. Skill Evolution uses execution feedback and validation to improve skills on evaluable tasks. Application features and results depend on each project's configuration and evaluation.

---

## 2. Design Principles and Philosophy

| Principle | Problem addressed | Implementation |
| --- | --- | --- |
| **Shared SDK across interfaces** | Avoid rebuilding execution and data management for each interface | `ms_agent/ui/`, `project/`, `config/`, `PermissionHandler` |
| **Composable orchestration** | Support autonomous delegation and explicit business processes | `LLMAgent`, `AgentTool`, `ChainWorkflow`, `DagWorkflow` |
| **Layered permissions** | Separate operation rules, user authorization, and business extensions | `SafetyGuard`, `PermissionEnforcer`, `HookRuntime` |
| **Separate history from model context** | Limit model input while retaining the original session record | `SessionLog`, `ContextAssembler` |
| **Explicit extension points** | Integrate custom tools, callbacks, skills, and plugins through interfaces | `ToolBase`, `callbacks/`, `skill/`, `plugins/` |
| **Incremental migration** | Allow old and new configuration and execution paths to coexist | `Config.from_task()` / `ConfigResolver`, legacy LLM / Provider routing |
| **Open integration** | Reuse external tools, skills, and agent resources | MCP, ACP / A2A, plugin loaders, Agent Hub |

Permission coverage depends on tool adapters and configuration; it does not replace operating-system or container isolation. Plugin compatibility covers supported resource types and loading rules, rather than arbitrary execution of another host's plugin code.

---

## 3. Overall Layered Architecture

```{mermaid}
flowchart TB
    entry["Interfaces and services<br/>CLI · TUI · WebUI · ACP / A2A"]
    workflow["Task orchestration<br/>ChainWorkflow · DagWorkflow · Sub-agents"]
    agent["Agent runtime<br/>Model calls · Tool execution · Lifecycle callbacks"]
    context["Context and state<br/>SessionLog · ContextAssembler · Memory"]
    tools["Tool pipeline<br/>Permissions · Hooks · ToolManager"]
    services["Shared SDK services<br/>Projects · Sessions · Config · Skills · Plugins"]
    ecosystem["External capabilities<br/>Model providers · MCP tools · Remote agents"]
    entry --> agent
    entry --> workflow --> agent
    entry --> services
    agent --> context
    agent --> tools --> ecosystem
    agent --> services
```

Interfaces translate requests into SDK calls and events into terminal output or WebUI streams. `LLMAgent.run_loop()` manages a single agent's execution; workflows and sub-agents provide higher-level task orchestration. Shared services own projects, sessions, and configuration, so interfaces do not need a second storage implementation.

---

## 4. Runtime Core: the LLMAgent Lifecycle

`LLMAgent.run_loop()` manages the execution lifecycle of a single agent. It first runs a series of `prepare_*` assembly steps, then enters the "generate → tool call → persist" main loop until the task completes or the round cap is reached.

```
run_loop(messages)
├─ Assembly phase
│   ├─ resolve interactive mode / register callbacks
│   ├─ prepare_llm()        # LLM.from_config() (provider routing, see §9.6)
│   ├─ prepare_runtime()
│   ├─ prepare_tools()      # permission objects + Plugin assembly + Hook runtime + ToolManager
│   ├─ prepare_skills()     # SkillCatalog / Injector / ToolSet; inject the system-content builder
│   ├─ load_memory()        # memory backend; register MemoryTool when unified_memory is on
│   ├─ prepare_rag() / prepare_knowledge_search()
│   └─ _init_session_log()  # SessionLog + ContextAssembler
│
├─ Input resolution   # when messages is empty: interactive read / config.prompt.query / piped stdin
├─ History restore    # load from SessionLog or the history cache
│
├─ If a new task (round == 0)
│   ├─ create_messages() → messages[0] = _build_system_content()   # §6
│   ├─ on_task_begin() → SessionStart hook
│   ├─ UserPromptSubmit hook (can block)
│   ├─ do_rag()
│   └─ SessionLog writes the initial messages
│
└─ while not stopped:
    ├─ context_assembler.assemble()               # non-destructive context rebuild (§7)
    ├─ maybe_refresh_system_prompt()              # refresh prompt layers (§6)
    ├─ condense_memory()                          # inject long-term memory (§7)
    ├─ try: step()                                # generation + tool calls (§5)
    │     └─ except Cancelled/GeneratorExit: seal the interrupted round → re-raise (§7)
    ├─ SessionLog writes this round's output (assistant + tool)
    ├─ add_memory() on a completed assistant turn
    ├─ after_tool_call() → Stop hook + interactive follow-up input
    ├─ attach prompt/model notices and memory recall to new input
    ├─ round += 1; persist appended input; save_history
    └─ reaching the round limit (including a concluding round) → stop
        on_task_end() → cleanup_tools()
```

Design points:

- **Integration points, not hard-coding**: permission, Hooks, Plugins, Skills, and Memory are all assembled at fixed `prepare_*` steps and invoked at fixed positions. Extensions should reuse these integration points and account for lifecycle and resource cleanup.
- **Persistence follows output closely**: this round's assistant/tool messages are flushed before `after_tool_call` (which may block waiting for the next input), avoiding a save that depends on the next user input.
- **Interrupt-recoverable**: `step()` is wrapped to catch cancellation and faithfully seal the interrupted round as a replayable log (see §7).

---

## 5. Tool Calls and Safety: Dual-layer Permissions + Hooks

Tool calls dispatched by `ToolManager` go through `ToolManager.single_call_tool()`; `parallel_call_tool()` invokes it concurrently over a batch of tool_calls. The decision pipeline (in real order):

```
single_call_tool(tool_call)
├─ parse args; verify tool_name is in the index
├─ MCP availability check (server unavailable → return mcp_unavailable directly)
├─ [inner] SafetyGuard.check()                # tool rule validation (Appendix A)
│     ├─ deny → block
│     └─ ask  → disambiguate by mode (auto/strict/interactive)
├─ [Hook] PreToolUse                          # can rewrite args / decision (Appendix B)
├─ permission decision fusion                 # merge the hook decision with the outer PermissionEnforcer
│     └─ PermissionEnforcer.check():
│          blacklist→deny · forced asks/ask_rules · mode/whitelist · memory · handler.ask()
├─ call_tool()                                # actual execution (with timeout)
└─ [Hook] PostToolUse                         # attach extra context onto the return value
```

**Dual-layer permissions** is the core design:

- **Inner `SafetyGuard` (rule validation)**: checks shell commands and file-tool paths, rejecting calls that match deny rules. Direct tool invocation, operations inside an external MCP service, and trusted Hook scripts are outside this pipeline’s coverage. Details in [Appendix A](#appendix-a-permission-and-shell-safety-validation-reference).
- **Outer `PermissionEnforcer` (user intent)**: expresses "what this user / this session is allowed to do", via blacklist / ask_rules / whitelist / memory (always-allow) / interactive confirmation (`PermissionHandler`).

**Permission modes** (`PermissionConfig.mode`, default `auto`; `restricted` normalizes to `interactive`):

| Mode | SafetyGuard `ask` | Enforcer | Use case |
|------|---------------------|----------|---------|
| `auto` | disambiguate by category (allow safe, deny dangerous) | deny blacklist; ask_rules still require confirmation; allow the rest | automatic execution |
| `strict` | deny everything | deny blacklist; ask_rules still require confirmation; allow the rest | conservative handling of uncertain operations |
| `interactive` | keep asking, hand off to the handler | full chain (blacklist→ask rules→whitelist/memory→confirmation) | attended CLI / Web |

**Permission interaction across interfaces**: the core picks a handler by "mode + whether it's an interactive terminal" — an interactive terminal picks `CLIPermissionHandler` (prompts `[y/s/a/e/n]`), otherwise `AutoPermissionHandler`. An external UI can inject a custom implementation via `set_permission_handler()` (TUI uses `TUIPermissionHandler`; Web can inject an SSE/callback-based handler). During concurrent tool calls, interactive asks are serialized by a lock created lazily per event loop, so multiple confirmations do not contend for the same terminal.

**Hooks** provide ecosystem extension points on the same pipeline (`PreToolUse` / `PostToolUse`, etc.), able to rewrite args, attach context, or block execution; protocol and events in [Appendix B](#appendix-b-hooks-protocol-and-events-reference).

---

## 6. System Prompt Assembly

`_build_system_content()` assembles independent layers for general behavior, project instructions, and runtime capabilities:

1. **Base prompt:** an explicit `prompt.system` replaces only the built-in base layer.
2. **Personalization and project instructions:** when `personalization.enabled` is set, read global `SOUL.md`, `AGENTS.md`, `PROFILE.md`, and project instruction files.
3. **Workspace guidance:** describe framework directories and session records so agents can distinguish them from user files.
4. **Memory guidance:** include it after unified memory tools are registered.
5. **Skill summaries:** build them through the skill injector and `SkillRuntime` according to configuration.

`prompting/workspace_files.py` handles reading, template initialization, and caching. Markdown frontmatter and HTML comments are excluded; empty templates do not override useful legacy instruction fields. Personalization defaults to `false` when unspecified, while the bundled general-purpose `agent.yaml` explicitly enables it. Specialized projects follow their own configuration.

Prompt content can refresh each round. `skills.update_notice=true` pins the **skill summary section**, conveying skill changes through conversation notices. Other layers may still change, so this does not guarantee a byte-stable system prompt or a provider cache hit. Prompt-file changes and model switches retain the session state needed to detect changes after resuming.

---

## 7. Session and Context: SessionLog / ContextAssembler / Memory

This layer separates "historical truth", "context view", and "long-term memory" — the foundation of the framework's ability to run long.

- **SessionLog** (`session/session_log.py`): append-only JSONL with a `seq` sequence number and a `round` sidecar, the single source of truth for history. Besides messages it records several **sidecar records** (all excluded from the LLM context, kept only for replay/statistics):
  - `metadata` (title/status/counters), `compaction_event` (compaction events), `error` (tool/round errors), `permission` (permission decisions), `skill_invocation` (the user's raw input before `/skill` expansion, so replay shows the original text rather than the long expanded prompt).
  - **Faithful sealing of interrupted rounds**: when a round is cancelled, the normal round-boundary persistence does not run, so cancellation is caught around `step()` and the interrupted round is repaired into a record that "both ends of the protocol can replay" — preserving parseable `tool_calls` and filling them with `is_error` interrupt results, downgrading unsigned thinking content to display-only, and padding empty segments with placeholders; every line is marked `interrupted` (visible on replay, filtered when rebuilding context).

- **ContextAssembler** (`session/context_assembler.py`): rebuilds the model-facing context from SessionLog on later rounds. The default strategy pipeline is `[ToolOutputPruner, SummaryCompactor]`. Compaction changes the view while retaining the raw log. A configured memory backend with `flush()` can receive discarded messages asynchronously; this does not guarantee a durable memory write before summarization.

- **Memory** (`memory/`): `SharedMemoryManager` instantiates a memory backend per config; when unified memory is on, it registers `MemoryTool` into the ToolManager and injects a usage hint. Each turn `condense_memory()` injects long-term memory into the messages.

**Two session-driving modes** (an important architectural split):

- **A. Agent-driven**: one `run_loop` runs to completion; the Agent owns the SessionLog + ContextAssembler auto-compaction + a once-per-session lifecycle hook. CLI interactive mode takes this path.
- **B. Outer-owned session**: the outer layer calls the Agent each turn and persists the session itself (this is how the TUI works: treating the working directory as a project, persisting via `SessionManager`, supporting `/sessions`, `/resume`, `/new`). In this mode, auto-compaction must be supplemented by the outer layer via means like `/compact`.

To keep "auto-compaction + a single lifecycle" while the outer layer owns the session, use mode A + the **async input interface** (`input_source` can await a queue instead of blocking on stdin, paired with `event_sink` for output events) — WebUI uses this mode in `SessionRuntime`, receiving subsequent input through `WebInputSource` and mapping SDK events to streamed responses.

---

## 8. Configuration System

The framework has three configuration sources with different responsibilities — do not conflate them:

1. **The agent.yaml family (agent definition)**: read by `Config.from_task(dir_or_id)`; `agent/agent.yaml` is the framework default. Fields cover `llm / generation_config / prompt / tools / skills / memory / permission / hooks / session_log / compaction / max_chat_round / output_dir`, etc.
2. **Global settings `~/.ms_agent/settings.json` (global preferences)**: mapped to the agent config by `ConfigResolver._settings_to_agent_config()` (e.g. `llm.provider → llm.service`, personalization, `output_dir`, the `tools` block — see [Appendix D](#appendix-d-configuration-field-reference)).
3. **Project patch `<work_dir>/.ms_agent/config.yaml`**: interactive overrides (e.g. `/model`) are written here, taking precedence over the committed YAML without modifying the source file.

**Key mental model: the project patch is anchored to the "working directory", not the directory the config file lives in.**

- Write: overrides like `/model` are written to `output_dir/.ms_agent/config.yaml`.
- Read/merge: `Agent.__init__` (`agent/base.py`) resolves `output_dir` and then merges via `ConfigResolver._load_project_patch(output_dir)` (covering both run and tui).
- `Config.from_task` no longer merges the patch from the config file's directory — otherwise running a shared/template config would leak that directory's patch into every run and scatter `.ms_agent/` into the template directory.
- In one sentence: **the config file is a "definition/template" (can be read-only/shared); mutable project state (including `/model` overrides, memory, snapshots, sessions) belongs to the working directory.**

The full five-layer merge (framework default → global settings → user agent.yaml → project patch → runtime dict) is handled by `ConfigResolver.resolve()`, used mainly in external Server/UI assembly scenarios; the CLI main path only does a lightweight merge.

---

## 9. Core Module Design

### 9.1 Project / Session / Workspace (`project/`)

Modeled on the Claude Code / Codex "project–session" mental model, decoupling session storage from the working directory:

| Class | Responsibility |
|----|------|
| `Project` (frozen) | The project entity: `id / name / path / instruction / memory_enabled / memory_backend / timestamps`. `id` depends on how it was created: `create` → a random 12-char hex, `open_folder` → a path-derived `project_key`, default → `_default` |
| `ProjectManager` | Project CRUD; two creation paths — `create` (random id + optional workspace init, "start from scratch") and `open_folder` (dedup by path, "use an existing folder") |
| `Session` / `SessionManager` | Session-metadata CRUD; messages delegated to `SessionLog` |
| `Workspace` | Workspace file operations (`list_dir/read_file/write_file/delete/import_path`), with `_resolve_safe()` guarding against path traversal |
| `JSONFileStore` | Atomic-write (tmp + rename) JSON storage |

Inside the framework, the TUI persists sessions itself via `SessionManager` (session-driving mode B, see §7); `ProjectManager` / `Workspace` are the SDK surface reserved for an external Server/UI.

### 9.2 Command System (`command/`)

A unified slash-command and interaction driver:

- `CommandRouter` cascades four levels: `priority` (lock-free priority, e.g. `/stop`) → `exact` → `prefix` → `interceptor` (Skill / Plugin bridging).
- 12 built-in commands: `/stop`, `/new`, `/status`, `/quit`, `/help`, `/version`, `/usage`, `/tools`, `/context`, `/model`, `/config`, `/compact` (each with aliases).
- `CommandResult.type ∈ {MESSAGE, SUBMIT_PROMPT, MUTATE_STATE, QUIT}` standardizes "what the command did".
- `InteractiveSession` owns the `>>>` read and command loop; the initial prompt and multi-turn input share the same router instance.
- `SkillCommandBridge` (interceptor) expands `/<skill-id>` into a skill prompt; the expansion is factored into the shared functions `expand_skill()` / `expand_slash_text()` for reuse by non-interactive surfaces (other interfaces).

### 9.3 Skills (`skill/`, `config/skills_manager.py`)

Skills are exposed as standard tools (`skills_list` / `skill_view` / `skill_manage`) and can be injected into the system prompt. The core design is **live-tree discovery**:

- Each scope implicitly provides one "live directory" source — `<global_home>/skills` and `<project>/.ms_agent/skills`. Drop a skill directory in and it is registered, without editing `skills.json` (mental model: "**existence = filesystem, state = the disabled list**").
- Relative sources in `skills.json` are anchored to the scope root (not the process cwd); the loader scans recursively (treating a directory with `SKILL.md` as a leaf and not descending further, skipping hidden directories); deduped by identity.
- **In-session hot sync**: `SkillCatalog.resync()` rebuilds the catalog in place (long-lived holders stay valid); `SkillRuntime.sync_with_config()` bumps the version only when the skill surface (manifest/metadata/disabled set) actually changes, driving the system prompt to refresh on demand.
- `SkillToolSet` creation/deletion is anchored to the managed live tree, and the deletion guard is the tree boundary (external / config-declared source directories are read-only).

### 9.4 Plugins (`plugins/`)

A plugin system compatible with the Claude Code `plugin.json` format; a single plugin can provide multiple kinds of sub-resources:

- `PluginRuntime.start_sync()` starts during the `prepare_tools` phase: parse manifests → assemble via `PluginLoader.load_all()` → apply to config.
- Component distribution: `skills/` → skill sources; MCP servers → `config.tools` + merged index (name collisions get a `plugin.<id>.` prefix for dedup); `hooks/hooks.json` → hook registry; `commands/` → commands; `agents/` → sub-agent registry; `bin/` → executable paths; `settings` → config patch (whitelisted); `userConfig` → plugin data directory.
- Config layering precedence: `config._merged_plugins` (resolver output) > `PluginConfigManager.load_merged()` (`~/.ms_agent/plugins.json` + project-level) > legacy `config.plugins` path list.
- Runtime operations: `toggle / reload / install / uninstall / get_user_config / set_user_config`. Install sources cover local / tarball / `github://` / `modelscope://` / marketplace aliases.
- Manifest detection is compatible with multiple ecosystem formats (`.ms-agent-plugin/`, `.claude-plugin/`, `.codex-plugin/`, etc.), with the MS-Agent native format winning on conflict.

Unshipped incremental capabilities (per-plugin incremental hot reload, an online install UI, some security hardening) are in [rfcs/plugins.md](./rfcs/plugins.md).

Plugin Hook handlers carry source identities and directories through `HookRegistry.with_plugin_source()`. The executor builds the corresponding context, and the factory prefers registries supplied by the plugin runtime over legacy directory discovery.

### 9.5 MCP Runtime (`mcp/runtime.py`, `config/mcp_manager.py`)

`MCPRuntime` is a config-driven MCP lifecycle state machine that manages server connection, health, degradation, and tool-index sync. The CLI defaults to the legacy `MCPClient` path; `MCPRuntime` is the more complete runtime capability, enabled once injected by an external Server/UI. The state machine, failure classification, and config model are in [Appendix C](#appendix-c-mcp-runtime-state-machine-and-configuration); the Server-facing API surface is in [rfcs/mcp-runtime-api.md](./rfcs/mcp-runtime-api.md).

### 9.6 LLM Provider Layer (`llm/`)

Data-driven multi-provider access:

- `ProviderSpec` + `ProviderRegistry`: describe each provider declaratively (service name, aliases, default transport, credential resolution, model-keyword routing).
- `CredentialResolver` (config → env → default), `ResponseAdapter` (`Message ⇄ LLMResponse`), `retry` (error classification + exponential backoff), `transport/` (`openai_compat` / `anthropic_messages`).
- `LLM.from_config()` retains two paths. With `use_provider_router` unset, `modelscope/openai/anthropic/dashscope` use the legacy implementation, while other registered providers route automatically through the Provider layer. `true` forces Provider routing; `false` forces the legacy path.
- Supports mid-stream interruption (`interrupt()`): when a consumer abandons a round, it can close the upstream response stream; whether remote generation stops immediately depends on the provider.
- Transport can be overridden per provider (e.g. having one provider hit another vendor's compatible endpoint), while also handling "thinking + tools" (replaying signed thinking blocks under the Anthropic protocol).

Adding a provider essentially only requires one more `ProviderSpec` in `spec.py` (plus a transport if needed), see §11.

### 9.7 Personalization (`personalization/`)

- `PersonalizationInjector.build()` (a stateless pure function) produces the "Custom Instructions / Project Instructions / User Profile" blocks injected into the system prompt (see §6).
- `prompting/workspace_files.py` manages the current `SOUL.md` / `AGENTS.md` / `PROFILE.md` files. Legacy `profile.md` and configuration fields retain compatibility reading or migration paths. `PersonalizationSettings` manages related settings.json fields.

### 9.8 Memory (`memory/`)

See §7. Key points: `SharedMemoryManager` instantiates the backend per config; unified memory registers `MemoryTool` as a tool; both file and vector backends are supported; memory is isolated per project/working directory.

### 9.9 Protocol Services (`acp/`, `a2a/`)

MS-Agent serves both as a **protocol server** (exposing itself) and as a **client** (calling remote agents):

- **ACP (Agent Client Protocol)**: `MSAgentACPServer` exposes ms-agent over stdio or HTTP/SSE; `MSAgentACPProxy` acts as a multi-backend proxy; `generate_agent_manifest` produces the discovery manifest. CLI: `ms-agent acp` / `acp-proxy` / `acp-registry`.
- **A2A (Agent-to-Agent)**: `MSAgentA2AExecutor` bridges A2A requests to the ms-agent runtime (server side); `A2AClientManager` calls remote A2A agents over HTTP (client side); `build_agent_card` produces the discovery document (Agent Card). CLI: `ms-agent a2a` / `a2a-registry`. SDK imports are lazy, so the package degrades gracefully when `a2a-sdk` is not installed.

Both are also exposed as tools (`acp_agent_tool` / `a2a_agent_tool`) so the LLMAgent can call remote agents within a session.

### 9.10 Agent Hub (`agent_hub/`)

Cross-framework **agent workspace management**: define, merge, convert, and sync the same set of agent assets (instructions, skills, memory, etc.) across different host frameworks.

- `WorkspaceSpec` + `FRAMEWORK_REGISTRY`: describe each framework's workspace layout declaratively; built-in support for qoder / qwenpaw / openclaw / hermes / nanobot / openhuman / ms-agent, with `register_framework()` for runtime extension.
- `convert_workspace()` / `merge_resources()`: convert between frameworks and merge resources section by section; paired with local/remote sync, a watch daemon, and backup/restore.
- The low-level remote transport reuses `modelscope_hub.agent.AgentApi`. CLI: `ms-agent agent` (list / upload / download / convert / status / watch / restore …).

### 9.11 Scheduled Tasks (`cron/`)

`CronService` provides process-level scheduling: trigger agent tasks on a fixed cadence or from declarative `jobs.d/*.yaml`, managing execution history and output. It is both a built-in tool (`cron`) and a standalone CLI (`ms-agent cron start/stop/list/create/…`), supporting cron expressions, fixed intervals, and one-time schedules. The scheduler process must remain running. The `cron` tool cannot manage jobs from within a scheduled job.

---

## 10. On-disk Storage Layout

Storage paths are defined in `ms_agent/project/paths.py`. It splits into three parts: the **global home**, the **working/project directory**, and **session global storage**:

```
# ── Global home (~/.ms_agent, or $MS_AGENT_HOME) ─────────────────────────────
~/.ms_agent/
├── settings.json            # global settings (llm / personalization …)         ← ConfigResolver
├── SOUL.md / AGENTS.md / PROFILE.md  # persona and global instructions (prompting/)
├── mcp.json / skills.json   # global MCP / Skills
├── skills/                  # global skill live tree (drop a dir to register)    ← SkillCatalog
├── plugins.json + plugins/  # installed-plugin records + install artifacts / data
└── projects/                # [session global storage, decoupled from work dir]
    ├── <work-dir-key>/                 # key = escaped absolute path of the working dir (zero-config CLI/TUI)
    │   └── session_<id>.jsonl(+.meta)  # runtime SessionLog
    └── <project.id>/                   # explicit project (ProjectManager)
        └── sessions/<sid>/{session.json, session_<sid>.jsonl}

# ── Working / project directory (== output_dir) ──────────────────────────────
<work_dir>/
├── <any work artifacts>     # artifacts may land anywhere in the working directory
└── .ms_agent/               # all framework internals collected here
    ├── memory/              # history cache + memory backend
    ├── snapshots/           # snapshot git repo
    ├── index/ · locks/      # file/code index, locks
    ├── artifacts/ · subagents/ · tmp/ · search_index/ · web_search/
    ├── AGENTS.md            # private project instructions; the workdir may also have AGENTS.md
    ├── settings.local.json  # project-level config (settings schema)
    ├── config.yaml          # project-level agent-schema override (/model writes here)
    ├── mcp.json / skills.json  # project-level MCP / Skills
    └── skills/              # project skill live tree
# Logs: console-only by default; MS_AGENT_LOG_FILE on → ~/.ms_agent/logs/
```

**Compatibility**: legacy directories (`<work>/.memory`, `<work>/.ms_agent_snapshots`, `<work>/sessions`, and the hyphenated `<project>/.ms-agent/*`) keep read compatibility + forward migration; `MS_AGENT_HOME` can redirect the global home (used for test isolation).

---

## 11. Extension and Development Guide

| What you want to do | How |
|---------|--------|
| Add a built-in command | Add a `CommandDef` + async handler under `command/builtin/`, and register it in `register_builtin_commands()` |
| Add a Hook event point | Add `run_*` to `HookRuntime`, call it at the semantically equivalent position in `LLMAgent`/`ToolManager`, and register it in `HookRegistry.VALID_EVENTS` |
| Add an LLM provider | Add one declarative `ProviderSpec` in `llm/spec.py`; add a transport if needed |
| Add a built-in tool | Implement `ToolBase` and declare it in the config `tools` block; use `ToolManager.index_extra_tool()` to index precisely (do not re-list MCP) |
| Add a settings.json mapping field | Add a mapping in `ConfigResolver._settings_to_agent_config()` plus a matching test |
| Add a field to Project/Session | Add a field with a default value to the dataclass in `project/types.py`; old JSON deserializes via the default |
| Wire in custom interactive permissions | Inject an implementation via `agent.set_permission_handler(...)` and build your own resolve channel |
| Let an external Server drive the core long | Use the async input/event interfaces (`input_source` / `event_sink`) with the Agent-driven model (§7) |

Regression checks (module unit tests):

```bash
pytest tests/project tests/command tests/config tests/personalization \
       tests/skill tests/permission tests/hooks tests/plugins tests/mcp tests/llm -v
```

---

## 12. Glossary

| Term | Meaning |
|------|------|
| Dual-layer permissions | Inner `SafetyGuard` (tool rule validation) + outer `PermissionEnforcer` (user intent) |
| Canonical event | The normalized Hooks event type (aligned with Claude Code / Codex / Cursor) |
| `TOOL_SPLITER='---'` | Tool-name separator: `server---tool`; the unified format for permission / Hook matchers |
| Provider routing | `LLM.from_config` deciding, per the registry, whether to take the provider layer or the legacy implementation |
| live-tree | An implicit skill source directory, "existence = registration", with state managed by the disabled list |
| Session-driving modes A/B | Agent-driven (owns its own session) / outer-owned session |
| Non-destructive context | The context view is rebuilt per turn from the SessionLog; the raw log always stays complete |

---

## Appendix A: Permission and Shell Safety Validation Reference

The inner `SafetyGuard` is the tool rule validation, implemented by `permission/{safety,shell_validator,path_validator,path_extractors,wrapper_strip,ask_resolver}.py`.

### A.1 SafetyConfig (safety baseline config)

| Field | Default | Meaning |
|------|------|------|
| `patterns` | `rm -rf /*` / `mkfs *` / `dd if=*` | Dangerous command patterns denied outright |
| `sensitive_paths` | `/etc/*`, `/sys/*`, `~/.ssh/*`, `**/.git/**`, etc. | Sensitive paths |
| `dangerous_removal_paths` | `*`, `/*`, `/`, `~` | Dangerous removal targets |
| `read_policy` | `loose` | Leniency policy when a read goes out of range (`loose` / `strict`) |
| `max_command_chars` | `8192` | Max length of a single command |
| `allowed_directories` / `read_only_directories` | empty | Writable / read-only directory allowlists (support `${PROJECT_ROOT}` expansion) |

The **default blacklist is empty**. Network commands such as `curl / wget / ssh / scp / rsync / nc / netcat` match default `ask_rules`, requiring confirmation in every mode. They are denied without an interactive handler; matching remembered approvals can be reused. `allow_network: true` (or the legacy `no_default_blacklist`) removes these default ask rules while retaining user-defined blacklist and ask rules. These are shell-tool matching rules, not network isolation for arbitrary programs.

### A.2 Shell path-level validation: five extraction strategies + a 36-command registry

`build_extractor_registry()` registers, for each supported shell command, a "path extractor + operation type (read/write/create) + optional command validator". Extracted paths are then range-checked by `validate_path`. Five strategies:

| Strategy | Commands | Extraction |
|------|------|---------|
| A `filter_out_flags` (27) | `cat head tail sort uniq wc cut paste column file stat diff awk strings hexdump od base64 nl sha256sum sha1sum md5sum` (read), `mkdir touch` (create), `rm rmdir mv cp` (write) | Keep non-flag args, respecting the `--` separator |
| B `parse_pattern_command` | `grep rg` | The first non-flag is the search pattern (skipped), the rest are paths; when `-e/-f` gives the pattern explicitly, all are treated as paths |
| C special skip | `sed` (write), `jq` (read) | Skip the script/expression arg, the rest are paths |
| D search-root collection | `find` | Collect search roots and path-type flag values; also recursively validate the `-exec` sub-command and block writes like `-delete`/`-fprintf` |
| E sub-command dispatch | `git` | Extract paths only for `git diff --no-index` |
| special | `cd ls tr` | Custom per command |

**Command validators** (extra blocking beyond path checks): `mv`/`cp` with flags are denied (to prevent a `--target-directory` bypass); `find`'s `-fprintf`/`-fprint`/`-fls` and similar writes require confirmation.

### A.3 Defense in depth

- **safe-wrapper stripping** (`wrapper_strip.py`): strip wrappers like `sudo`, `env`, `nice`, `timeout` and then validate the real command.
- **compound commands / redirection / process substitution**: split on `;`, `&&`, `||`, and pipes; parse output redirection (`>`/`>>`); recursively handle process substitution `$(...)`, command substitution, and variable expansion.
- **file tools**: `write_file / edit_file / read_file / grep / glob` call `validate_path` directly.

### A.4 Permission YAML example

```yaml
permission:
  mode: interactive            # auto | strict | interactive(=restricted)
  allow_network: false
  whitelist: []
  blacklist: []                # user-defined deny rules; empty by default
  ask_rules: []                # added to default network-command ask rules
  safety_rules:
    # Omit safety pattern/path lists to retain defaults; explicit lists replace them.
    allowed_directories: ["${PROJECT_ROOT}"]
    read_only_directories: []
    path_validation:
      read_policy: loose       # loose | strict
      max_command_chars: 8192
```

---

## Appendix B: Hooks Protocol and Events Reference

Hooks are ecosystem extension points that hook external scripts/policies into key moments of the Agent and its tools. Implementation in `hooks/`.

### B.1 Canonical events

| Event | Trigger point | Can block |
|------|--------|--------|
| `SessionStart` | A new task begins (via `CallbackToHookBridge.on_task_begin`) | No |
| `UserPromptSubmit` | On the first and each subsequent user-input submission | Yes |
| `PreToolUse` | Before tool execution (after SafetyGuard, before the permission decision) | Yes |
| `PermissionRequest` | In interactive mode when a matching handler exists | Yes |
| `PostToolUse` | After the tool executes successfully | No |
| `Stop` | Before deciding to stop (can prevent stopping) | Yes |
| `SubagentStop` | Can be configured/loaded, but currently not triggered | — |

Tool events (with a matcher): `PreToolUse` / `PostToolUse` / `PermissionRequest`.

### B.2 Command-executor subprocess protocol (`command` executor)

- **Input (stdin)**: the event is serialized to JSON and written to stdin. Common keys: `event`, `session_id`, `project_path`, `cwd`, `hook_event_name`; tool events also carry `tool_name` / `tool_args` (`tool_input`), `PostToolUse` has `tool_result`, `UserPromptSubmit` has `prompt`, `Stop` has `reason` / `last_assistant_message`, etc. Env vars are an allowlist + `MS_AGENT_PROJECT_DIR` / `CLAUDE_PROJECT_DIR`, etc.
- **Output (stdout)**: JSON, recognizing `decision` / `permission` / `action` / `reason` / `additionalContext` / `updatedArgs` (and nested forms like `hookSpecificOutput.permissionDecision`).
- **Exit-code semantics**: `0` → parse stdout; `2` → deny directly (reason from stderr, stdout not parsed); other non-zero → `error` (escalated to `deny` when `fail_closed`); timeouts/exceptions likewise.

### B.3 Decision mapping (ResponseAdapter)

By priority: `hookSpecificOutput.permissionDecision` (deny/allow/ask) → `decision`/`permission` (deny·block·reject / allow·approve·permit / ask) → top-level `action` (block/deny) → `updatedArgs` only (allow + modify args) → `additionalContext` only (allow + attach context) → Stop-specific (`continue:false` / `followup_message`) → otherwise `pass`. Additional context is attached via `Message.hook_attachments` and re-fed as a user meta-message the next round.

### B.4 Matcher and configuration

- **Matcher**: fnmatch globbing (`*`, `?`), supporting `|`-separated alternatives; tool names are unified as `server---tool` (`TOOL_SPLITER='---'`). Non-tool events ignore the matcher.
- **Config structure** (`config.hooks` or `hooks.json`/YAML): under each event is a set of `{matcher, hooks:[{type, command, timeout, failClosed}]}`. Meta keys: `enabled_sources` (default `[native]`), `enabled_executors` (default `[command]`), `fail_closed`, `default_model`.
- **Multi-platform loader**: `native` (`~/.ms_agent/hooks.yaml`, agent.yaml, project `hooks.json`), `claude` (`.claude/settings.json`), `cursor` (`.cursor/hooks.json`), `hermes` (`~/.hermes/config.yaml`), `plugin` (a plugin's `hooks/hooks.json`). Each platform's event names are normalized to the canonical set and merged low→high priority.

> Only the `command` executor is implemented today; the `http` / `prompt` / `agent` executors are proposals, see [rfcs/hooks-executors.md](./rfcs/hooks-executors.md).

---

## Appendix C: MCP Runtime State Machine and Configuration

`MCPRuntime` (`mcp/runtime.py`) is a config-driven MCP lifecycle state machine.

### C.1 States and transitions

State set (`MCPServerStatus`): `registered / connecting / connected / degraded / error / disabled`.

```
(new, enabled)   → registered
(new, disabled)  → disabled
registered/error → connecting → connected        # connection succeeds
connecting       → error                          # connection fails
connected        → degraded                       # a hard failure, or ≥ 3 consecutive failures
any enabled      → disabled                        # disable_server / apply_config
degraded         → connected                       # only via a successful reconnect (record_success does not clear degraded)
```

`is_callable(server)` only when `status == 'connected'`; `sync_tools()` indexes only connected + enabled servers.

### C.2 Failure classification and degradation

- Classification (`classify_mcp_failure`): `transient` (timeout / 502 / 503), `hard` (connection dropped / reset / refused), `none` (business/argument errors, no status change).
- Thresholds: `DEGRADED_FAILURE_THRESHOLD = 3`, `FAILURE_HISTORY_LIMIT = 20`. Degradation condition: `hard`, or ≥ 3 consecutive failures, while currently `connected`. `record_success` resets the consecutive-failure counter but does not clear `degraded`.

### C.3 Public API (summary)

`start / stop`, `enable_server / disable_server`, `reload_server / reconnect_server`, `apply_config` (add/remove/change diff + reconnect + sync), `list_servers / get_server`, `is_callable / unavailable_detail`, `record_failure / record_success`, `bind_tool_manager / sync_tools`.

### C.4 Configuration model

- `ResolvedMCPConfig.mcp_servers`: `{name: entry}`; `to_mcp_json()` → `{'mcpServers': ...}`; `enabled_servers()` filters by `enabled`.
- Server-entry connection fields: `enabled / transport / type / command / args / url / env / headers / timeout / include / exclude / source / meta`, etc.; `source ∈ {global, project, agent_yaml, plugin, session}`.
- Merge (`merge_mcp_layers`): later layers override earlier by name, `meta` is deep-merged, and `enabled` is overridden only when the override layer gives it explicitly.
- `MCPConfigManager` (scopes: `global / project / merged`): global reads `settings.json`'s `mcp_servers` and `mcp.json` (settings wins), project reads `.ms_agent/mcp.json`; writes land only in `global` or `project`, and project deletion uses a `_removed` mask rather than a physical delete.

> The external-Server-facing `/api/mcp/*` and hot-update event persistence are proposals, see [rfcs/mcp-runtime-api.md](./rfcs/mcp-runtime-api.md).

---

## Appendix D: Configuration Field Reference

### D.1 Main agent.yaml fields

`llm` (`service / model / {service}_api_key / {service}_base_url`), `generation_config` (`temperature / top_k / stream / extra_body`), `prompt.system`, `tools`, `skills` (`sources / disabled / prompt_injection / update_notice`), `memory`, `permission` (see Appendix A), `hooks` (see Appendix B), `session_log`, `compaction`, `max_chat_round`, `callbacks`, `output_dir`.

### D.2 settings.json → agent config mapping

`ConfigResolver._settings_to_agent_config()`:

| settings.json | → agent config |
|---------------|----------------|
| `llm.provider` | `llm.service` |
| `llm.model` | `llm.model` |
| `llm.api_key` | `llm.{provider}_api_key` (dynamic prefix) |
| `llm.base_url` | `llm.{provider}_base_url` |
| `llm.temperature` (when `temperature_enabled`) | `generation_config.temperature` |
| `llm.max_tokens` | `generation_config.max_tokens` |
| `default_model` (`provider/model` or `model`) | fallback for `llm.service` / `llm.model` |
| `output_dir` | `output_dir` |
| `personalization.{global_instruction, memory_enabled, memory_backend}` | `personalization.*` |
| `tools` | `tools` (`tools.<id>.enabled: false` disables a tool) |
