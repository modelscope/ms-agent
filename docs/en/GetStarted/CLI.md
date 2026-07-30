---
slug: CLI
title: CLI Reference
description: Complete reference for the MS-Agent command line (CLI)
---

# CLI Reference

Installing MS-Agent registers the `ms-agent` console command. Use it to run an
agent, launch the Web/terminal UI, manage scheduled jobs, manage agent files and
plugins, and start A2A / ACP protocol services.

Invocation format:

```shell
ms-agent <command> [<args>]
```

List all commands:

```shell
ms-agent --help
```

Command overview:

| Command | Description |
| --- | --- |
| `run` | Run an agent (single query or interactive mode) |
| `tui` | Launch the terminal interactive UI (TUI) |
| `ui` | Launch the Web UI server |
| `app` | Launch a Gradio app (DeepResearch / FinResearch) |
| `cron` | Scheduled-job orchestration (daemon + job management) |
| `agent` | Manage agent workspace files (upload/download/sync/convert/backup, etc.) |
| `plugin` | Install and manage plugins |
| `a2a` | Start an A2A (Agent-to-Agent) protocol HTTP server |
| `a2a-registry` | Generate an A2A Agent Card (`agent-card.json`) |
| `acp` | Start an ACP (Agent Client Protocol) server (stdio, or HTTP) |
| `acp-proxy` | Start an ACP proxy that routes to multiple backend agents |
| `acp-registry` | Generate an ACP `agent.json` manifest |

> Notes: an empty "Default" cell means there is no default value; arguments
> marked **required** must be provided. Flag arguments (`action=store_true`)
> take no value — their presence means `true`.

---

## run — Run an Agent

Run an agent from a config or a query. Without `--query`, it enters interactive
mode.

```shell
ms-agent run --config path/to/agent.yaml --query "Hello"
```

| Argument | Description | Default |
| --- | --- | --- |
| `--config` | Directory or ModelScope repo id of the config file | `None` |
| `--query` | Query/prompt to send to the LLM; if unset, enters interactive mode | `None` |
| `--output_dir` | Directory for agent outputs, histories and artifacts; overrides `output_dir` in the config | `None` |
| `--project` | Use a built-in project (choices come from the built-in project list) | `None` |
| `--env` | Path to a `.env` file; if omitted, loads `./.env` when present | `None` |
| `--trust_remote_code` | Trust external code referenced by the config file | `false` |
| `--load_cache` | Load previous step histories from cache (useful when retrying a failed query) | `false` |
| `--mcp_config` | Extra MCP server config | `None` |
| `--mcp_server_file` | Extra MCP server file | `None` |
| `--openai_api_key` | API key for an OpenAI-compatible service | `None` |
| `--modelscope_api_key` | API key for ModelScope api-inference services | `None` |
| `--animation_mode` | Animation mode for the video-generation project: `auto` / `human` | `None` |
| `--knowledge_search_paths` | Comma-separated list of paths for knowledge search | `None` |

---

## tui — Terminal UI

Launch an interactive UI in the terminal.

```shell
ms-agent tui --config path/to/agent.yaml
```

| Argument | Description | Default |
| --- | --- | --- |
| `--config` | Path to an `agent.yaml` (or a task dir / ModelScope id) | built-in `agent.yaml` |
| `--work-dir`, `--work_dir` | Working/project directory (== `output_dir`) | current directory |
| `--env` | Path to a `.env` file | `./.env` |
| `--permission_mode` | Permission mode for tool calls: `auto` / `strict` / `restricted` / `interactive` | `restricted` |
| `--trust_remote_code` | Allow loading external code referenced by the config (flag) | `false` |
| `--mcp-server-file`, `--mcp_server_file` | Path to an MCP servers JSON file | `None` |
| `--emit-events`, `--emit_events` | Also append every structured AgentEvent as JSON lines to this file | `None` |

---

## ui — Web UI Server

Launch the Web UI server.

```shell
ms-agent ui --host 0.0.0.0 --port 7860
```

| Argument | Description | Default |
| --- | --- | --- |
| `--host` | The server host to bind to | `0.0.0.0` |
| `--port` | The server port to bind to | `7860` |
| `--reload` | Enable auto-reload for development (flag) | `false` |
| `--production` | Run in production mode (serve built frontend, flag) | `false` |
| `--no-browser` | Do not automatically open the browser (flag) | `false` |

---

## app — Gradio App

Launch a Gradio application UI.

```shell
ms-agent app --app_type doc_research
```

| Argument | Description | Default |
| --- | --- | --- |
| `--app_type` | App type: `doc_research` / `fin_research` (**required**) | `doc_research` |
| `--server_name` | Gradio server name to bind to | `0.0.0.0` |
| `--server_port` | Gradio server port to bind to | `7860` |
| `--share` | Share the Gradio app publicly (flag) | `false` |

---

## cron — Scheduled Jobs

Manage the cron daemon and jobs. Format: `ms-agent cron <action> [<args>]`.

```shell
ms-agent cron start --foreground
ms-agent cron create "0 9 * * *" "Generate daily report" --name daily-report
ms-agent cron list --all
```

| Subcommand | Arguments | Description |
| --- | --- | --- |
| `start` | `--foreground`; `--workspace PATH`; `--env PATH` | Start the cron daemon; `--foreground` runs in foreground |
| `stop` | none | Stop the cron daemon |
| `status` | none | Show scheduler status |
| `tick` | `--verbose` | Run a single scheduler tick |
| `list` | `--all` (include disabled); `--json` (JSON output) | List cron jobs |
| `create` | `schedule` (**required**, positional); `prompt` (**required**, positional); `--name`; `--project PATH`; `--timeout SEC` | Create a cron job; `schedule` is a schedule expression |
| `pause` | `job_id` (**required**, positional) | Pause a job |
| `resume` | `job_id` (**required**, positional) | Resume a paused job |
| `run` | `job_id` (**required**, positional) | Run a job immediately |
| `remove` | `job_id` (**required**, positional) | Remove a job |
| `history` | `job_id` (**required**, positional); `--limit` (default `10`) | Show job run history |
| `output` | `job_id` (**required**, positional); `--last` (latest output) | Show job output |
| `import` | none | Import jobs from `jobs.d/*.yaml` declarations |

---

## agent — Agent Hub File Management

Manage agent files between the local workspace and remote repositories: upload,
download, background sync, list remote repositories, cross-framework conversion,
local status, backups and restore. Format: `ms-agent agent <action> [<args>]`.

**Supported frameworks**: `qoder`, `qwenpaw`, `openclaw`, `hermes`, `nanobot`, `openhuman`, `ms-agent`.

**Shared credential options** (common to the network subcommands `upload` / `download` / `watch` / `list`):

| Argument | Description | Default |
| --- | --- | --- |
| `--token` | API token; falls back to `ms login` / `MODELSCOPE_API_TOKEN` | `None` |
| `--endpoint` | API endpoint; falls back to `MODELSCOPE_ENDPOINT` | `None` |

```shell
ms-agent agent upload -f qwenpaw -r user/my-agent
ms-agent agent download -f qwenpaw -r user/my-agent
ms-agent agent watch -f qwenpaw -r user/my-agent --pull
ms-agent agent convert --from-framework qoder --target-framework qwenpaw
```

### upload — Upload local agent files to a remote repository

| Argument | Description | Default |
| --- | --- | --- |
| `-f`, `--framework` | Agent framework (**required**) | |
| `-r`, `--repo` | Remote repo identifier, supports `owner/name` (**required**) | |
| `-n`, `--name` | Local agent name; auto-selected if only one exists, errors if multiple | `None` |
| `--local-dir` | Override local workspace root (default: framework standard path) | `None` |
| `--visibility` | Visibility of the remote repo when created: `public` / `private` | `public` |
| `--dry-run` | List files that would be uploaded without uploading (flag) | `false` |
| `--token` / `--endpoint` | See shared credential options above | `None` |

### download — Download agent files from a remote repository

| Argument | Description | Default |
| --- | --- | --- |
| `-f`, `--framework` | Agent framework (**required**) | |
| `-r`, `--repo` | Remote repo identifier, supports `owner/name` (**required**) | |
| `-n`, `--name` | Local agent name to write as (default `default`) | `None` |
| `--local-dir` | Override local workspace root (default: framework standard path) | `None` |
| `--target-framework` | Convert to a different framework on download | `None` |
| `--dry-run` | List files that would be written without writing (flag) | `false` |
| `--token` / `--endpoint` | See shared credential options above | `None` |

### watch — Background sync

Launch a background daemon that watches local changes and pushes to remote; with
`--pull`, also pulls remote changes to local (bidirectional sync).

| Argument | Description | Default |
| --- | --- | --- |
| `-f`, `--framework` | Agent framework (**required**) | |
| `-r`, `--repo` | Remote repo identifier, supports `owner/name` (**required**) | |
| `-n`, `--name` | Agent name to sync (default: ALL agents in the workspace) | `None` |
| `--local-dir` | Override local workspace root (default: framework standard path) | `None` |
| `--pull` | Enable bidirectional sync; pull remote changes to local (default: push-only, flag) | `false` |
| `--token` / `--endpoint` | See shared credential options above | `None` |

### list — List remote agent repositories

Query and display remote agent repositories with pagination.

| Argument | Description | Default |
| --- | --- | --- |
| `--owner` | Filter by owner username or organization name | `None` |
| `--page` | Page number for pagination | `1` |
| `--page-size` | Number of items per page | `10` |
| `--token` / `--endpoint` | See shared credential options above | `None` |

### status — Show local agent status

| Argument | Description | Default |
| --- | --- | --- |
| `-f`, `--framework` | Agent framework (**required**) | |
| `--local-dir` | Override local workspace root (default: framework standard path) | `None` |

### backups — List available backups

Backups are named `{framework}_{name}_{date}_{time}.zip`.

| Argument | Description | Default |
| --- | --- | --- |
| `-f`, `--framework` | Filter backups by framework name prefix | `None` |
| `-n`, `--name` | Filter backups by agent name (matches `_{name}_` in the filename) | `None` |
| `--local-dir` | Override local workspace root | `None` |

### restore — Restore from a backup

Restore the workspace from a backup zip; the current state is backed up first.

| Argument | Description | Default |
| --- | --- | --- |
| `--from-backup` | `last` (most recent matching backup) or a specific backup filename (**required**) | |
| `-f`, `--framework` | Filter backup candidates by framework (used with `last`) | `None` |
| `-n`, `--name` | Filter backup candidates by agent name (used with `last`) | `None` |
| `--local-dir` | Override the restore target directory | `None` |

### convert — Local cross-framework conversion (offline)

Convert agent workspace files from one framework format to another. Skips default
template files with no custom content, and automatically backs up existing target
files before writing.

| Argument | Description | Default |
| --- | --- | --- |
| `--from-framework` | Source framework (**required**) | |
| `--target-framework` | Target framework (**required**) | |
| `--from-name` | Source agent name to read (default `default`) | `None` |
| `--target-name` | Target agent name to write as (default: same as `--from-name`) | `None` |
| `--local-dir` | Source workspace root to read from (default: source framework path) | `None` |
| `--out-dir` | Destination directory to write to (default: target framework path) | `None` |
| `--dry-run` | Show what would be written without writing (flag) | `false` |

### stop — Stop background sync

No arguments. Gracefully stop the background `watch` daemon (cross-platform:
stop-file + SIGTERM).

```shell
ms-agent agent stop
```

---

## plugin — Plugin Management

Install and manage plugins. Format: `ms-agent plugin <action> [<args>]`.

```shell
ms-agent plugin install ./my-plugin
ms-agent plugin install github://org/repo@main#subdir
ms-agent plugin list --json
```

### install — Install a plugin

Supports local paths, `github://`, `modelscope://`, and marketplace aliases.

| Argument | Description | Default |
| --- | --- | --- |
| `source` | Plugin source (**required**, positional), e.g. `./path`, `github://org/repo@ref#subdir`, `hookify@claude-plugins-official` | |
| `--scope` | Install scope: `global` / `project` | `global` |
| `--project-path` | Project path for project-scoped install | `None` |
| `--link` | Symlink local plugin sources instead of copying (flag) | `false` |
| `--force` | Replace an existing managed plugin copy (flag) | `false` |
| `--disabled` | Install but keep the plugin disabled (flag) | `false` |

### list — List installed plugins

| Argument | Description | Default |
| --- | --- | --- |
| `--project-path` | Project path for merged plugin listing | `None` |
| `--json` | Print machine-readable JSON (flag) | `false` |

### toggle — Enable/disable a plugin

| Argument | Description | Default |
| --- | --- | --- |
| `plugin_id` | Plugin id (**required**, positional) | |
| `--enable` | Enable the plugin (default action, flag) | `false` |
| `--disable` | Disable the plugin (flag) | `false` |
| `--scope` | Scope: `global` / `project` | `global` |
| `--project-path` | Project path | `None` |

### uninstall — Remove a plugin

| Argument | Description | Default |
| --- | --- | --- |
| `plugin_id` | Plugin id (**required**, positional) | |
| `--scope` | Scope: `global` / `project` | `global` |
| `--purge` | Delete managed plugin files (flag) | `false` |
| `--project-path` | Project path | `None` |

---

## a2a — A2A Protocol Server

Start an A2A (Agent-to-Agent) protocol HTTP server.

```shell
ms-agent a2a --config researcher.yaml --host 0.0.0.0 --port 5000
```

| Argument | Description | Default |
| --- | --- | --- |
| `--config` | Path to the agent config YAML (**required**) | |
| `--env` | Path to a `.env` file | `None` |
| `--trust_remote_code` | Trust external code referenced by the config | `false` |
| `--host` | Host to bind the A2A server | `0.0.0.0` |
| `--port` | Port to bind the A2A server | `5000` |
| `--max-tasks` | Maximum concurrent A2A tasks | `8` |
| `--task-timeout` | Task inactivity timeout in seconds | `3600` |
| `--log-file` | Write logs to this file instead of stderr | `None` |

---

## a2a-registry — Generate an A2A Agent Card

Generate an Agent Card JSON for agent discovery.

```shell
ms-agent a2a-registry --config researcher.yaml --output agent-card.json
```

| Argument | Description | Default |
| --- | --- | --- |
| `--config` | Path to agent config YAML (used for metadata extraction) | `None` |
| `--output` | Output path for the agent card | `agent-card.json` |
| `--host` | Host the agent will be served on | `0.0.0.0` |
| `--port` | Port the agent will be served on | `5000` |
| `--title` | Agent display title in the card | `MS-Agent` |

---

## acp — ACP Protocol Server

Start an ACP (Agent Client Protocol) server, over stdio by default; with
`--serve-http` it starts a non-standard HTTP/SSE service API instead.

```shell
ms-agent acp --config researcher.yaml
ms-agent acp --config researcher.yaml --serve-http --host 0.0.0.0 --port 8080
```

| Argument | Description | Default |
| --- | --- | --- |
| `--config` | Path to the agent config YAML (**required**) | |
| `--env` | Path to a `.env` file | `None` |
| `--trust_remote_code` | Trust external code referenced by the config | `false` |
| `--max_sessions` | Maximum concurrent ACP sessions | `8` |
| `--session_timeout` | Session inactivity timeout in seconds | `3600` |
| `--log-file` | Write logs to this file instead of stderr | `None` |
| `--serve-http` | Start a non-standard HTTP/SSE service API instead of stdio (flag) | `false` |
| `--host` | HTTP host to bind (only with `--serve-http`) | `0.0.0.0` |
| `--port` | HTTP port to bind (only with `--serve-http`) | `8080` |
| `--api-key` | API key for HTTP authentication (or set `MS_AGENT_ACP_API_KEY`) | `None` |

---

## acp-proxy — ACP Proxy

Start an ACP proxy that routes requests to multiple backend agents.

```shell
ms-agent acp-proxy --config proxy.yaml
```

| Argument | Description | Default |
| --- | --- | --- |
| `--config` | Path to the proxy config YAML (defines backends, **required**) | |
| `--log-file` | Write logs to this file instead of stderr | `None` |

---

## acp-registry — Generate an ACP Manifest

Generate an `agent.json` manifest for the ACP Agent Registry.

```shell
ms-agent acp-registry --config researcher.yaml --output agent.json
```

| Argument | Description | Default |
| --- | --- | --- |
| `--config` | Path to agent config YAML (baked into manifest transport args) | `None` |
| `--output` | Output path for the manifest | `agent.json` |
| `--title` | Agent display title in the manifest | `MS-Agent` |
