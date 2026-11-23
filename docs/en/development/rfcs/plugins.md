
# RFC: Plugins Ecosystem Completion

> **Status: Draft (proposal)** · Related current state [Plugins](../../core/plugins.md)
>
> This RFC **covers only the unshipped increments**. The plugin system's core assembly (distributing skills/commands/agents/hooks/mcp/bin/settings/userConfig, multi-format manifest detection, config layering, `install/uninstall/toggle/reload`) is **already implemented** — see Plugins, not repeated here.

## Background

`PluginRuntime` can already assemble the various sub-resources of a Claude-compatible plugin into the runtime. To form a complete ecosystem loop, four areas still need completing: "hot-reload granularity, manageability, execution-context integrity, supply-chain security". The items below are to be built.

## 1. Per-plugin incremental hot reload

**Current state**: `reload()` ignores `plugin_id` and performs a full `start()` restart.

**Proposal**: reload incrementally per capability, so a single change does not trigger a full rescan:

| Capability | Incremental-reload behavior |
|------|-------------|
| skills / commands | remove the old source → rescan that plugin → refresh the system prompt |
| agents | rebuild that plugin's AgentRegistry segment |
| hooks | replace that plugin's HookRegistry segment |
| mcp | `MCPRuntime.apply_config` diff, disconnecting only removed entries |
| settings | roll back the old patch → apply the new patch |
| bin | update the PATH snapshot |
| user_config | re-read data, without auto-popping a form |

Backed by a finer plugin state machine: `installed → disabled → enabled → loading → ready | error`, supporting per-capability partial-success/partial-failure UX. Hot-reload races are guarded by the existing `_reload_lock` (+ the MCP sync lock).

## 2. Management API and settings UI

**Current state**: no `/api/plugins` routes; the `list_all()` data model is largely complete (`plugin_id/name/version/enabled/scope/path/capabilities/status/...`).

**Proposal (external-Server/UI-facing)**:

| Method | Path | Purpose |
|--------|------|------|
| GET | `/api/plugins` | List merged plugins + per-capability status |
| POST | `/api/plugins/install` | Install (body carries the source) |
| DELETE | `/api/plugins/{id}?purge=true` | Uninstall (optionally purge files) |
| PATCH | `/api/plugins/{id}` | `{enabled}` toggle |
| POST | `/api/plugins/{id}/reload` | Reload a single plugin |

The settings page places Plugins alongside MCP/Skill/Hooks; plugin-sourced skills are shown read-only and tagged by origin; the hook master switch reuses `enabled_sources` (which excludes `plugin` by default — the user must enable it explicitly and acknowledge the risk).

## 3. Implemented Hook Source Context

`HookRegistry.with_plugin_source()` already attaches `source_plugin_id`, `source_plugin_root`, and `source_plugin_data_dir` to handlers, and `_context_for_handler()` supplies that context to execution. When the factory receives registries from the plugin runtime, it skips legacy directory discovery. This is implemented; incremental reload must preserve the source metadata and isolation semantics rather than reimplement this capability.

## 4. Supply-chain and config security

- **Verification/signing** of install packages: `github://`'s `@sha` pinning is already supported and persists `resolved_sha`; further support package-level `sha256` / GPG verification (not implemented today).
- **Size checks** before install and shallow cloning, to avoid an oversized plugin dragging down the environment.
- **Secure storage** (keychain) for sensitive `userConfig` fields, avoiding plaintext in `data/<id>/config.json`; redact sensitive values on export.

## 5. P2/P3 capabilities and detect-only resources

- `commands`' `allowed-tools` frontmatter affecting execution (P2); agent selection and argument passing in WebUI (P3).
- detect-only resources (`lsp / themes / monitors / apps / channels`): currently only scanned and reported; future work adds `migration_hints` and UI presentation.
- Explicitly **out of scope**: OpenClaw `handler.ts` (TS runtime), Hermes in-process Python plugins — beyond the security boundary of plugin assembly.

## Open questions

- How should incremental hot reload and "partial failure" state be expressed in the UI (overall degraded vs per-capability annotation)?
- Does the plugin data directory need project-level isolation (currently the global `plugins/data/<id>/`)?
- Should supply-chain verification (sha256/GPG) be mandatory or optional by default? Enforced in enterprise mode?
