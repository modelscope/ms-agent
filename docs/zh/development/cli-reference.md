# CLI 参数参考

下列参数表由当前源码的argparse定义生成，保留CLI原始帮助文字，避免手写默认值漂移。用 `ms-agent <command> --help` 查本机版本。操作教程见[CLI任务](../user-guide/cli.md)。

## 阅读约定

- 表中默认值是参数解析器默认值，不等于全部有效Agent配置。
- `run --trust_remote_code true` 与 `tui --trust_remote_code` 语法不同。
- 未知 `--a.b value` 可被任务配置层解析；并非每个管理命令都支持。
- `run --mcp_server_file`是文档推荐的MCP文件入口，不能仅凭参数被声明认定其他兼容选项已接入。
- 凭据使用环境变量或私有dotenv；避免将Key保留在命令历史。

## `ms-agent run`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--env` | — | Path to a .env file. If omitted, loads ./.env from the current working directory when present; missing file is ignored. |
| `--query` | — | The query or prompt to send to the LLM. If not set, will enter an interactive mode. |
| `--config` | — | The directory or the repo id of the config file |
| `--output_dir` | — | Directory for agent outputs, histories, and artifacts. Overrides output_dir in the config file. |
| `--project` | — | Built-in bundled project name under package ms_agent/projects. |
| `--trust_remote_code` | false | Trust the code belongs to the config file, default False |
| `--load_cache` | false | Load previous step histories from cache, this is useful when a query fails and retry |
| `--mcp_config` | — | The extra mcp server config |
| `--mcp_server_file` | — | An extra mcp server file. |
| `--openai_api_key` | — | API key for accessing an OpenAI-compatible service. |
| `--modelscope_api_key` | — | API key for accessing ModelScope api-inference services. |
| `--animation_mode` | — | Animation mode for video_generate project: auto (default) or human. Choices: auto, human |
| `--knowledge_search_paths` | — | Comma-separated list of paths for knowledge search. |

## `ms-agent tui`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--config` | — | Path to an agent.yaml (or a task dir / modelscope id). Defaults to the built-in agent.yaml. |
| `--agent` | — | Install an Agent Hub template and start with it. Copy the id from https://www.modelscope.cn/agents. Example: ms-agent --agent ms-agent/stock_data_agent. A local agent.yaml or task directory is loaded in place. |
| `--work-dir, --work_dir` | — | Working/project directory (== output_dir). Defaults to the current directory. Framework internals go to &lt;work_dir&gt;/.ms_agent/; sessions are global under ~/.ms_agent/projects/. |
| `--env` | — | Path to a .env file (defaults to ./.env). |
| `--permission_mode` | ask | Permission mode for tool calls: ask (confirm uncertain calls with you), auto (a model decides them), full-access (allow them). Default `ask`. Older names restricted, interactive, strict, delegate are accepted. |
| `--trust_remote_code` | False | Allow loading external code referenced by the config. |
| `--mcp-server-file, --mcp_server_file` | — | Path to an MCP servers JSON file ({"mcpServers": {...}}) — stdio / sse / streamable_http servers to connect for this session. |
| `--emit-events, --emit_events` | — | Also append every structured AgentEvent as JSON lines to this file — the exact wire payloads a WebUI backend would forward. Use it to inspect/validate the event contract. |

## `ms-agent ui`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--host` | 127.0.0.1 | 见命令用途 |
| `--port` | — | Public port (default: a free port starting at 8000) |
| `--backend-port` | — | Internal API port (default: next free port) |
| `--no-browser` | False | 见命令用途 |
| `--skip-install` | False | Do not download or synchronize dependencies |
| `--production` | False | Compatibility alias for the default SSR mode |
| `--reload` | False | Reserved; use the documented development commands |
| `--prepare-only` | False | Prepare resources and dependencies, then exit |
| `--startup-timeout` | 120.0 | 见命令用途 |

## `ms-agent app`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--app_type` | doc_research | The app type, supported values: `doc_research`, `fin_research` |
| `--server_name` | 0.0.0.0 | The gradio server name to bind to. |
| `--server_port` | 7860 | The gradio server port to bind to. |
| `--share` | False | Whether to share the gradio app publicly. |

## `ms-agent cron`

请继续选择下列子命令。

## `ms-agent cron start`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--foreground` | False | Run in foreground. |
| `--workspace` | — | Cron workspace path. |
| `--env` | — | Path to .env file. |

## `ms-agent cron stop`

无额外参数。

## `ms-agent cron status`

无额外参数。

## `ms-agent cron tick`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--verbose` | False | 见命令用途 |

## `ms-agent cron list`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--all` | False | Include disabled jobs. |
| `--json` | False | JSON output. |

## `ms-agent cron create`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `schedule` | 必填 | Schedule expression. |
| `prompt` | 必填 | Task prompt. |
| `--name` |  | Job name. |
| `--project` | — | Agent project path. |
| `--timeout` | — | Timeout in seconds. |

## `ms-agent cron pause`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `job_id` | 必填 | 见命令用途 |

## `ms-agent cron resume`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `job_id` | 必填 | 见命令用途 |

## `ms-agent cron run`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `job_id` | 必填 | 见命令用途 |

## `ms-agent cron remove`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `job_id` | 必填 | 见命令用途 |

## `ms-agent cron history`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `job_id` | 必填 | 见命令用途 |
| `--limit` | 10 | 见命令用途 |

## `ms-agent cron output`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `job_id` | 必填 | 见命令用途 |
| `--last` | False | Show latest output. |

## `ms-agent cron import`

无额外参数。

## `ms-agent agent`

请继续选择下列子命令。

## `ms-agent agent upload`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--token` | — | API token (default: `ms login` / MODELSCOPE_API_TOKEN). |
| `--endpoint` | — | API endpoint (default: MODELSCOPE_ENDPOINT). |
| `-f, --framework` | 必填 | Agent framework (ms-agent, qwenpaw) |
| `-n, --name` | — | Local agent name; auto-selects if only one exists, errors if multiple |
| `-r, --repo` | 必填 | Remote repo identifier, supports owner/name format (e.g. user/my-agent) |
| `--local-dir` | — | Override local workspace root (default: framework standard path) |
| `--visibility` | public | Visibility of the remote repo when created (default: public) Choices: public, private |
| `--dry-run` | False | List files that would be uploaded, without actually uploading |

## `ms-agent agent download`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--token` | — | API token (default: `ms login` / MODELSCOPE_API_TOKEN). |
| `--endpoint` | — | API endpoint (default: MODELSCOPE_ENDPOINT). |
| `-f, --framework` | 必填 | Agent framework (ms-agent, qwenpaw) |
| `-r, --repo` | 必填 | Remote repo identifier, supports owner/name format (e.g. user/my-agent) |
| `-n, --name` | — | Local agent name to write as (default: "default") |
| `--local-dir` | — | Override local workspace root (default: framework standard path) |
| `--target-framework` | — | Convert to a different framework on download (ms-agent, qwenpaw) |
| `--dry-run` | False | List files that would be written, without actually writing |

## `ms-agent agent watch`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--token` | — | API token (default: `ms login` / MODELSCOPE_API_TOKEN). |
| `--endpoint` | — | API endpoint (default: MODELSCOPE_ENDPOINT). |
| `-f, --framework` | 必填 | Agent framework (ms-agent, qwenpaw) |
| `-n, --name` | — | Agent name to sync (default: ALL agents in the workspace) |
| `-r, --repo` | 必填 | Remote repo identifier, supports owner/name format (e.g. user/my-agent) |
| `--local-dir` | — | Override local workspace root (default: framework standard path) |
| `--pull` | False | Enable bidirectional sync; pull remote changes to local (default: push-only) |

## `ms-agent agent list`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--token` | — | API token (default: `ms login` / MODELSCOPE_API_TOKEN). |
| `--endpoint` | — | API endpoint (default: MODELSCOPE_ENDPOINT). |
| `--owner` | — | Filter by owner username or organization name |
| `--page` | 1 | Page number for pagination (default: 1) |
| `--page-size` | 10 | Number of items per page (default: 10) |

## `ms-agent agent status`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `-f, --framework` | 必填 | Agent framework (ms-agent, qwenpaw) |
| `--local-dir` | — | Override local workspace root (default: framework standard path) |

## `ms-agent agent backups`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `-f, --framework` | — | Filter backups by framework name prefix |
| `-n, --name` | — | Filter backups by agent name (matches _{name}_ in filename) |
| `--local-dir` | — | Override local workspace root |

## `ms-agent agent restore`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--from-backup` | 必填 | 'last' (most recent matching backup) or a specific backup filename |
| `-f, --framework` | — | Filter backup candidates by framework (used with 'last') |
| `-n, --name` | — | Filter backup candidates by agent name (used with 'last') |
| `--local-dir` | — | Override restore target directory |

## `ms-agent agent convert`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--from-framework` | 必填 | Source framework to read from (ms-agent, qwenpaw) |
| `--target-framework` | 必填 | Target framework to write to (ms-agent, qwenpaw) |
| `--from-name` | — | Source agent name to read (default: "default") |
| `--target-name` | — | Target agent name to write as (default: same as --from-name) |
| `--local-dir` | — | Source workspace root to read from (default: source framework path) |
| `--out-dir` | — | Destination directory to write to (default: target framework path) |
| `--dry-run` | False | Show what would be written without writing |

## `ms-agent agent stop`

无额外参数。

## `ms-agent plugin`

请继续选择下列子命令。

## `ms-agent plugin install`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `source` | 必填 | Plugin source, e.g. ./path, github://org/repo@ref#subdir, or hookify@claude-plugins-official |
| `--scope` | global | Install scope (default: global) Choices: global, project |
| `--project-path` | — | Project path for project-scoped install |
| `--link` | False | Symlink local plugin sources instead of copying |
| `--force` | False | Replace an existing managed plugin copy |
| `--disabled` | False | Install but keep the plugin disabled |

## `ms-agent plugin list`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--project-path` | — | Project path for merged plugin listing |
| `--json` | False | Print machine-readable JSON |

## `ms-agent plugin toggle`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `plugin_id` | 必填 | 见命令用途 |
| `--enable` | False | Enable the plugin (default action) |
| `--disable` | False | Disable the plugin |
| `--scope` | global | 见命令用途 Choices: global, project |
| `--project-path` | — | 见命令用途 |

## `ms-agent plugin uninstall`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `plugin_id` | 必填 | 见命令用途 |
| `--scope` | global | 见命令用途 Choices: global, project |
| `--purge` | False | Delete managed plugin files |
| `--project-path` | — | 见命令用途 |

## `ms-agent acp`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--config` | 必填 | Path to the agent config YAML file (e.g. researcher.yaml) |
| `--env` | — | Path to a .env file |
| `--trust_remote_code` | false | Trust external code files referenced by the config |
| `--max_sessions` | 8 | Maximum concurrent ACP sessions (default: 8) |
| `--session_timeout` | 3600 | Session inactivity timeout in seconds (default: 3600) |
| `--log-file` | — | Write logs to this file instead of stderr |
| `--serve-http` | False | Start a non-standard HTTP/SSE service API instead of stdio |
| `--host` | 0.0.0.0 | HTTP host to bind (only with --serve-http, default: 0.0.0.0) |
| `--port` | 8080 | HTTP port to bind (only with --serve-http, default: 8080) |
| `--api-key` | — | API key for HTTP authentication (or set MS_AGENT_ACP_API_KEY env) |

## `ms-agent acp-proxy`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--config` | 必填 | Path to the proxy config YAML (defines backends) |
| `--log-file` | — | Write logs to this file instead of stderr |

## `ms-agent acp-registry`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--config` | — | Path to agent config YAML (baked into manifest transport args) |
| `--output` | agent.json | Output path for the manifest (default: agent.json) |
| `--title` | MS-Agent | Agent display title in the manifest |

## `ms-agent a2a`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--config` | 必填 | Path to the agent config YAML file (e.g. researcher.yaml) |
| `--env` | — | Path to a .env file |
| `--trust_remote_code` | false | Trust external code files referenced by the config |
| `--host` | 0.0.0.0 | Host to bind the A2A server (default: 0.0.0.0) |
| `--port` | 5000 | Port to bind the A2A server (default: 5000) |
| `--max-tasks` | 8 | Maximum concurrent A2A tasks (default: 8) |
| `--task-timeout` | 3600 | Task inactivity timeout in seconds (default: 3600) |
| `--log-file` | — | Write logs to this file instead of stderr |

## `ms-agent a2a-registry`

| 参数 | 默认值 | 说明（来自CLI定义） |
| --- | --- | --- |
| `--config` | — | Path to agent config YAML (used for metadata extraction) |
| `--output` | agent-card.json | Output path for the agent card (default: agent-card.json) |
| `--host` | 0.0.0.0 | Host the agent will be served on (default: 0.0.0.0) |
| `--port` | 5000 | Port the agent will be served on (default: 5000) |
| `--title` | MS-Agent | Agent display title in the card |
