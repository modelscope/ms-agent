---
slug: cli
title: 命令行工具
description: MS-Agent 命令行（CLI）完整参考
---

# 命令行工具

安装 MS-Agent 后会注册控制台命令 `ms-agent`，用于运行 Agent、启动 Web/终端界面、
管理定时任务、管理 Agent 文件与插件，以及启动 A2A / ACP 协议服务。

统一调用格式：

```shell
ms-agent <command> [<args>]
```

查看全部命令：

```shell
ms-agent --help
```

命令一览：

| 命令 | 说明 |
| --- | --- |
| `run` | 运行一个 Agent（单次查询或进入交互模式） |
| `tui` | 启动终端交互界面（TUI） |
| `ui` | 启动 Web UI 服务 |
| `app` | 启动 Gradio 应用（DeepResearch / FinResearch） |
| `cron` | 定时任务调度（守护进程 + 任务管理） |
| `agent` | 管理 Agent 工作区文件（上传/下载/同步/转换/备份等） |
| `plugin` | 安装与管理插件 |
| `a2a` | 启动 A2A（Agent-to-Agent）协议 HTTP 服务 |
| `a2a-registry` | 生成 A2A Agent Card（`agent-card.json`） |
| `acp` | 启动 ACP（Agent Client Protocol）服务（stdio，或 HTTP） |
| `acp-proxy` | 启动 ACP 代理，路由到多个后端 Agent |
| `acp-registry` | 生成 ACP `agent.json` 清单 |

> 说明：表格中「默认值」为空表示无默认值；标注 **必填** 的参数必须提供。开关型参数
> （`action=store_true`）不接收值，出现即为 `true`。

---

## run — 运行 Agent

从配置或查询运行一个 Agent。不指定 `--query` 时进入交互模式。

```shell
ms-agent run --config path/to/agent.yaml --query "你好"
```

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--config` | 配置文件所在目录或 ModelScope 仓库 id | `None` |
| `--query` | 发送给 LLM 的查询/提示；不设置则进入交互模式 | `None` |
| `--output_dir` | Agent 输出、历史与产物目录，覆盖配置中的 `output_dir` | `None` |
| `--project` | 使用内置项目（取值范围为内置项目列表） | `None` |
| `--env` | `.env` 文件路径；缺省时若存在则加载当前目录 `./.env` | `None` |
| `--trust_remote_code` | 是否信任配置文件引用的外部代码 | `false` |
| `--load_cache` | 从缓存加载上一步历史（查询失败后重试时有用） | `false` |
| `--mcp_config` | 额外的 MCP server 配置 | `None` |
| `--mcp_server_file` | 额外的 MCP server 文件 | `None` |
| `--openai_api_key` | 访问 OpenAI 兼容服务的 API key | `None` |
| `--modelscope_api_key` | 访问 ModelScope api-inference 服务的 API key | `None` |
| `--animation_mode` | 视频生成项目的动画模式，取值 `auto` / `human` | `None` |
| `--knowledge_search_paths` | 知识检索路径，逗号分隔 | `None` |

---

## tui — 终端交互界面

在终端启动交互式界面。

```shell
ms-agent tui --config path/to/agent.yaml
```

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--config` | `agent.yaml` 路径（或任务目录 / ModelScope id） | 内置 `agent.yaml` |
| `--work-dir`, `--work_dir` | 工作/项目目录（等同 `output_dir`） | 当前目录 |
| `--env` | `.env` 文件路径 | `./.env` |
| `--permission_mode` | 工具调用权限模式：`auto` / `strict` / `restricted` / `interactive` | `restricted` |
| `--trust_remote_code` | 允许加载配置引用的外部代码（开关） | `false` |
| `--mcp-server-file`, `--mcp_server_file` | MCP servers JSON 文件路径 | `None` |
| `--emit-events`, `--emit_events` | 将结构化 AgentEvent 以 JSON Lines 追加到该文件 | `None` |

---

## ui — Web UI 服务

启动源码仓库中的 WebUI 开发栈。该命令同时管理内部 FastAPI 服务和公开的 React Router 开发服务。

```shell
ms-agent ui
```

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--host` | 公开前端绑定的主机 | `127.0.0.1` |
| `--port` | 公开前端端口 | `7860` |
| `--backend-port` | 内部 FastAPI 端口 | `8000` |
| `--reload` | 后端源码变化时自动重载（开关） | `false` |
| `--mock` | 使用内存模拟后端而非 MS-Agent（开关） | `false` |
| `--skip-install` | 跳过依赖同步；要求 `.venv` 和 `node_modules` 已存在（开关） | `false` |
| `--production` | 兼容性保留参数；当前会提示不支持并退出 | `false` |
| `--no-browser` | 不自动打开浏览器（开关） | `false` |

启动器要求 uv、Node.js 22.22.0 或更高版本以及 pnpm 10.x，并会在首次使用时安装锁定的项目内依赖。安装、模型配置、环境变量、Windows 支持与排障说明见 [WebUI 完整指南](https://github.com/modelscope/ms-agent/blob/main/webui/README_ZH.md)。

---

## app — Gradio 应用

启动 Gradio 应用界面。

```shell
ms-agent app --app_type doc_research
```

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--app_type` | 应用类型：`doc_research` / `fin_research`（**必填**） | `doc_research` |
| `--server_name` | Gradio 服务绑定的主机名 | `0.0.0.0` |
| `--server_port` | Gradio 服务绑定的端口 | `7860` |
| `--share` | 是否公开共享 Gradio 应用（开关） | `false` |

---

## cron — 定时任务

管理定时任务守护进程与任务。调用格式：`ms-agent cron <子命令> [<args>]`。

```shell
ms-agent cron start --foreground
ms-agent cron create "0 9 * * *" "生成每日报告" --name daily-report
ms-agent cron list --all
```

| 子命令 | 参数 | 说明 |
| --- | --- | --- |
| `start` | `--foreground`；`--workspace PATH`；`--env PATH` | 启动 cron 守护进程；`--foreground` 前台运行 |
| `stop` | 无 | 停止 cron 守护进程 |
| `status` | 无 | 查看调度器状态 |
| `tick` | `--verbose` | 执行一次调度 tick |
| `list` | `--all`（含已禁用）；`--json`（JSON 输出） | 列出定时任务 |
| `create` | `schedule`（**必填**，位置参数）；`prompt`（**必填**，位置参数）；`--name`；`--project PATH`；`--timeout SEC` | 创建定时任务；`schedule` 为调度表达式 |
| `pause` | `job_id`（**必填**，位置参数） | 暂停任务 |
| `resume` | `job_id`（**必填**，位置参数） | 恢复已暂停任务 |
| `run` | `job_id`（**必填**，位置参数） | 立即运行任务 |
| `remove` | `job_id`（**必填**，位置参数） | 删除任务 |
| `history` | `job_id`（**必填**，位置参数）；`--limit`（默认 `10`） | 查看任务运行历史 |
| `output` | `job_id`（**必填**，位置参数）；`--last`（最新一次输出） | 查看任务输出 |
| `import` | 无 | 从 `jobs.d/*.yaml` 声明导入任务 |

---

## agent — Agent Hub 文件管理

在本地工作区与远端仓库之间管理 Agent 文件：上传、下载、后台同步、列出远端仓库、
跨框架转换、本地状态、备份与恢复。调用格式：`ms-agent agent <子命令> [<args>]`。

**支持的框架**：`qoder`、`qwenpaw`、`openclaw`、`hermes`、`nanobot`、`openhuman`、`ms-agent`。

**共享凭据参数**（网络类子命令 `upload` / `download` / `watch` / `list` 通用）：

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--token` | API token；缺省时回退到 `ms login` / `MODELSCOPE_API_TOKEN` | `None` |
| `--endpoint` | API endpoint；缺省时回退到 `MODELSCOPE_ENDPOINT` | `None` |

```shell
ms-agent agent upload -f qwenpaw -r user/my-agent
ms-agent agent download -f qwenpaw -r user/my-agent
ms-agent agent watch -f qwenpaw -r user/my-agent --pull
ms-agent agent convert --from-framework qoder --target-framework qwenpaw
```

### upload — 上传本地 Agent 文件到远端仓库

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `-f`, `--framework` | Agent 框架（**必填**） | |
| `-r`, `--repo` | 远端仓库标识，支持 `owner/name` 格式（**必填**） | |
| `-n`, `--name` | 本地 Agent 名称；仅一个时自动选择，多个则报错 | `None` |
| `--local-dir` | 覆盖本地工作区根目录（默认为框架标准路径） | `None` |
| `--visibility` | 创建远端仓库时的可见性：`public` / `private` | `public` |
| `--dry-run` | 仅列出将上传的文件，不实际上传（开关） | `false` |
| `--token` / `--endpoint` | 见上方共享凭据参数 | `None` |

### download — 从远端仓库下载 Agent 文件

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `-f`, `--framework` | Agent 框架（**必填**） | |
| `-r`, `--repo` | 远端仓库标识，支持 `owner/name` 格式（**必填**） | |
| `-n`, `--name` | 写入的本地 Agent 名称（默认 `default`） | `None` |
| `--local-dir` | 覆盖本地工作区根目录（默认为框架标准路径） | `None` |
| `--target-framework` | 下载时转换为另一框架格式 | `None` |
| `--dry-run` | 仅列出将写入的文件，不实际写入（开关） | `false` |
| `--token` / `--endpoint` | 见上方共享凭据参数 | `None` |

### watch — 后台同步

启动后台守护进程监听本地变更并推送到远端；`--pull` 时同时拉取远端变更（双向同步）。

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `-f`, `--framework` | Agent 框架（**必填**） | |
| `-r`, `--repo` | 远端仓库标识，支持 `owner/name` 格式（**必填**） | |
| `-n`, `--name` | 要同步的 Agent 名称（默认工作区内的全部 Agent） | `None` |
| `--local-dir` | 覆盖本地工作区根目录（默认为框架标准路径） | `None` |
| `--pull` | 启用双向同步，将远端变更拉取到本地（默认仅推送，开关） | `false` |
| `--token` / `--endpoint` | 见上方共享凭据参数 | `None` |

### list — 列出远端 Agent 仓库

分页查询并展示远端 Agent 仓库。

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--owner` | 按拥有者用户名或组织名过滤 | `None` |
| `--page` | 分页页码 | `1` |
| `--page-size` | 每页条目数 | `10` |
| `--token` / `--endpoint` | 见上方共享凭据参数 | `None` |

### status — 查看本地 Agent 状态

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `-f`, `--framework` | Agent 框架（**必填**） | |
| `--local-dir` | 覆盖本地工作区根目录（默认为框架标准路径） | `None` |

### backups — 列出可用备份

备份文件命名格式：`{framework}_{name}_{date}_{time}.zip`。

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `-f`, `--framework` | 按框架名前缀过滤备份 | `None` |
| `-n`, `--name` | 按 Agent 名称过滤备份（匹配文件名中的 `_{name}_`） | `None` |
| `--local-dir` | 覆盖本地工作区根目录 | `None` |

### restore — 从备份恢复

从备份 zip 恢复工作区，恢复前会先备份当前状态。

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--from-backup` | `last`（最近匹配的备份）或指定的备份文件名（**必填**） | |
| `-f`, `--framework` | 按框架过滤备份候选（配合 `last` 使用） | `None` |
| `-n`, `--name` | 按 Agent 名称过滤备份候选（配合 `last` 使用） | `None` |
| `--local-dir` | 覆盖恢复目标目录 | `None` |

### convert — 本地跨框架转换（不联网）

将本地 Agent 工作区文件从一种框架格式转换为另一种。跳过无自定义内容的默认模板文件，
写入前自动备份已存在的目标文件。

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--from-framework` | 源框架（**必填**） | |
| `--target-framework` | 目标框架（**必填**） | |
| `--from-name` | 读取的源 Agent 名称（默认 `default`） | `None` |
| `--target-name` | 写入的目标 Agent 名称（默认与 `--from-name` 相同） | `None` |
| `--local-dir` | 读取的源工作区根目录（默认为源框架路径） | `None` |
| `--out-dir` | 写入的目标目录（默认为目标框架路径） | `None` |
| `--dry-run` | 仅展示将写入的内容，不实际写入（开关） | `false` |

### stop — 停止后台同步

无参数。优雅停止后台 `watch` 守护进程（跨平台：stop-file + SIGTERM）。

```shell
ms-agent agent stop
```

---

## plugin — 插件管理

安装与管理插件。调用格式：`ms-agent plugin <子命令> [<args>]`。

```shell
ms-agent plugin install ./my-plugin
ms-agent plugin install github://org/repo@main#subdir
ms-agent plugin list --json
```

### install — 安装插件

支持本地路径、`github://`、`modelscope://` 与 marketplace 别名。

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `source` | 插件来源（**必填**，位置参数），如 `./path`、`github://org/repo@ref#subdir`、`hookify@claude-plugins-official` | |
| `--scope` | 安装范围：`global` / `project` | `global` |
| `--project-path` | project 范围安装时的项目路径 | `None` |
| `--link` | 软链本地插件源而非复制（开关） | `false` |
| `--force` | 替换已存在的受管插件副本（开关） | `false` |
| `--disabled` | 安装后保持禁用状态（开关） | `false` |

### list — 列出已安装插件

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--project-path` | 合并列出插件时的项目路径 | `None` |
| `--json` | 输出机器可读的 JSON（开关） | `false` |

### toggle — 启用/禁用插件

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `plugin_id` | 插件 id（**必填**，位置参数） | |
| `--enable` | 启用插件（默认行为，开关） | `false` |
| `--disable` | 禁用插件（开关） | `false` |
| `--scope` | 范围：`global` / `project` | `global` |
| `--project-path` | 项目路径 | `None` |

### uninstall — 卸载插件

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `plugin_id` | 插件 id（**必填**，位置参数） | |
| `--scope` | 范围：`global` / `project` | `global` |
| `--purge` | 删除受管插件文件（开关） | `false` |
| `--project-path` | 项目路径 | `None` |

---

## a2a — A2A 协议服务

启动 A2A（Agent-to-Agent）协议 HTTP 服务。

```shell
ms-agent a2a --config researcher.yaml --host 0.0.0.0 --port 5000
```

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--config` | Agent 配置 YAML 路径（**必填**） | |
| `--env` | `.env` 文件路径 | `None` |
| `--trust_remote_code` | 是否信任配置引用的外部代码 | `false` |
| `--host` | A2A 服务绑定主机 | `0.0.0.0` |
| `--port` | A2A 服务绑定端口 | `5000` |
| `--max-tasks` | 最大并发 A2A 任务数 | `8` |
| `--task-timeout` | 任务不活跃超时（秒） | `3600` |
| `--log-file` | 日志写入该文件而非 stderr | `None` |

---

## a2a-registry — 生成 A2A Agent Card

为 Agent 发现生成 Agent Card JSON。

```shell
ms-agent a2a-registry --config researcher.yaml --output agent-card.json
```

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--config` | Agent 配置 YAML 路径（用于元数据抽取） | `None` |
| `--output` | Agent Card 输出路径 | `agent-card.json` |
| `--host` | Agent 将被服务的主机 | `0.0.0.0` |
| `--port` | Agent 将被服务的端口 | `5000` |
| `--title` | Card 中的 Agent 展示标题 | `MS-Agent` |

---

## acp — ACP 协议服务

启动 ACP（Agent Client Protocol）服务，默认基于 stdio；使用 `--serve-http` 时改为
启动非标准 HTTP/SSE 服务 API。

```shell
ms-agent acp --config researcher.yaml
ms-agent acp --config researcher.yaml --serve-http --host 0.0.0.0 --port 8080
```

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--config` | Agent 配置 YAML 路径（**必填**） | |
| `--env` | `.env` 文件路径 | `None` |
| `--trust_remote_code` | 是否信任配置引用的外部代码 | `false` |
| `--max_sessions` | 最大并发 ACP 会话数 | `8` |
| `--session_timeout` | 会话不活跃超时（秒） | `3600` |
| `--log-file` | 日志写入该文件而非 stderr | `None` |
| `--serve-http` | 启动非标准 HTTP/SSE 服务 API 而非 stdio（开关） | `false` |
| `--host` | HTTP 绑定主机（仅 `--serve-http` 时生效） | `0.0.0.0` |
| `--port` | HTTP 绑定端口（仅 `--serve-http` 时生效） | `8080` |
| `--api-key` | HTTP 鉴权 API key（或设置 `MS_AGENT_ACP_API_KEY`） | `None` |

---

## acp-proxy — ACP 代理

启动 ACP 代理，将请求路由到多个后端 Agent。

```shell
ms-agent acp-proxy --config proxy.yaml
```

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--config` | 代理配置 YAML 路径（定义后端，**必填**） | |
| `--log-file` | 日志写入该文件而非 stderr | `None` |

---

## acp-registry — 生成 ACP 清单

为 ACP Agent Registry 生成 `agent.json` 清单。

```shell
ms-agent acp-registry --config researcher.yaml --output agent.json
```

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--config` | Agent 配置 YAML 路径（写入清单的 transport 参数） | `None` |
| `--output` | 清单输出路径 | `agent.json` |
| `--title` | 清单中的 Agent 展示标题 | `MS-Agent` |
