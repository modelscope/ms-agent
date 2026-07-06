# Plugins 兼容系统设计文档

> 基于 [`playground_prototype_design.md`](../../../playground_prototype_design.md) F9（Plugins 兼容）；与已落地模块对齐：
> - [`hooks-design.md`](hooks-design.md) F6 / F9 Plugin hooks
> - [`mcp_runtime_management.md`](mcp_runtime_management.md) F7 Plugin MCP（`.mcp.json` / `tools/mcp.json`）→ MCPRuntime
> - Skill 体系（PR#907：`SkillCatalog` + `SkillRuntime` + `SkillsConfigManager`）
> - [`permission-design.md`](permission-design.md) 双层权限（Plugin 贡献的 MCP/Tool 调用进入 ToolManager 后受约束；Plugin hook command 脚本本身是独立子进程，见 §10.2）
>
> 状态：方案设计 v0.4 | 2026-06-23（修正安全边界、已实现状态、PluginRuntime/HookRuntime 职责、Phase 0/1 验收与链接）

---

## 目录

- [1. 背景与目标](#1-背景与目标)
- [2. 现状分析](#2-现状分析)
- [3. 总体架构](#3-总体架构)
- [4. Plugin 包格式与 Manifest](#4-plugin-包格式与-manifest)
  - [4.4 组件能力注册表（Component Registry）](#44-组件能力注册表component-registry)
- [5. 发现、安装与配置分层](#5-发现安装与配置分层)
- [6. PluginLoader — 分发注册](#6-pluginloader--分发注册)
- [7. 子资源加载语义](#7-子资源加载语义)（skills / commands / agents / hooks / mcp / bin / settings / userConfig）
- [8. PluginRuntime — 运行时管理](#8-pluginruntime--运行时管理)
- [9. 环境变量与路径变量](#9-环境变量与路径变量)
- [10. 与 Command / Permission 的协作](#10-与-command--permission-的协作)
- [11. 集成点与代码变更](#11-集成点与代码变更)
- [12. API 与 UI 数据模型](#12-api-与-ui-数据模型)
- [13. 文件结构](#13-文件结构)
- [14. 兼容矩阵](#14-兼容矩阵)
- [15. 分阶段交付与验收](#15-分阶段交付与验收)
- [16. 多生态兼容：OpenClaw 与 Hermes](#16-多生态兼容openclaw-与-hermes)
- [17. 风险与对策](#17-风险与对策)
- [18. 测试策略](#18-测试策略)
- [19. 社区 Plugin 组件全景（调研）](#19-社区-plugin-组件全景调研)
- [附录 D：黄金测例 — hookify](#附录-d黄金测例--hookify)
- [附录 A：plugins.json 示例](#附录-apluginsjson-示例)
- [附录 B：plugin.json 字段对照（Claude Code）](#附录-bpluginjson-字段对照claude-code)
- [附录 C：跨文档约定](#附录-c跨文档约定)

---

## 1. 背景与目标

### 1.1 产品背景

Claude Code / Codex 社区已沉淀大量 **Plugin 包**：在单一目录内打包 manifest + 多种可加载组件（skills、agents、commands、hooks、MCP、settings 等）。MS-Agent 实验场（Playground）需要 **复用该生态**，避免重复造轮子。

Playground 原型（F9）定义的核心诉求（**已扩展为完整组件集**，详见 §4.4 / §19）：

| 能力 | 说明 | 优先级 |
|------|------|--------|
| Manifest 解析 | 多生态 manifest 路径 + 安装时 `format` / `manifest_path` 锁定 | P0 |
| Skills 分发 | `skills/`、根 `SKILL.md` → `SkillCatalog` | P0 |
| Commands 分发 | `commands/*.md` → Skill 或 `CommandRouter` | P1 |
| Agents 分发 | `agents/*.md` → 子 agent 模板 / `AgentDelegate` | P1 |
| Hooks 分发 | `hooks/hooks.json`、`hooks/hermes.yaml` → `HookRegistry` | P0/P1 |
| MCP 分发 | `.mcp.json` / `tools/mcp.json` → `MCPRuntime` | P1 |
| 运行时辅助 | `bin/` PATH、`settings.json` 补丁、`userConfig` 表单 | P1 |
| 元数据 / UI | `assets/`、`interface.*`、`dependencies` | P1 UI |
| 环境变量桥接 | `PLUGIN_ROOT` / `PLUGIN_DATA` / `user_config.*` | P0 |
| 安装来源 | 本地 / `github://` / `modelscope://` / marketplace | P0–P1 |

### 1.2 设计原则

1. **Plugin 是容器，不是新子系统**：不重复实现 Skill / Hook / MCP 逻辑，只做发现、安装、enabled 管理、环境桥接与向各 Runtime 分发。
2. **与分层配置一致**：全局 → 项目 → session 的 `plugins.json` 与 `mcp.json` / `skills.json` 同级；Plugin 内子资源的 enabled 语义遵循各子系统既有规则。
3. **Gateway 无关**：同一套 `ms_agent/plugins/` 供 WebUI、TUI、CLI 共用。
4. **多生态并存**：Claude Code Plugin 为主路径；**OpenClaw / Hermes 的「检测 + 可复用子资源加载」并入 P1**（见 §16）；进程内 hook（OpenClaw `handler.ts`、Hermes Python plugin）不原生执行。
5. **安全默认**：Plugin 安装不自动 `trust_remote_code`；Plugin hooks 默认不启用。MCP / 内置 tool 调用进入 `ToolManager.single_call_tool()` 后受 SafetyGuard + Permission 约束；**hook command 脚本本身由 HookExecutor 直接启动，不经过 ToolManager，不能宣称受 PreToolUse/Permission 二次拦截**。

### 1.3 与已落地三个模块的关系

当前分支 `feat/new_playground_part` 已落地：

| 模块 | 文档 | Plugin 依赖点 |
|------|------|---------------|
| 权限管控 F4 | `permission-design.md` | Agent 发起的 MCP / tool 调用仍经 `ToolManager.single_call_tool()`；Plugin hook command 脚本自身按 hook 安全策略治理 |
| Hooks F6 | `hooks-design.md` | **`PluginHooksLoader` 已实现**；缺统一 Manifest 与 `PluginRuntime` |
| MCP 运行时 F7 | `mcp_runtime_management.md` | Phase 3 待做：Plugin `mcp` capability → MCP server |

```
                    ┌─────────────────────────────────────┐
                    │           PluginRuntime              │
                    │  (install / enabled / hot-reload)    │
                    └──────────┬──────────────────────────┘
                               │ PluginLoader.load_all()
       ┌───────────┬───────────┼───────────┬───────────┬──────────────┐
       ▼           ▼           ▼           ▼           ▼              ▼
  skills/     commands/    agents/     hooks/      .mcp.json      bin/ settings
       │           │           │           │           │              │
       ▼           ▼           ▼           ▼           ▼              ▼
 SkillRuntime  CommandRouter AgentRegistry HookRuntime  MCPRuntime  Executor/Config
 + Catalog                  (P1)         + Registry   + ToolMgr    patch (P1)
       │           │           │           │           │              │
       └───────────┴───────────┴───────────┴───────────┴──────────────┘
                               │
                    ToolManager.single_call_tool()
                    (SafetyGuard → PermissionEnforcer → Hooks)
```

**安全边界**：上图描述的是 Agent 侧 tool 调用链。`hooks/hooks.json` 中 `type=command` 的脚本由 `HookExecutor` 直接以子进程执行，当前不会再作为一次 shell tool call 进入 `PermissionEnforcer`。因此 Plugin hooks 必须通过 `hooks.enabled_sources` 显式开启，并在安装 / 启用 UI 中提示风险。

**不经过 PluginLoader 独立加载、仅扫描/report 的组件**：LSP、output-styles、themes、monitors、channels、OpenClaw `handler.ts`、Hermes Python plugin 等（§4.4 `unsupported` / `detect-only`）。

---

## 2. 现状分析

### 2.1 已实现（F9 局部）

| 组件 | 位置 | 状态 |
|------|------|------|
| `PluginHooksLoader` | `ms_agent/hooks/loaders/plugin.py` | ✅ 读取 `<plugin-id>/hooks/hooks.json`，委托 `ClaudeSettingsLoader` |
| Plugin 根目录发现 | `ms_agent/hooks/factory.py::_discover_plugin_roots` | ✅ 扫描 `.ms-agent/plugins/*` + `agent.yaml` 的 `plugins:` 列表 |
| Hook 环境变量 | `ms_agent/hooks/executors/command.py::build_hook_env` | ✅ allowlist + `MS_AGENT_*` / `CLAUDE_*` 元数据；⚠️ 执行期 `HookRuntime._ctx()` 尚未传入 plugin root/data |
| 路径变量展开 | `ms_agent/hooks/loaders/claude.py::_expand_path_vars` | ✅ `${CLAUDE_PLUGIN_ROOT}` 等 |

### 2.2 缺口

| 缺口 | 影响 |
|------|------|
| 无 `ms_agent/plugins/` 模块 | 无 Manifest 解析、无安装器、无 CRUD |
| Plugin `skills/` 未自动挂载 | 用户需手动把 plugin 路径写入 `skills.json` |
| Plugin `mcp` 未实现 | 见 `mcp_runtime_management.md` Phase 3（`.mcp.json` / `tools/mcp.json`） |
| Plugin `commands/`、`agents/` 未挂载 | 需 `PluginLoader` 分发至 SkillCatalog / AgentRegistry |
| 无 `plugins.json` 持久化 | 无法 UI 级 enable/disable / 版本管理 |
| `PluginHooksLoader` 未注入 `plugin_data_dir` | `MS_AGENT_PLUGIN_DATA` 仅在 executor 层预留，loader 未关联 plugin id |
| Hook command 安全边界未在产品层显式表达 | command 脚本是 HookExecutor 子进程，不经过 ToolManager 的 Permission / SafetyGuard；需默认关闭 + 启用提示 |
| 无安装 URI | 不能 `github://org/repo` 一键安装 |
| Command 扩展未接入 Plugin | F5 预留的注册 API 未与 Plugin manifest 联动 |

### 2.3 现有发现逻辑（待收敛）

```python
# ms_agent/hooks/factory.py — 当前临时实现
def _discover_plugin_roots(config, project_path) -> list[str]:
    # 1. <project>/.ms-agent/plugins/<plugin-id>/   （安装目标目录）
    # 2. config.plugins[] 中的相对/绝对路径            （agent.yaml 显式声明）
```

**问题**：无 manifest 校验、无 enabled 过滤、与全局 `~/.ms_agent/plugins/` 不同步。新设计将 discovery 收敛到 `PluginRegistry`。

### 2.4 术语冲突（实现时必须消歧）

当前代码里已有三处名字接近但语义不同的 “plugin”：

| 名称 | 当前位置 | 语义 | 与本文关系 |
|------|----------|------|------------|
| `config.plugins[]` | `ms_agent/hooks/factory.py` | 临时声明 Plugin hooks 根目录 | Phase 0 迁移到 `plugins.json` / `PluginRegistry` |
| `tools.plugins[]` | `ms_agent/tools/tool_manager.py` | Python `ToolBase` 外部工具插件，需 `trust_remote_code=True` | 不是本文的容器 Plugin；文档和 UI 需避免混称 |
| `plugins.json` | 本文新增 | 容器 Plugin 安装索引与 enabled 状态 | F9 正式配置入口 |

---

## 3. 总体架构

### 3.1 模块职责

```
ms_agent/plugins/
├── manifest.py      # PluginManifest 解析与校验
├── registry.py      # 已安装 Plugin 索引（内存 + 磁盘）
├── installer.py     # 本地 / github / modelscope 安装
├── config_manager.py # plugins.json CRUD（对标 MCPConfigManager）
├── loader.py        # PluginLoader：按 manifest 分发到各子系统
├── runtime.py       # PluginRuntime：enabled、热重载、聚合 list_all()
└── types.py         # PluginRecord、InstallSource、PluginStatus
```

### 3.2 数据流

```plaintext
安装/配置
  plugins.json (global / project)
       │
       ▼
  PluginConfigManager.load_merged()
       │
       ▼
  PluginRegistry.resolve()  ──→  list[PluginManifest]
       │
       ▼
  PluginLoader.load_all(manifests, ctx)
       ├─ skills/ + 根 SKILL.md     → SkillCatalog
       ├─ commands/*.md             → SkillLoader / CommandRouter
       ├─ agents/*.md               → AgentRegistry（P1）
       ├─ hooks/hooks.json + yaml    → HookRegistry
       ├─ .mcp.json / tools/mcp.json → MCPRuntime
       ├─ bin/                      → code_executor PATH（P1）
       ├─ settings.json             → ConfigResolver 补丁（P1）
       ├─ userConfig (manifest)       → plugins/data + 变量展开（P1）
       ├─ assets/ + interface         → UI 元数据（不进入 Runtime）
       └─ scan unsupported          → lsp / themes / monitors / …
       │
       ▼
  PluginRuntime
       ├─ toggle(plugin_id, enabled)
       ├─ reload(plugin_id)
       └─ list_all() → UI
```

**唯一来源约定**：Phase 0 迁移完成后，Plugin 子资源发现以 `PluginRegistry` / `PluginLoader` 为准；`build_hook_runtime()` 不再自行扫描 `.ms-agent/plugins/*`。迁移期可保留 `_discover_plugin_roots()` 作为兼容层，但必须保证同一 plugin hook 不会被 legacy path 和 `plugins.json` 双重加载。

### 3.3 与 ConfigResolver 的关系

`ConfigResolver` 在 `resolve()` 末尾已有 `_merge_mcp` / `_merge_skills`。Plugin 合并作为 **第 6 步**（在 session overrides 之后、fill_missing_fields 之前），仅用于 Playground / Server / TUI 这类分层配置入口；CLI 直读 `Config.from_task()` 的兼容路径不强制接入：

```python
# 伪代码 — config/resolver.py 扩展
def resolve(...):
    merged = self._merge_layers(layers)
    merged = self._merge_mcp(merged, project_path)
    merged = self._merge_skills(merged, project_path)
    merged = self._merge_plugins(merged, project_path)  # 新增
    return Config.fill_missing_fields(merged)
```

`_merge_plugins` 职责：

- 读取 `PluginConfigManager.load_merged(project_path)`
- 将 **enabled** 的 plugin 根路径写入 `merged.plugins`（`List[str]`，兼容现有 `agent.yaml` 字段）
- 将 plugin 衍生的 MCP server 条目 **合并进** MCP 层（见 §7.3）

---

## 4. Plugin 包格式与 Manifest

### 4.1 目录布局（Claude Code / Codex 兼容）

Manifest 位置因生态而异（**均需识别**）：

| 生态 | Manifest 路径 |
|------|---------------|
| Claude Code | `.claude-plugin/plugin.json`（组件目录在 plugin **根**） |
| Codex | `.codex-plugin/plugin.json` |
| Cursor | `.cursor-plugin/plugin.json`（bundle 检测） |
| OpenClaw native | `openclaw.plugin.json`（包根，TS 进程内） |
| MS-Agent 原生 | `plugin.json` 或 `.ms-agent-plugin/plugin.json` |

完整目录（Claude Code 官方 reference + 社区常见布局）：

```plaintext
my-plugin/
├── .claude-plugin/              # Claude：仅 manifest 在此
│   └── plugin.json
├── .codex-plugin/               # Codex：同上
│   └── plugin.json
├── README.md
├── skills/                      # Skill 目录（每子目录含 SKILL.md）
│   └── commit-helper/SKILL.md
├── SKILL.md                     # 可选：无 skills/ 时根目录单 skill
├── commands/                    # 遗留 slash command（flat .md）
├── agents/                      # Subagent 定义（.md + frontmatter）
├── hooks/
│   ├── hooks.json               # Claude/Codex plugin 格式（含 hooks 包装层）
│   └── hermes.yaml              # Hermes shell hooks（包内，P1）
├── .mcp.json                    # MCP（Claude/Codex 惯例文件名）
├── tools/                       # MS-Agent 别名：tools/mcp.json
│   └── mcp.json
├── .app.json                    # Codex App Connectors（OAuth 应用）
├── .lsp.json                    # LSP 语言服务配置
├── output-styles/               # Claude 输出风格
├── themes/                      # Claude 颜色主题（experimental）
├── monitors/                    # Claude 后台监视器（experimental）
├── bin/                         # 加入 Bash tool PATH 的可执行文件
├── settings.json                # Plugin 启用时的默认 settings 片段
├── scripts/                     # hook/MCP 引用的辅助脚本（非独立组件）
├── assets/                      # Codex UI：icon/logo/screenshots
└── rules/                       # 部分社区包携带 .claude/rules 片段
```

**原设计遗漏项**见 [§19](#19-社区-plugin-组件全景调研)。

### 4.2 plugin.json Schema

MS-Agent **超集** Claude Code manifest，未知字段忽略：

```json
{
  "name": "commit-helper",
  "version": "1.2.0",
  "description": "Conventional commit assistant",
  "author": { "name": "Alice" },
  "homepage": "https://github.com/org/commit-helper",
  "license": "MIT",
  "keywords": ["git", "commit"],

  "ms_agent": {
    "min_version": "1.0.0",
    "capabilities": [
      "skills", "commands", "agents", "hooks", "mcp",
      "settings", "bin", "user_config"
    ]
  },

  "skills": "./skills/",
  "commands": "./commands/",
  "agents": ["./agents/reviewer.md"],
  "hooks": "./hooks/hooks.json",
  "mcpServers": "./.mcp.json",
  "lspServers": "./.lsp.json",
  "outputStyles": "./output-styles/",
  "dependencies": [{ "name": "base-plugin", "version": "~1.0.0" }],
  "userConfig": { "...": "见 §19.2" },
  "defaultEnabled": true
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | ✅ | Plugin 稳定 id（目录名默认与此一致） |
| `version` | 推荐 | semver；用于升级与冲突检测 |
| `description` | 推荐 | UI 展示 |
| `ms_agent.min_version` | 可选 | SDK 版本门禁 |
| `ms_agent.capabilities` | 可选 | 声明包含的子资源，便于 UI 图标 |

**Plugin id 规则**：`manifest.name` 规范化（小写、`/` → `-`）作为 `plugin_id`；安装目录名必须一致。

#### Manifest 发现 vs 安装域（必读）

这是两个**正交**问题，原先 §4.2 列表易误解为「MS-Agent 去读 Claude 的全局缓存」——**不是**。

| 维度 | MS-Agent 行为 | 不做什么 |
|------|---------------|----------|
| **安装域 / 缓存** | 仅 `~/.ms_agent/plugins/<id>/`（global）或 `<project>/.ms-agent/plugins/<id>/`（project） | **默认不**扫描 `~/.claude/plugins/cache/`、`~/.codex/plugins/cache/`、`~/.openclaw/` |
| **配置索引** | `~/.ms_agent/plugins.json` / `.ms-agent/plugins.json` 列出 enabled + **path** | 不读 Claude `enabledPlugins`、Codex `config.toml` plugins 段 |
| **可变数据** | `~/.ms_agent/plugins/data/<id>/` | 与 Claude `CLAUDE_PLUGIN_DATA` 目录**物理隔离** |
| **Manifest 解析** | 在**已落入 MS-Agent 安装目录的那一份拷贝**上，识别其生态格式 | 不在「用户同时开了 Claude/Codex」时跨工具抢目录 |

用户本机同时装 Claude Code + Codex + MS-Agent **不会**导致 MS-Agent 加载错包，只要 MS-Agent 只消费自己的 `plugins.json` 条目。  
只有当用户用 **`--link` 开发模式** 把 `plugins.json.path` 指到 Claude 缓存里的同一路径时，才可能与 Claude 并发写同一目录——此时为显式 opt-in，文档警告。

#### Manifest 路径解析（安装时探测 + 持久化锁定）

解析发生在 **`PluginInstaller.install()` 的 staging 阶段**，结果写入 `plugins.json` 的 `format` + `manifest_path`，**运行时不再按全局优先级重猜**。

**探测顺序**（仅当安装源未声明 `format` 且目录内存在多个 manifest 时）：

1. `.ms-agent-plugin/plugin.json` — **MS-Agent 原生，显式优先**
2. 根目录 `plugin.json` 且含 `ms_agent` 段
3. `.claude-plugin/plugin.json`
4. `.codex-plugin/plugin.json`
5. `.cursor-plugin/plugin.json`
6. `openclaw.plugin.json`
7. 根目录 `plugin.json`（无 `ms_agent` 段的通用/遗留包）

**冲突规则**（同一目录多个 manifest）：

为避免「装一次后运行时格式漂移」，安装 staging 阶段必须一次性锁定 `format` + `manifest_path`。无 `format_hint` 时：

- 只有一个 manifest：直接采用；
- 同时存在 MS-Agent 原生 manifest（`.ms-agent-plugin/plugin.json` 或根 `plugin.json` 且含 `ms_agent` 段）和其他宿主 manifest：采用 MS-Agent 原生，并记录 warning；
- 其他多 manifest 并存：报 `AmbiguousPluginManifest`，要求用户显式 `--format claude|codex|...`。

```python
# 伪代码
def detect_manifest(root: Path, *, format_hint: str | None) -> tuple[Path, PluginFormat]:
    if format_hint:
        return _resolve_by_hint(root, format_hint)  # 安装 URI / CLI 指定
    candidates = _scan_all_manifests(root)
    if len(candidates) == 1:
        return candidates[0]
    native = _pick_ms_agent_native(candidates)
    if native is not None:
        return native
    if len(candidates) > 1:
        raise AmbiguousPluginManifest(candidates)  # 要求用户 --format claude
```

`PluginRegistry` / `PluginLoader` **只读** `plugins.json` 里已锁定的 `manifest_path`，避免用户后来在磁盘上多加 `.codex-plugin/` 导致运行时格式漂移。

#### 安装 URI 与「指定装进 MS-Agent」

社区 Plugin **没有** Claude 式的跨宿主自动发现；要通过 MS-Agent 安装器写入 MS-Agent 缓存，使用下列入口之一：

| 方式 | 示例 | 行为 |
|------|------|------|
| **MS-Agent URI**（推荐） | `ms-agent://plugin/install?source=github://anthropics/claude-plugins-official@main#plugins/hookify` | 明确目标宿主为 MS-Agent |
| **GitHub 子路径** | `github://org/repo@ref#plugins/foo` | fetch → **copy** 到 `~/.ms_agent/plugins/foo/` |
| **GitHub SHA pin（可选）** | `github://org/repo@<sha>#plugins/foo` 或 `...@main#foo?sha=<sha>` | 克隆后 `rev-parse` 与 pin 比对；不匹配则拒绝安装 |
| **Marketplace** | `ms-agent plugin install hookify --marketplace anthropics/claude-plugins-official` | 读 marketplace.json 的 `source.path`，仍安装到 MS-Agent 目录 |
| **本地目录** | `ms-agent plugin install /path/to/plugin` 或 `file:///...` | copy/link 到 MS-Agent 目录；**不**注册到 Claude |
| **显式 format** | `... --format claude` | 多 manifest 冲突时指定解析 |
| **显式 link** | `... --link` | path 指向外部目录（开发）；与 Claude 共享目录时用户自负 |

`plugins.json` 条目扩展（安装后持久化）：

```json
{
  "id": "hookify",
  "enabled": true,
  "managed_by": "ms-agent",
  "format": "claude",
  "manifest_path": ".claude-plugin/plugin.json",
  "source": {
    "type": "github",
    "uri": "github://anthropics/claude-plugins-official@main#plugins/hookify",
    "resolved_sha": "abc123..."
  },
  "path": "/Users/me/.ms_agent/plugins/hookify",
  "installed_at": "2026-06-18T12:00:00Z"
}
```

- `managed_by: "ms-agent"`：声明此拷贝由 MS-Agent 生命周期管理；Claude/Codex **不会**自动读取该条目。
- `format` + `manifest_path`：安装时锁定，消除多工具歧义。
- `resolved_sha`：安装时记录的 **实际检出 commit**（`git rev-parse HEAD`），用于审计与复现。
- **SHA pin（可选）**：
  - `@<commit>`：ref 本身为 7–40 位十六进制时，按 commit 检出（不再误用 `git clone --branch`）
  - `#subdir?sha=<commit>`：分支/标签可变时，用 query 锁定版本；仅当显式 pin 时才做 mismatch 拒绝
  - 未 pin 的 `@main#plugins/foo` **保持兼容**，行为与改前一致

**GitHub URI 示例**

```text
github://anthropics/claude-plugins-official@main#plugins/hookify          # 原有写法，兼容
github://owner/repo@abc123def456...#plugins/demo                          # ref 即 commit
github://owner/repo@main#plugins/demo?sha=abc123def456...                 # 分支 + 显式 pin
```

**与 Claude 并存时的推荐做法**：同一份社区包各装一份——Claude 走 `/plugin install` → `~/.claude/plugins/cache/...`；MS-Agent 走 `ms-agent plugin install` → `~/.ms_agent/plugins/...`。内容可相同，**缓存互不干扰**。

### 4.3 Manifest 解析与校验

```python
@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    description: str
    root: Path
    format: PluginFormat              # claude | codex | ms-agent | mixed | ...
    manifest_path: str                # 相对 root，安装时锁定
    capabilities: frozenset[str]      # 见 §4.4 capability id
    components: dict[str, ComponentScan]  # 每组件：path、count、status
    source: InstallSource
    installed_at: str
    enabled: bool = True

    # 约定路径（manifest 可覆盖，见 plugin.json 各 *Servers / skills / agents 字段）
    def resolve_path(self, kind: str) -> Path | None: ...
```

#### 4.3.1 Manifest 文件校验

1. **manifest 存在**：`plugins.json` 锁定的 `manifest_path` 指向的 JSON 合法可读
2. **`name`**：匹配 `^[a-z0-9][a-z0-9._-]{0,63}$`（kebab-case）
3. **`version`**：若存在则为 semver；用于升级与 `dependencies` 约束
4. **未知顶层字段**：忽略（兼容 Claude/Codex 超集）；`ms_agent plugin validate --strict` 可报 warning

#### 4.3.2 可加载组件存在性（安装门槛）

Plugin **至少须含下列「可加载组件」之一**（§4.4 `loadable=true`）。  
仅含 `scripts/`、`assets/`、`README` **不能**单独构成可安装 Plugin。

| capability id | 判定信号（任一命中即可） |
|---------------|-------------------------|
| `skills` | `skills/` 下含 `SKILL.md`；或 manifest `skills` 路径；或根 `SKILL.md` |
| `commands` | `commands/*.md`；或 manifest `commands` |
| `agents` | `agents/*.md`（或 `agents/*/AGENT.md`，warning 非标准） |
| `hooks` | `hooks/hooks.json`；manifest 内联 `hooks`；`hooks/hermes.yaml` |
| `mcp` | `.mcp.json`；`tools/mcp.json`；manifest `mcpServers` 内联 |
| `settings` | 根 `settings.json`（非空） |
| `bin` | `bin/` 下至少一个可执行文件 |
| `user_config` | manifest `userConfig` 非空 |

**不记入安装门槛、仅扫描上报**：`lsp`、`output_styles`、`themes`、`monitors`、`apps`、`channels`、`rules`、OpenClaw/Hermes 进程内扩展等（§4.4）。

#### 4.3.3 分组件内容校验

| 组件 | 规则 | 失败级别 |
|------|------|----------|
| **skills** | 每个 skill 目录须含 `SKILL.md`；frontmatter `name` 可选 | 缺 `SKILL.md` → **error**（该 skill）；其余 skill 仍可加载 |
| **commands** | 每个 `.md` 须可解析 YAML frontmatter | 单文件 **warning**，跳过 |
| **agents** | 每个 `.md` 须含 `description`；推荐 `name` | 缺 `description` → **warning** |
| **hooks** | `hooks.json` 符合 plugin 包装或 settings 格式；Hermes yaml 含 `hooks:` | 解析失败 → 该源 **error**，另一格式可并存 |
| **mcp** | JSON 合法；server 条目经 `normalize_mcp_server_entry` | 非法 server → **warning**，跳过该 server |
| **settings** | JSON 合法；仅 merge 白名单键（§7.8） | 未知键 → **warning** |
| **bin** | 文件存在；非 Windows 下检查 `+x` 或 shebang | 不可执行 → **warning** |
| **userConfig** | schema 字段 `type`/`title`/`description` 合法 | 非法项 → **error**（阻止启用表单） |
| **dependencies** | 引用的 plugin id 可解析；semver 合法 | 缺失依赖 → 安装时 **error**（可先装依赖） |

#### 4.3.4 扫描期自动发现 `capabilities`

安装 staging 阶段执行 `scan_components(root)`，不依赖 manifest 自声明（manifest `ms_agent.capabilities` 仅用于 UI 图标，**以扫描结果为准**）：

```python
def scan_components(root: Path) -> frozenset[str]:
    found: set[str] = set()
    if _has_skills(root): found.add("skills")
    if _has_commands(root): found.add("commands")
    if _has_agents(root): found.add("agents")
    if _has_hooks(root): found.add("hooks")
    if _has_mcp(root): found.add("mcp")
    if (root / "settings.json").is_file(): found.add("settings")
    if _has_bin(root): found.add("bin")
    if _manifest_user_config(root): found.add("user_config")
    # detect-only（写入 components.*.status，不计入 capabilities 门槛）
    if (root / ".lsp.json").is_file(): _mark(root, "lsp", "detect_only")
    ...
    if not found & LOADABLE_CAPABILITIES:
        raise EmptyPluginError(root)
    return frozenset(found)
```

---

### 4.4 组件能力注册表（Component Registry）

MS-Agent 用统一 **capability id** 描述 Plugin 内各组件，避免全文只写 skills/hooks/tools 三类。

| capability id | 目录 / 文件 | MS-Agent 运行时 | 阶段 | 说明 |
|---------------|-------------|-----------------|------|------|
| `skills` | `skills/*/SKILL.md`、根 `SKILL.md` | `SkillCatalog` | **P0** | 模型注入 + `/skill-name` |
| `commands` | `commands/*.md` | `SkillCatalog` 或 `CommandRouter` | **P1** | Claude 遗留 slash；2026 常与 skill 合并语义 |
| `agents` | `agents/*.md` | `AgentRegistry` → `AgentDelegate` | **P1** | 子 agent 模板；frontmatter：`model`、`tools`、`skills` |
| `hooks` | `hooks/hooks.json`、`hooks/hermes.yaml` | `HookRegistry` | **P0/P1** | command hook 为主；prompt/http P2 |
| `mcp` | `.mcp.json`、`tools/mcp.json` | `MCPRuntime` | **P1** | 与 F7 对齐；server 名冲突加 `plugin.<id>.` 前缀 |
| `settings` | `settings.json` | `ConfigResolver` 补丁 | **P1** | 白名单键：`agent`、`subagentStatusLine` 等 |
| `bin` | `bin/*` | `LocalCodeExecutor` 扩展 PATH | **P1** | plugin enable 时注入，disable 移除 |
| `user_config` | manifest `userConfig` | `plugins/data/<id>/config.json` | **P1** | `${user_config.KEY}`、`CLAUDE_PLUGIN_OPTION_*` |
| `dependencies` | manifest `dependencies[]` | `PluginInstaller` 拓扑 | **P1** | 安装顺序，非运行时组件 |
| `assets` | `assets/*` | UI only | P1 | Codex `interface.logo` 等 |
| `apps` | `.app.json` | AppConnector（OAuth） | P2 | Codex 专有 |
| `rules` | `rules/`、包内 instruction | `PersonalizationInjector` | P2 | 并入 project 指令 |
| `lsp` | `.lsp.json` | detect-only | P3 | Playground 非 IDE 核心 |
| `output_styles` | `output-styles/` | ignore / P3 | P3 | 终端呈现 |
| `themes` | `themes/` | ignore | P3 | |
| `monitors` | `monitors/monitors.json` | detect-only / P3 | P3 | 对标 Monitor tool |
| `channels` | manifest `channels[]` | P3 | P3 | MCP 消息注入 |
| `hooks_openclaw_internal` | `HOOK.md`+`handler.ts` | unsupported | detect | §16 |
| `hooks_hermes_python` | `register(ctx)` | unsupported | detect | §16 |
| `scripts` | `scripts/` | — | — | **非独立组件**；供 hooks/MCP 引用 |

**`list_all()` / `capabilities_status` 键名**与上表 `capability id` 一致，例如：

```json
"capabilities_status": {
  "skills": { "count": 1, "status": "ready" },
  "commands": { "count": 4, "status": "ready" },
  "agents": { "count": 1, "status": "ready" },
  "hooks": { "count": 4, "status": "ready" },
  "mcp": { "count": 0, "status": "skipped" },
  "settings": { "status": "skipped" },
  "bin": { "status": "skipped" },
  "lsp": { "status": "detect_only", "hint": "Playground 不加载 LSP" }
}
```

---

## 5. 发现、安装与配置分层

### 5.1 存储布局（MS-Agent 独立安装域）

| scope | 配置索引 | 安装目录（缓存） | 可变数据 |
|-------|----------|------------------|----------|
| global | `~/.ms_agent/plugins.json` | `~/.ms_agent/plugins/<plugin-id>/` | `~/.ms_agent/plugins/data/<plugin-id>/` |
| project | `<project>/.ms-agent/plugins.json` | `<project>/.ms-agent/plugins/<plugin-id>/` | 同上或 project 子目录（P2） |

对比其他宿主（**MS-Agent 默认不读取**）：

| 宿主 | 典型缓存 | MS-Agent 关系 |
|------|----------|---------------|
| Claude Code | `~/.claude/plugins/cache/<marketplace>/<name>/<version>/` | 仅当 `plugin install` **copy** 社区包后内容可相同；路径独立 |
| Codex | `~/.codex/plugins/cache/...` | 同上 |
| OpenClaw | `~/.openclaw/extensions/`、`plugins/installs.json` | bundle 可复用布局；安装域独立 |

**staging 目录**（安装中间态）：`~/.ms_agent/plugins/.staging/<uuid>/` → 校验通过后原子 `rename` 到 `<plugin-id>/`。

`plugins.json` 格式见 [附录 A](#附录-apluginsjson-示例)。

### 5.2 合并规则

与 MCP / Skills 一致：

- **并集**：global + project 均列出时，project 同 id **覆盖** global 的 `enabled` 与 `path`
- **enabled: false**：Plugin 不参与任何子系统加载；已安装文件保留磁盘
- **path 解析**：条目可为 `{ "id": "commit-helper", "source": "local", "path": "/abs/path" }` 或安装后的默认路径

### 5.3 安装来源

| 来源 | URI 示例 | Phase | 行为 |
|------|----------|-------|------|
| **MS-Agent 显式** | `ms-agent://plugin/install?source=...` | P0 | 目标宿主固定为 MS-Agent 缓存 |
| 本地目录 | `/path/to/plugin` 或 `file:///...` | P0 | **copy**（默认）或 `--link` 到 MS-Agent 目录 |
| 本地 tarball | `file:///path/plugin.tgz` | P1 | **安全解压**（防 tar slip）→ staging → 落入 MS-Agent 目录 |
| GitHub | `github://org/repo[@ref]#subdir[?sha=commit]` | P1 | shallow clone；可选 SHA pin 校验；子路径 sparse-checkout → **copy** |
| ModelScope | `modelscope://org/pack[@rev]` | P1 | 下载 → MS-Agent 目录 |
| Claude marketplace 名 | `hookify@claude-plugins-official`（CLI 糖） | P1 | 解析 marketplace.json → 同 GitHub 流程 → **装入 MS-Agent**，不调用 Claude CLI |

安装流程：

```plaintext
PluginInstaller.install(source, scope, project_path?)
  → fetch 到 staging/
  → PluginManifest.parse(staging)
  → 冲突检测（同 id 高版本 / 强制 --force）
  → 原子移动到 plugins/<plugin-id>/
  → PluginConfigManager.upsert(record)
  → PluginRuntime.reload(plugin_id)
```

**默认 copy**；开发模式可选 `--link` symlink。

#### 安装安全（`installer.py`）

| 威胁 | 对策 |
|------|------|
| 恶意 tar 路径穿越（`../../.ssh/authorized_keys`） | `_safe_extract_tar()`：Python 3.12+ 使用 `filter='data'`；低版本拒绝 `..`/绝对路径/符号链接/设备节点 |
| GitHub 检出内容与预期不符 | 可选 `@sha` 或 `?sha=` pin；`git rev-parse` 后 `_verify_resolved_sha()` |
| 不完整/错误 clone | `subprocess` `check=True`；SHA mismatch 抛 `UnsupportedPluginSource` |
| GPG 签名 / 包级 checksum | **未实现**（v1）；可后续在 URI 增加 `?sha256=` 或 manifest 签名 |

`PluginLoader._expand_vars()` 对 `user_config` **只读取一次**（递归展开时传递缓存），避免重复读 `config.json`。

### 5.4 PluginConfigManager

对标 `MCPConfigManager` / `SkillsConfigManager`：

```python
class PluginConfigManager:
    def list(scope: Literal['global','project','merged']) -> list[PluginRecord]
    def get(plugin_id: str, scope=...) -> PluginRecord | None
    def upsert(record: PluginRecord, scope=...) -> None
    def set_enabled(plugin_id: str, enabled: bool, scope=...) -> None
    def remove(plugin_id: str, scope=...) -> None   # 仅删配置；--purge 删目录
    def load_merged(project_path: str | None) -> list[PluginRecord]
```

---

## 6. PluginLoader — 分发注册

### 6.1 接口

```python
@dataclass
class PluginLoadContext:
    project_path: str
    session_id: str
    enabled_executors: frozenset[str]
    plugin_data_root: Path   # ~/.ms_agent/plugins/data

@dataclass(frozen=True)
class PluginHookContribution:
    plugin_id: str
    registry: HookRegistry
    plugin_root: Path
    plugin_data_dir: Path

class PluginLoadResult:
    skill_sources: list[SkillSource]
    hook_registries: list[PluginHookContribution]
    mcp_servers: dict[str, dict]
    command_defs: list[CommandDef]           # commands/*.md
    agent_defs: list[AgentDef]               # agents/*.md
    settings_patch: dict[str, Any]           # settings.json 片段
    bin_paths: list[Path]
    user_config_schema: dict[str, Any]
    ui_metadata: dict[str, Any]              # assets + interface
    unsupported: list[UnsupportedCapability] # lsp, themes, monitors, ...

class PluginLoader:
    @staticmethod
    def load(manifest: PluginManifest, ctx: PluginLoadContext) -> PluginLoadResult: ...

    @staticmethod
    def load_all(manifests: list[PluginManifest], ctx: PluginLoadContext) -> PluginLoadResult:
        # 按 plugin_id 排序保证确定性；hook merge 顺序 = 安装顺序
```

**Hook metadata 必须是 per-handler 级别**：`HookRegistry.merge()` 合并后只保留 `HookHandlerConfig`，不能只依赖外层 `(plugin_id, registry)` tuple。`PluginLoader` 在产出 hook registry 时必须给每个 handler 标注只读来源元数据（例如 `source_plugin_id`、`source_plugin_root`、`source_plugin_data_dir`），`HookExecutor` 执行单个 handler 时据此构造 `HookExecutionContext`。否则多 Plugin hooks 合并后无法稳定注入 `MS_AGENT_PLUGIN_ROOT` / `MS_AGENT_PLUGIN_DATA`，也无法精确热重载某个 Plugin 的 hook 段。

### 6.2 与现有 Hook factory 的迁移

**当前**：`build_hook_runtime` 内联 `_discover_plugin_roots` + 循环 `PluginHooksLoader`。

**目标**：`build_hook_runtime` 只负责把各来源 `HookRegistry` 合并成 `HookRuntime`，不负责 Plugin manifest / enabled / 安装域解析。Plugin 来源由 `PluginRegistry` 解析，`PluginLoader` 产出 `hook_registries` 后注入 hook factory。

```python
# hooks/factory.py — 重构后
def build_hook_runtime(config, *, session_id=None, plugin_hook_registries=None):
    ...
    if 'plugin' in enabled_sources:
        for contrib in (plugin_hook_registries or []):
            # contrib.registry 内的 handler 已带 source_plugin_* metadata
            loaders.append((f'plugin:{contrib.plugin_id}', contrib.registry))
```

`PluginHooksLoader` **保留**为薄封装，不删除，供 `PluginLoader` 内部调用。Phase 0 允许保留 `_discover_plugin_roots()` 兼容 `agent.yaml plugins:`，但兼容路径必须在发现到同 id 的 `plugins.json` 记录时跳过，避免重复注册同一 hooks。

### 6.3 Skills 与 Commands 挂载

**Skills**（`skills/`、manifest `skills`、根 `SKILL.md`）：

```python
for skills_path in manifest.resolve_paths("skills"):
    # SkillSource 需扩展 origin/plugin_id/capability；当前 sources.py 尚无这些字段。
    sources.append(SkillSource(
        type=SkillSourceType.LOCAL_DIR,
        path=str(skills_path),
        origin="plugin",
        plugin_id=manifest.plugin_id,
        capability="skills",
    ))
if (manifest.root / "SKILL.md").is_file():
    sources.append(...)  # 单 skill 包
```

**Commands**（`commands/*.md`，P1）：

- **策略 A（推荐）**：flat `.md` 经 `SkillLoader` 单文件模式并入 `SkillCatalog`
- **策略 B**：`CommandRouter.register` + `SUBMIT_PROMPT`
- UI 命名空间：`/plugin-id:command-name`（对齐 Claude）

`SkillSource` / `SkillSchema` / `SkillRuntime.list_all()` 需补齐来源元数据：`origin`, `plugin_id`, `capability: "skills"|"commands"`。当前代码中的 `SkillSource` 尚未包含这些字段，`SkillRuntime.list_all()` 也未返回来源信息，因此这是 Phase 0 的显式 API 扩展，而不是现有接口。**优先级**：plugin **高于** builtin，**低于** workspace sources（tier 2.5）；热重载需新增 source-level reload，或先移除该 plugin source 再重新加载。

### 6.4 Agents 挂载（P1）

扫描 `agents/*.md`（`agents/*/AGENT.md` 兼容但 deprecation warning）→ `AgentDef` → `AgentRegistry` / `AgentDelegate`。P1 可先 **list 不执行**。

### 6.5 Hooks 挂载

- `hooks/hooks.json` → `PluginHooksLoader`
- `hooks/hermes.yaml` → `HermesShellLoader`（§16.4）
- manifest 内联 `hooks` → 与文件 merge

### 6.6 MCP 挂载（P1）

探测：manifest `mcpServers` → `.mcp.json` → `tools/mcp.json`。详见 §7.5。

### 6.7 辅助组件（P1）

| 组件 | Loader 输出 |
|------|-------------|
| `settings.json` | `settings_patch` |
| `bin/` | `bin_paths` → `WorkspaceContext` |
| `userConfig` | `user_config_schema` + data 目录 |
| `assets/` + `interface` | `ui_metadata` |
| LSP / themes / monitors 等 | `unsupported`（detect-only） |

---

## 7. 子资源加载语义

> 各节 capability id 与 §4.4 注册表一致。

### 7.1 Skills

| 维度 | 语义 |
|------|------|
| Plugin `enabled=false` | 整个 Plugin 不加载；skills / commands 均不可见 |
| Skill 级 `disabled` | `SkillsConfigManager.disabled`；同名冲突时 plugin 来源优先 |
| Slash command | disabled skill 仍可通过 `/skill-name` 触发 |
| 根 `SKILL.md` | 无 `skills/` 时整包视为单 skill |
| 热重载 | `reload` → `SkillCatalog.reload_source` → `SkillRuntime.version++` |

### 7.2 Commands

| 维度 | 语义 |
|------|------|
| 与 skills 关系 | Claude 2026 统一为 skill 语义；MS-Agent P1 优先并入 `SkillCatalog` |
| Slash | `/plugin-id:cmd` 或 `/cmd`（项目内无冲突时） |
| frontmatter | `allowed-tools`、`argument-hint` 影响 Command 执行上下文（P2） |
| 注册 | `PluginLoader` 解析；优先 SkillCatalog，备选 `CommandRouter.register` |

示例 frontmatter：

```markdown
---
name: deploy
description: Deploy current project
priority: 50
---
Run deployment using scripts in ${MS_AGENT_PLUGIN_ROOT}/scripts/
```

### 7.3 Agents（Subagents）

| 维度 | 语义 |
|------|------|
| 文件 | `agents/*.md`；frontmatter：`name`、`description`、`model`、`tools`、`disallowedTools`、`skills` |
| 运行时 | P1：`list_all` 展示；P2：`AgentDelegate` 按模板 spawn |
| Plugin disable | agent 从 registry 移除 |
| 安全 | plugin agent **不可**声明 `hooks` / `mcpServers` / `permissionMode`（对齐 Claude 限制） |

### 7.4 Hooks

| 维度 | 语义 |
|------|------|
| 格式 | Claude `hooks/hooks.json`（与 `.claude/settings.json` 的 `hooks` 段同构） |
| enabled_sources | 需在 `agent.yaml` / settings 中 `hooks.enabled_sources` 含 `plugin`（**默认不含**，避免静默执行第三方脚本） |
| plugin_data_dir | `~/.ms_agent/plugins/data/<plugin-id>/` 传入 `HookExecutionContext` |
| 安全 | command hook 是独立子进程；不经过 ToolManager 的 Permission + SafetyGuard。Plugin 不能 bypass Agent tool 调用权限，但 hook 脚本自身需按 hook 风险治理 |

**推荐默认配置**（安全默认，CLI / Playground 均适用）：

```yaml
hooks:
  enabled_sources: [native]
  enabled_executors: [command]
  fail_closed: false
```

Playground 可以在**用户显式确认**或企业内置 trusted profile 中开启 `plugin` source，例如 `enabled_sources: [native, plugin]`。UI 必须在首次启用含 hooks 的第三方 Plugin 时提示：`type=command` hook 可执行任意本地命令，风险不等同于一次受控 shell tool call。未确认前，即使 Plugin 已安装且 `enabled=true`，其 hooks 也不应加载。

### 7.5 MCP（`.mcp.json` / `tools/mcp.json`）

Plugin MCP 配置示例（`.mcp.json` 惯例文件名）：

```json
{
  "mcpServers": {
    "commit-helper": {
      "command": "node",
      "args": ["${MS_AGENT_PLUGIN_ROOT}/tools/server/index.js"],
      "env": {
        "PLUGIN_CONFIG": "${MS_AGENT_PLUGIN_DATA}/config.json"
      }
    }
  }
}
```

处理规则：

1. **Server 命名**：默认使用 manifest 中的 key；若与全局 MCP 冲突，加前缀 `plugin.<plugin_id>.<name>`
2. **路径变量**：Loader 阶段展开 `${MS_AGENT_PLUGIN_ROOT}` / `${MS_AGENT_PLUGIN_DATA}` / Claude 别名
3. **合并**：注入 `ConfigResolver.resolve_mcp()` 的 project 层，携带 `source: "plugin"`, `plugin_id`
4. **enabled**：随 Plugin enabled；MCP 级 `enabled: false` 可在 `tools/mcp.json` 内 per-server 设置
5. **生命周期**：`MCPRuntime.reload_server` / `disable_server`；Plugin disable 时 disconnect 该 plugin 贡献的全部 server

详见 `mcp_runtime_management.md` §Phase 3 第一条。

### 7.6 bin/ PATH 注入（P1）

- enable：将 `<plugin-root>/bin` 追加到 `LocalCodeExecutor` / shell 的 `PATH`（plugin 作用域）
- disable：移除；不影响系统 PATH
- 与 Claude「Bash tool 可裸调 bin 内命令」语义对齐

### 7.7 settings.json 补丁（P1）

- 白名单键（一期）：`agent`、`subagentStatusLine` 及 Playground 已支持字段
- enable：merge 进 session/project resolved config；disable：revert 该 plugin 贡献的键
- OpenClaw bundle 的 Claude `settings.json` 默认值同此路径

### 7.8 userConfig（P1）

- 启用 plugin 时 UI 收集 manifest `userConfig` 字段
- 持久化：`~/.ms_agent/plugins/data/<id>/config.json`；敏感项走 keychain / credentials 文件
- 展开：`${user_config.KEY}`、`${CLAUDE_PLUGIN_OPTION_KEY}` 用于 MCP env、hook command、monitor command

### 7.9 detect-only / unsupported 组件

| capability | 行为 |
|------------|------|
| `lsp` | `capabilities_status.lsp=detect_only`；文档引导 IDE 场景 |
| `output_styles` / `themes` | ignore 或 CLI P3 |
| `monitors` | P3；需 Monitor tool |
| `apps` | P2 OAuth |
| `channels` | P3 |
| `hooks_openclaw_internal` / Hermes Python | `unsupported` + `migration_hints` |

---

## 8. PluginRuntime — 运行时管理

对标 `MCPRuntime` / `SkillRuntime`：

```python
class PluginRuntime:
    def __init__(
        self,
        config_manager: PluginConfigManager,
        *,
        skill_runtime: SkillRuntime | None = None,
        hook_runtime_factory: Callable[..., HookRuntime] | None = None,
        mcp_runtime: MCPRuntime | None = None,
    ): ...

    async def start(self, project_path: str, session_id: str) -> None:
        """加载全部 enabled plugin 并分发。"""

    def list_all(self) -> list[dict]:
        """UI：id, name, version, enabled, capabilities, status, path"""

    async def toggle(self, plugin_id: str, enabled: bool, scope=...) -> None:
        """写盘 + 增量 reload 子系统。"""

    async def reload(self, plugin_id: str) -> None:
        """单 Plugin 热重载。"""

    async def install(self, source: str, scope=..., **opts) -> PluginManifest: ...

    async def uninstall(self, plugin_id: str, scope=..., purge: bool = False) -> None: ...
```

### 8.1 热重载矩阵

| capability | reload 行为 |
|------------|-------------|
| skills / commands | 移除旧 source → rescan → refresh system prompt |
| agents | 重建 `AgentRegistry` 中该 plugin 条目 |
| hooks | 替换 `HookRegistry` 中该 plugin 段 |
| mcp | `MCPRuntime.apply_config` diff → disconnect 移除的 server |
| settings | revert 旧补丁 → apply 新 `settings.json` |
| bin | 更新 PATH 快照 |
| user_config | 重读 data 目录；不自动弹表单 |
| ui_metadata | 刷新 Plugin 列表缓存 |

### 8.2 状态机

```plaintext
installed → disabled → enabled → loading → ready
                              ↘ error (manifest / MCP connect / skill parse)
```

`error` 状态：Plugin 内 **其他子资源仍可用**（例如 hooks 失败但 skills 成功），UI 展示 per-capability 状态。

---

## 9. 环境变量与路径变量

### 9.1 脚本运行时（Hook command executor 已实现部分）

| 变量 | 含义 | Claude 别名 |
|------|------|-------------|
| `MS_AGENT_PROJECT_DIR` | 项目根 | `CLAUDE_PROJECT_DIR` |
| `MS_AGENT_PLUGIN_ROOT` | 当前 plugin 根 | `CLAUDE_PLUGIN_ROOT` |
| `MS_AGENT_PLUGIN_DATA` | `~/.ms_agent/plugins/data/<plugin-id>/` | — |
| `MS_AGENT_SESSION_ID` | 当前 session | — |

当前实现状态：

- `build_hook_env()` 已支持上述变量；
- **环境变量 allowlist**：command hook 子进程**不**继承完整 `os.environ`；仅传递 `PATH`/`HOME`/`LANG`/`TMPDIR` 等运行所需变量 + 上表 MS-Agent 元数据，避免 `OPENAI_API_KEY` 等父进程密钥泄露给第三方 plugin 脚本；
- `PluginHooksLoader` 已在加载阶段把 `${MS_AGENT_PLUGIN_ROOT}` / `${CLAUDE_PLUGIN_ROOT}` 展开到 command 字符串；
- 执行阶段 `HookRuntime._ctx()` 尚未携带 `plugin_root` / `plugin_data_dir`，因此 `MS_AGENT_PLUGIN_ROOT` / `MS_AGENT_PLUGIN_DATA` 需要由 `PluginLoader` 给 **每个 handler** 标注来源后才能稳定注入；这属于 Phase 0 必做项，不能只在 registry 外层保存 plugin id。

### 9.2 配置/template 展开（Loader 阶段）

在 `tools/mcp.json`、`.mcp.json`、hook `command`、MCP `env` 中展开：

- `${MS_AGENT_PLUGIN_ROOT}` / `${CLAUDE_PLUGIN_ROOT}`
- `${MS_AGENT_PLUGIN_DATA}` / `${CLAUDE_PLUGIN_DATA}`
- `${MS_AGENT_PROJECT_DIR}` / `${CLAUDE_PROJECT_DIR}`
- `${user_config.KEY}` / `${CLAUDE_PLUGIN_OPTION_KEY}`（P1）

### 9.3 待补全

`HookExecutionContext.plugin_data_dir` 当前未由 handler 元数据稳定携带；需在 `PluginLoader` → `HookRegistry` 的 handler 上标注 `plugin_id` / `plugin_root` / `plugin_data_dir`，executor 在执行每个 handler 时生成对应 ctx。建议给 `HookHandlerConfig` 增加只读 metadata（如 `source_plugin_id`, `source_plugin_root`, `source_plugin_data_dir`），避免从 command 字符串反推来源，也避免多个 Plugin hooks merge 后丢失来源。

---

## 10. 与 Command / Permission 的协作

### 10.1 Slash Command 与 Agents

- Plugin **skills** 自动进入 `SkillCommandBridge` 拦截链（`/skill-id`）
- Plugin **commands**（P1）在 `SkillCommandBridge` **之后**注册 interceptor，命名空间 `/plugin-id:cmd`
- Plugin **agents**（P1 list / P2 execute）由 `AgentRegistry` 暴露；不经过 Slash 链，由 `AgentDelegate` 或 UI 子 agent 选择器触发

### 10.2 Permission

Plugin 不改变权限模型：

- MCP tools：`server---tool` 格式进入 whitelist/blacklist
- Agent 发起的 tool/MCP 调用：仍按 `SafetyGuard → PreToolUse → PermissionEnforcer → call_tool → PostToolUse`
- Hook command 脚本自身：由 `HookExecutor` 直接启动，**不经过** `ToolManager.single_call_tool()`，因此不会被 PermissionEnforcer 按 shell 命令逐条确认；只能通过 hook source 默认关闭、安装来源信任、timeout、fail_closed、执行器白名单等机制治理
- Hook 脚本如果只是影响后续 Agent tool 调用（例如返回 `deny` / `updated_args`），后续 tool 调用仍按原权限链处理

### 10.3 Hooks enabled_sources 安全默认

CLI 和 Playground 默认保持 `enabled_sources: [native]`。Playground 可在用户显式确认某个含 hooks 的 Plugin 后开启 `plugin` source，或由受信任的企业 profile 预置开启。文档需警告：开启 plugin hooks = 允许已安装且 enabled 的 Plugin 执行任意 command hook。

---

## 11. 集成点与代码变更

### 11.1 LLMAgent 启动链

```plaintext
LLMAgent.__init__
  → ConfigResolver.resolve()                    # 含 plugins merge
  → PluginRuntime.start() / load_all()          # 新增；产出 skills/hooks/mcp/settings/bin 等贡献
  → build_hook_runtime(plugin_hook_registries)  # 不再自行扫描 plugin 根目录
  → SkillCatalog.load_from_config()             # 含 plugin skill sources
  → MCPRuntime.start() / apply_config()         # 含 plugin mcp servers
  → prepare_tools()
```

实现上可先在 `prepare_tools()` 前 lazy 初始化 `PluginRuntime`，但必须保证：

1. `PluginLoader.load_all()` 在 `build_hook_runtime()` 之前完成，才能注入 plugin hooks；
2. plugin MCP server 在 `MCPRuntime.start()` / `sync_tools()` 前进入 resolved MCP config；
3. plugin skills 在 `SkillCatalog.load_from_config()` 前变成 `SkillSource`；
4. legacy `_discover_plugin_roots()` 与新 `plugins.json` 不双重加载。

### 11.2 建议接线顺序

| 步骤 | 组件 | 变更 |
|------|------|------|
| 1 | `plugins/manifest.py`, `config_manager.py` | 新增 |
| 2 | `plugins/installer.py` | 本地安装 P0 |
| 3 | `plugins/loader.py` | 统一分发；迁移 factory 内 discovery |
| 4 | `skill/catalog.py` | plugin source 元数据 + 优先级 |
| 5 | `config/resolver.py` | `_merge_plugins` |
| 6 | `plugins/runtime.py` | 聚合 API |
| 7 | `mcp/runtime.py` | 消费 plugin 来源 server（本文 Phase 2；对齐 `mcp_runtime_management.md` Phase 3） |
| 8 | WebUI Session | `PluginRuntime` 注入 |

### 11.3 不改动

- `ToolManager` 核心调用链（仅 MCP sync 回调扩展 metadata）
- `PermissionEnforcer` / `SafetyGuard` 规则
- CLI `Config.from_task()` 直读 YAML 路径（Playground 才走 `ConfigResolver`）

可新增但不改变语义的安全增强：在 `PluginInstaller` / `PluginRuntime.toggle()` 层做来源提示、签名 / hash 校验、hook executor 白名单和 UI 风险确认；不要把这些包装成 `PermissionEnforcer` 对 hook subprocess 的逐命令拦截。

---

## 12. API 与 UI 数据模型

### 12.1 REST API（Playground 后端）

以下为新增 Playground 后端接口；当前代码库尚无 `/api/plugins` 路由，需随 `PluginRuntime` 一起落地。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/plugins` | `PluginRuntime.list_all()` |
| POST | `/api/plugins/install` | body: `{ "source": "...", "scope": "global\|project" }` |
| DELETE | `/api/plugins/{id}` | `?purge=true` |
| PATCH | `/api/plugins/{id}` | `{ "enabled": true/false }` |
| POST | `/api/plugins/{id}/reload` | 热重载 |

### 12.2 list_all 响应示例

```json
{
  "plugins": [
    {
      "plugin_id": "commit-helper",
      "name": "commit-helper",
      "version": "1.2.0",
      "description": "Conventional commit assistant",
      "enabled": true,
      "scope": "global",
      "path": "/Users/me/.ms_agent/plugins/commit-helper",
      "capabilities": ["skills", "commands", "agents", "hooks"],
      "status": "ready",
      "capabilities_status": {
        "skills": { "count": 1, "status": "ready" },
        "commands": { "count": 4, "status": "ready" },
        "agents": { "count": 1, "status": "ready" },
        "hooks": { "count": 4, "status": "ready" },
        "mcp": { "count": 0, "status": "skipped" },
        "settings": { "status": "skipped" },
        "bin": { "status": "skipped" },
        "user_config": { "status": "skipped" },
        "lsp": { "status": "detect_only" }
      },
      "source": { "type": "github", "uri": "github://org/commit-helper@v1.2.0" },
      "installed_at": "2026-06-18T10:00:00Z"
    }
  ]
}
```

### 12.3 设置页联动

实验场「智能体设置 → Plugin」与「MCP / Skill / Hooks」并列：

- 安装/卸载/开关 Plugin
- 展开查看 Plugin 内 skills 列表（跳转 Skill 开关页，只读展示 plugin 来源）
- Hooks 总开关仍在上级 `enabled_sources`

---

## 13. 文件结构

```plaintext
ms_agent/plugins/
├── __init__.py
├── types.py
├── manifest.py
├── registry.py
├── config_manager.py
├── installer.py
├── loader.py
└── runtime.py

ms_agent/hooks/loaders/plugin.py    # 保留；由 PluginLoader 调用

tests/plugins/
├── test_manifest.py
├── test_config_manager.py
├── test_installer_local.py
├── test_loader_skills.py
├── test_loader_hooks.py
├── test_loader_mcp.py
└── fixtures/
    ├── hookify/                   # 黄金测例 vendor 快照（附录 D）
    └── sample-plugin/             # 最小 synthetic（开发期）
```

---

## 14. 兼容矩阵

| 来源 | Manifest | skills | commands | agents | hooks | mcp | 其他 |
|------|----------|--------|----------|--------|-------|-----|------|
| Claude Code | `.claude-plugin/` | ✅ | ✅ | ✅ | hooks.json | `.mcp.json` | bin, settings, LSP, monitors |
| Codex | `.codex-plugin/` | ✅ | — | — | hooks.json | `.mcp.json` | apps, assets, interface |
| OpenClaw bundle | 多格式 | ✅ | ✅ | 部分 | 部分 | ✅ | settings, LSP detect |
| Hermes 包 | yaml/config | ✅ | — | — | shell yaml | 独立 MCP | Python plugin ✗ |
| MS-Agent 原生 | `.ms-agent-plugin/` | ✅ | ✅ | ✅ | native | mcp.json | 全 §4.4 |

---

## 15. 分阶段交付与验收

### Phase 0 — Manifest + 本地安装 + Skills + Hooks 迁移（P0）

| 交付项 | 验收 |
|--------|------|
| `PluginManifest.parse` | 多组件 `scan_components()`；空包拒绝；`hookify` fixture |
| `PluginConfigManager` CRUD | global/project merge 单测 |
| `PluginInstaller.install(local)` | 复制到 `~/.ms_agent/plugins/<id>/`；写入 `format` + `manifest_path` |
| `PluginLoader` skills | `skills/` + 根 `SKILL.md` 分发为 `SkillSource`；不要求 commands/agents 执行 |
| `PluginLoader` hooks | 复用已实现 `PluginHooksLoader`，产出 `hook_registries` 注入 `build_hook_runtime()` |
| 迁移 `_discover_plugin_roots` | `build_hook_runtime` 不再自行扫描 plugin 根；legacy `config.plugins[]` 仅兼容且不双加载 |
| Hook env 元数据 | `HookHandlerConfig` 或等价 metadata 可携带 `plugin_id/root/data_dir`；command 执行期能拿到 `MS_AGENT_PLUGIN_ROOT` / `MS_AGENT_PLUGIN_DATA` |
| `PluginRuntime.list_all` / `toggle` | CLI 或单元测试；`capabilities_status` 含 §4.4 全键 |

### Phase 1 — Commands / Agents 列表 + 远程安装 + 扩展组件基础（P1）

| 交付项 | 验收 |
|--------|------|
| `PluginLoader` commands / agents（list） | `hookify`：4 commands + 1 agent 可见；agents 可先不执行 |
| `plugin_data_dir` 扩展使用 | hook 脚本可读 `MS_AGENT_PLUGIN_DATA`，userConfig / 状态文件写入同一 data 目录 |
| `commands/*.md` | `/hookify:help` 或并入 skill slash 可识别 |
| `github://` 安装 | 集成测试 mock git |
| `modelscope://` 安装 | 复用 skill 下载 |
| Playground API §12.1 | UI 可列表/开关 |
| 文档：enabled_sources 需含 `plugin` | 示例 agent.yaml |
| **`PluginFormatDetector`** | 识别 claude / openclaw / hermes / ms-agent |
| **OpenClaw 部分加载** | skills + Claude hooks.json + MCP 可用；handler.ts 标 `unsupported` |
| **Hermes shell in bundle** | `hooks/hermes.yaml` → `HermesShellLoader` |
| `bin/`、`settings.json`、`userConfig`（基础） | 扫描、状态展示、变量展开；PATH / 配置补丁按白名单落地 |

### Phase 2 — MCP capability（优先级 P1，交付 Phase 2；对齐 `mcp_runtime_management.md` Phase 3）

| 交付项 | 验收 |
|--------|------|
| `.mcp.json` + `tools/mcp.json` 解析 | server 出现在 `MCPRuntime.list_servers()` |
| Plugin disable 断开 MCP | 该 plugin 贡献的 server 从 LLM 工具列表消失 |
| 命名冲突前缀 | 单测 |
| 路径变量展开 | node args 含绝对路径 |

### Phase 3 — Agents 执行 + 高级生态桥接（P2）

| 交付项 | 验收 |
|--------|------|
| `agents/*.md` → `AgentDelegate` | 按模板 spawn 子 agent |
| `settings.json`、`userConfig` 高级闭环 | 补丁回滚、敏感配置存储、keychain / credentials 集成 |
| Codex / OpenClaw `HOOK.md` **metadata-only** 导入 | 文档 + UI 提示，不执行 handler.ts |
| OpenClaw `handler.ts` Node 子进程桥（可选） | 仅 side-effect 类 hook；不承诺 PreToolUse 等价 |
| Plugin 签名/校验 | 可选 minisign |

---

## 16. 多生态兼容：OpenClaw 与 Hermes

> 与 [`hooks-design.md`](hooks-design.md) §3.6 / §15 / 附录 B 对齐。本节回答：**OpenClaw bundle 检测难不难？能否与 Hermes 一并兼容？**

### 16.1 结论（先说）

| 能力 | 难度 | 能否并入 P1 | 说明 |
|------|------|-------------|------|
| **格式识别**（Claude / OpenClaw / Hermes / ms-agent） | 低 | ✅ 是 | `PluginFormatDetector`，无新运行时 |
| **子资源复用**（skills、MCP、Claude `hooks.json`） | 低 | ✅ 是 | 已有 Loader 直接吃 |
| **Hermes shell hooks**（包内或全局 config） | 低 | ✅ 是 | `HermesShellLoader` **已实现** |
| **OpenClaw HOOK.md 元数据 + 文档展示** | 低 | ✅ 是 | 解析 frontmatter，UI 列出 |
| **OpenClaw `handler.ts` 原样执行** | 高 | ❌ 否（P2 可选桥接） | TS 进程内 API，事件模型不同 |
| **Hermes Python plugin `register_hook()`** | 高 | ❌ 否 | Hermes 进程内 API |
| **Hermes Gateway hook**（`HOOK.yaml` + `handler.py`） | 中 | ❌ 否（P2 文档） | 仅 Gateway 生命周期 |

**可以一并兼容的部分**：安装/发现/开关/Skills/MCP/Shell hooks —— 与 Claude Plugin 共用 `PluginLoader` 分发链。  
**不应承诺一并兼容的部分**：在 ms-agent 内嵌 OpenClaw Gateway 或 Hermes 的 **进程内 hook 虚拟机**。

### 16.2 为何 OpenClaw 曾被标 P2

OpenClaw 实际有 **两套 hook**，与 ms-agent（对齐 Claude Code）的 hook **不是同一类产品**：

```plaintext
OpenClaw 内部 hook（HOOK.md + handler.ts）
  事件：command:new, gateway:startup, message:received, agent:bootstrap ...
  模型：Gateway 侧效应 / 消息通道 / 会话生命周期
  执行：TypeScript 进程内，handler 接收 OpenClaw event 对象

OpenClaw Typed Plugin Hook（api.on(...)）
  事件：before_tool_call, before_agent_reply, session_end ...
  模型：有序中间件 / 策略门
  执行：TS 进程内 Plugin SDK

ms-agent / Claude Code Canonical Hook
  事件：PreToolUse, PostToolUse, UserPromptSubmit, Stop ...
  模型：Agent 工具管线拦截
  执行：子进程 command + stdin JSON（或 P2 http/prompt）
```

OpenClaw 官方文档也明确：**工具拦截、策略门**应走 Typed Plugin Hook，Internal Hook 适合 `/new` 记日志、gateway 启动跑 `BOOT.md` 等 **粗粒度自动化**——与 ms-agent `PreToolUse` 语义不对等。

因此「OpenClaw 兼容」若理解为 **跑通全部 handler.ts**，难度高且产品边界模糊；若理解为 **识别 bundle + 加载其中 Claude 兼容部分**，难度低，**应与 P1 Plugin 模块一起做**。

### 16.3 OpenClaw bundle：P1 可做什么

**识别特征**（`PluginFormat.OPENCLAW`，优先级低于显式 `plugin.json`）：

| 信号 | 路径 |
|------|------|
| npm hook pack | `package.json` → `"openclaw": { "hooks": ["hooks/foo"] }` 或 `"openclaw.hooks"` |
| HOOK 目录 | `hooks/<name>/HOOK.md` + `handler.ts` |
| MCP | `openclaw.json` → `mcpServers`（或合并进宿主 config 的 MCP 段） |
| Skills | workspace `skills/` 或包内 `skills/` |

**P1 加载策略**（`OpenClawBundleAdapter`）：

```python
def adapt_openclaw(root: Path) -> PluginLoadResult:
    result = PluginLoadResult()
    # 1. skills/ — 同 Claude，SkillCatalog
    # 2. hooks/hooks.json — 若存在，PluginHooksLoader（Claude 社区常双发）
    # 3. openclaw.json mcpServers — 转 tools/mcp.json 语义进 MCPRuntime
    # 4. HOOK.md 目录 — 仅 parse frontmatter → capabilities_status.hooks.openclaw_internal
    #    handler.ts 标记 unsupported，UI 展示「需 OpenClaw Gateway 或导出 shell 版」
    return result
```

**与 OpenClaw 自身行为一致**：OpenClaw 对 Claude `hooks.json` 也是 **detect-only、不执行**；ms-agent 反而 **更兼容**（Claude command hook 可直接跑）。

**P2 可选**（非 P1 承诺）：对 `handler.ts` 提供 **Node 子进程桥** —— 将 Canonical 事件 **近似** 映射为 OpenClaw event JSON，仅建议 side-effect 类 hook（如 command-logger）；**不**用于 PreToolUse 策略门。

### 16.4 Hermes：已有什么、Plugin 层补什么

Hermes 三套 hook（详见 `hooks-design.md` 附录 B）：

| 类型 | ms-agent 现状 | Plugin 包内 |
|------|---------------|-------------|
| **Shell hooks** | ✅ `HermesShellLoader` + `enabled_sources: hermes` 读 `~/.hermes/config.yaml` | P1：包内 `hooks/hermes.yaml` 或 `hooks/config.yaml` 的 `hooks:` 段 → 同一 Loader |
| **Python plugin hook** | ❌ 不执行 | 安装时检测 `register(ctx)` / `pyproject` hermes 段 → `unsupported` + 迁移文档 |
| **Gateway hook** | ❌ 不执行 | 检测 `HOOK.yaml` → 提示仅 Gateway 可用 |

**Hermes 与 Plugin 一并兼容的成本很低**，因为：

1. Shell loader **已落地**（`ms_agent/hooks/loaders/hermes.py`），Plugin 只需多一个发现路径。
2. Hermes shell hook 脚本与 Claude command hook **共用** `HookExecutor` + `ResponseAdapter`（`decision:block` / `action:block` 已归一化）。
3. 不需要 Hermes 运行时即可跑 **包内的 shell 脚本**。

当前 `HermesShellLoader.load_file()` 只接收 `path` + `project_path`，尚未支持 plugin root/data 路径变量展开，也未接收 `enabled_executors`。因此 P1 的包内 Hermes adapter 需要补齐与 `PluginHooksLoader` 等价的能力：展开 `${MS_AGENT_PLUGIN_ROOT}` / `${CLAUDE_PLUGIN_ROOT}` / `${MS_AGENT_PLUGIN_DATA}`，并给 handler 标注 `source_plugin_*` metadata。

**PluginLoader 扩展**：

```python
# hooks/ 目录多格式探测（按优先级，不互斥）
if (root / "hooks" / "hooks.json").is_file():
    merge(PluginHooksLoader...)           # Claude / Codex plugin
if (root / "hooks" / "hermes.yaml").is_file():
    merge(HermesShellLoader.load_file(...))
elif (root / "hooks" / "config.yaml").is_file():
    merge(HermesShellLoader.load_file(...))  # 仅 parse hooks: 段
```

全局 Hermes 配置（`~/.hermes/config.yaml`）**不经过 Plugin 模块**，仍由 `build_hook_runtime` 在 `enabled_sources` 含 `hermes` 时加载——与 Plugin 正交、可叠加。

### 16.5 统一：`PluginFormatDetector`

安装/扫描时自动识别，写入 `PluginManifest.format` 与 `capabilities_status`：

```python
class PluginFormat(str, Enum):
    MS_AGENT = "ms-agent"      # plugin.json + ms_agent 段
    CLAUDE = "claude"          # plugin.json（无 ms_agent）或纯 Claude 布局
    OPENCLAW = "openclaw"      # package.json openclaw.* 或 HOOK pack
    HERMES = "hermes"          # 以 Hermes hooks yaml 为主，无 plugin.json
    MIXED = "mixed"            # 多格式并存（常见：Claude plugin + OpenClaw HOOK pack）
```

`list_all()` 响应增加：

```json
{
  "format": "mixed",
  "compatibility": {
    "skills": "ready",
    "hooks_claude": "ready",
    "hooks_hermes_shell": "ready",
    "hooks_openclaw_internal": "unsupported",
    "hooks_hermes_python": "unsupported",
    "tools_mcp": "ready"
  },
  "migration_hints": [
    "3 OpenClaw internal hooks (handler.ts) skipped — export shell equivalents or run under OpenClaw Gateway"
  ]
}
```

### 16.6 与「一并兼容」的产品表述

对用户可承诺：

- 安装 OpenClaw hook pack / Hermes 技能包时，**Skills、MCP、Claude hooks.json、Hermes shell hooks 自动可用**。
- UI 明确列出 **未加载** 的进程内 hook 及原因，避免静默失败。
- 同一 `plugins.json` 管理 enable/disable，不区分来源框架。

不可承诺（除非远期单独立项 Node/Hermes 嵌入式运行时）：

- OpenClaw `handler.ts` / Typed `api.on()` 零改动运行。
- Hermes Python `ctx.register_hook()` 零改动运行。

### 16.7 实现增量（并入 Phase 1）

| 文件 | 变更 |
|------|------|
| `plugins/format_detector.py` | 新增：Claude / OpenClaw / Hermes 识别 |
| `plugins/adapters/openclaw.py` | 新增：部分加载 + unsupported 汇总 |
| `plugins/adapters/hermes.py` | 新增：包内 yaml hooks 路径 |
| `plugins/loader.py` | 调用各 adapter，合并 `PluginLoadResult` |
| `hooks/factory.py` | 可选：global hermes 与 plugin hermes 去重说明 |

验收：fixture 含 `hooks/hooks.json` + `hooks/hermes.yaml` + `hooks/foo/HOOK.md` 的 mixed 包，安装后 Claude + Hermes shell 生效，OpenClaw internal 出现在 `migration_hints`。

---

## 17. 风险与对策

| 风险 | 对策 |
|------|------|
| 恶意 Plugin hook 执行任意命令 | 默认不启用 `plugin` source；Playground 展示明确风险说明；限制 enabled_executors；timeout / fail_closed（超时 `kill` + `wait` 防僵尸进程）；**hook env allowlist** 防密钥泄露；安装来源校验（tar slip / SHA pin） |
| skill_id 与内置 skill 冲突 | 加载顺序 + UI 标记来源；warning 日志 |
| MCP server 命名冲突 | `plugin.<id>.<name>` 前缀 |
| GitHub 安装供应链 | `@sha` / `?sha=` 可选 pin + `resolved_sha` 落盘；未 pin 时仍记录实际 commit | GPG 签名 / 包 hash 为后续项 |
| 多 manifest 同目录 | 安装时 `AmbiguousPluginManifest`；要求 `--format` | 运行时读锁定 `manifest_path` |
| `--link` 与 Claude 共享目录 | 文档警告；默认 copy 隔离 | 产品默认 copy |
| Plugin 体积过大 | 安装前 size 检查；git shallow clone |
| 热重载竞态 | `PluginRuntime._reload_lock`；与 `MCPRuntime._sync_lock` 同级 |
| 密钥写入 plugin 配置 | 导出时脱敏；复用 MCP `Env` 替换 |

---

## 18. 测试策略

```python
# tests/plugins/test_loader_hooks.py
def test_plugin_hooks_merge_with_native():
    """plugin PreToolUse 与 native hooks 合并；matcher 生效。"""

# tests/plugins/test_installer_local.py
def test_install_idempotent():
    """重复 install 同 version 不重复复制。"""

# tests/plugins/test_runtime_toggle.py
async def test_disable_plugin_removes_skills_from_catalog():
    """toggle enabled=false 后 SkillRuntime.list_all 不可见。"""

# tests/plugins/test_loader_mcp.py
async def test_plugin_mcp_tools_sync():
    """安装带 tools/mcp.json 的 plugin 后 ToolManager 可见 server---tool。"""
```

**E2E 黄金测例**：见 [附录 D — hookify](#附录-d黄金测例--hookify)（官方社区 Plugin，覆盖 manifest / skills / commands / agents / hooks）。

---

## 19. 社区 Plugin 组件全景（调研）

> 来源：Claude Code [Plugins reference](https://code.claude.com/docs/en/plugins-reference)、Codex [Build plugins](https://developers.openai.com/codex/plugins/build)、OpenClaw [Plugin CLI](https://documentation.openclaw.ai/cli/plugins)、Hermes 架构文档与 `hooks-design.md` 附录 B。  
> 目的：避免 F9 只覆盖 skill/hook/mcp 而遗漏社区包中高频出现的其他配置项。

### 19.1 组件总表

| 组件 | 典型路径 / manifest 字段 | Claude | Codex | OpenClaw | Hermes | MS-Agent 策略 | 优先级 |
|------|---------------------------|--------|-------|----------|--------|---------------|--------|
| **Skills** | `skills/*/SKILL.md`、根 `SKILL.md` | ✅ | ✅ | ✅ bundle | ✅ 目录 | → `SkillCatalog` | **P0** |
| **Commands**（legacy） | `commands/*.md` | ✅ | — | ✅ command-skills | — | → Skill 或 `CommandRouter` | **P1** |
| **Agents / Subagents** | `agents/*.md` | ✅ | — | 部分 | — | → `AgentDelegate` / 子 agent 模板（F1.2 扩展） | **P1** |
| **Hooks (shell)** | `hooks/hooks.json` | ✅ | ✅ | 部分 | ✅ yaml | → `HookRegistry` | **P0/P1** |
| **Hooks (prompt/http/agent/mcp_tool)** | hooks.json `type` 字段 | ✅ | 部分 | ✗ | ✗ | P2 Executor（见 hooks-design §17） | P2 |
| **MCP servers** | `.mcp.json`、`mcpServers` | ✅ | ✅ | ✅ | MCP 独立 | → `MCPRuntime` | **P1** |
| **App Connectors** | `.app.json`、`apps` | — | ✅ | — | — | P2 OAuth 后端 + 凭证存储 | P2 |
| **LSP servers** | `.lsp.json`、`lspServers` | ✅ | — | ✅ bundle 默认 | — | P3 或 detect-only（Playground 非 IDE） | P3 |
| **Output styles** | `output-styles/` | ✅ | — | — | — | P3 / ignore（纯 UI） | P3 |
| **Themes** | `themes/`、`experimental.themes` | ✅ | — | — | — | ignore（CLI/TUI 可选） | P3 |
| **Monitors** | `monitors/monitors.json` | ✅ exp | — | — | — | P3 对标 Monitor tool | P3 |
| **bin/** | 可执行文件 | ✅ | — | — | — | P1：注入 `code_executor` PATH 或 document | **P1** |
| **settings.json** | plugin 根 | ✅ | — | ✅ Claude defaults | — | P1：merge 进 project/global settings 子集 | **P1** |
| **scripts/** | 辅助脚本 | 引用 | 引用 | 引用 | 引用 | 不单独加载；随 hook/MCP 路径展开 | — |
| **assets/** | icon/logo/screenshots | — | ✅ `interface.*` | — | — | UI 元数据 only | P1 UI |
| **userConfig** | manifest 字段 | ✅ | — | plugin config | — | P1：安装/启用时表单 → `pluginConfigs` | **P1** |
| **dependencies** | manifest 数组 | ✅ | — | — | — | P1：安装时解析依赖链 | **P1** |
| **channels** | manifest 数组 | ✅ | — | — | — | P3（MCP 消息注入通道） | P3 |
| **defaultEnabled** | manifest bool | ✅ | — | — | — | 读入 `plugins.json` 默认 enabled | P1 |
| **OpenClaw internal hooks** | `HOOK.md`+`handler.ts` | detect | — | ✅ | — | unsupported（§16） | detect |
| **OpenClaw native plugin** | `openclaw.plugin.json`+TS | — | — | ✅ | — | unsupported（进程内 SDK） | detect |
| **Hermes Python plugin** | `register(ctx)` | — | — | — | ✅ | unsupported | detect |
| **Hermes Gateway hook** | `HOOK.yaml`+`handler.py` | — | — | — | ✅ | unsupported | detect |
| **Marketplace** | `marketplace.json` | ✅ | ✅ | ClawHub | — | 安装源，非 plugin 内容（§19.3） | P1 |
| **Rules / CLAUDE.md 片段** | `rules/`、包内 md | 部分 | — | — | — | P2：merge 进 personalization 或 project instruction | P2 |

### 19.2 原设计已覆盖 vs 遗漏

**已覆盖（v0.1 设计层）**：skills、hooks/hooks.json、tools→MCP、commands（P2）、环境变量桥接、`plugins.json` CRUD。代码现状仅 hooks 局部落地；环境变量为 executor 预留，执行期来源 metadata 尚未接通。

**本次调研补充的遗漏项**（按 MS-Agent 价值排序）：

#### A. 高价值 — 建议并入 P1

1. **`.claude-plugin/` / `.codex-plugin/` manifest 路径**  
   社区包几乎不用根目录 `plugin.json`；Detector 必须识别子目录 manifest。

2. **`.mcp.json` 文件名**（非 `tools/mcp.json`）  
   Loader 应同时探测：`.mcp.json`、`tools/mcp.json`、manifest 内联 `mcpServers`。

3. **`agents/` 子 agent 定义**  
   Claude 社区大量 plugin 通过 agents 提供专用 reviewer/planner。  
   MS-Agent 映射：Playground F1.2 子 agent 模板 + `AgentDelegate` / `capabilities` 包装；frontmatter 字段 `model`、`tools`、`disallowedTools`、`skills` 写入 resolved agent config。

4. **`commands/` 遗留 slash**  
   与 `skills/` 统一为 Skill 加载（Claude 2026 已合并语义）；flat `.md` 走 `SkillLoader` 单文件模式或 `CommandRouter`。

5. **`bin/` PATH 注入**  
   Claude：启用 plugin 时把 `bin/` 加入 Bash tool 的 PATH。  
   MS-Agent：`LocalCodeExecutor` / `WorkspaceContext` 扩展 `plugin_bin_paths`；disable 时移除。

6. **`settings.json` 默认配置**  
   Claude 仅支持 `agent`、`subagentStatusLine` 等键；OpenClaw bundle 还支持 Claude `settings.json` 默认值。  
   MS-Agent：merge 到 session/project 的 agent.yaml 补丁（enabled 时 apply，disable 时 revert）。

7. **`userConfig` + `${user_config.*}` / `CLAUDE_PLUGIN_OPTION_*`**  
   启用 plugin 时 UI 表单收集；写入 `~/.ms_agent/plugins/data/<id>/config.json`；展开到 MCP/hook/monitor 命令字符串。

8. **`dependencies` 插件依赖**  
   安装 `formatter` 时自动安装 `secrets-vault@~2.1.0`；`PluginInstaller` 拓扑排序。

9. **根目录单文件 `SKILL.md`**  
   无 `skills/` 时整包即一个 skill（marketplace 安装常见）。

10. **Codex `interface` / `assets/`**  
    Playground Plugin 列表展示 displayName、icon、screenshots；纯 UI，不进入 Runtime。

#### B. 中价值 — P2

11. **`.app.json` App Connectors（Codex）**  
    Slack/GitHub/Notion OAuth 连接器；需 Playground 后端 OAuth 跳转（`mcp_runtime_management.md` Phase 3 认证项）。

12. **Hook 扩展类型**：`prompt`、`http`、`agent`、`mcp_tool`  
    已在 `hooks-design.md` §17；Plugin 内 hooks.json 常见 prompt 型策略 hook。

13. **`rules/` / 包内 instruction 片段**  
    映射到 `PersonalizationInjector` 或 project `.ms-agent/config.yaml` patch。

14. **Skill frontmatter 扩展**（Claude 2026 统一 skill/command）  
    `allowed-tools`、`context: fork`、`agent`、`model`、`paths`、`disable-model-invocation` — 影响 SkillRuntime 与 AgentDelegate 行为。

#### C. 低价值 / 非 Playground 核心 — P3 或 detect-only

15. **`.lsp.json`** — IDE 代码智能；OpenClaw 已支持 bundle 默认，MS-Agent CLI 可 detect + 文档说明。  
16. **`output-styles/`、`themes/`** — 纯终端/UI 呈现。  
17. **`monitors/`** — Claude 后台监视 + 通知；需 Monitor tool 对标。  
18. **`channels`** — MCP 驱动的消息注入通道。  
19. **OpenClaw/Hermes 进程内扩展** — 仅 detect（§16）。

### 19.3 Marketplace 与 Plugin 的边界

社区分发常通过 **marketplace.json**（非 plugin 内容），MS-Agent 安装器需支持但不应混入 `PluginLoader`：

| 文件 | 作用 | MS-Agent 模块 |
|------|------|---------------|
| `marketplace.json` / `.agents/plugins/marketplace.json` | 插件目录、source.path、policy | `PluginInstaller` 索引源 |
| `.claude-plugin/marketplace.json` | Claude 官方/团队 marketplace | 同上 |
| Codex `~/.agents/plugins/marketplace.json` | 个人/仓库 curated list | 同上 |
| OpenClaw ClawHub / `plugins/installs.json` | 安装记录 + registry | 参考 `PluginConfigManager` 设计 |

Marketplace entry 字段：`source`（local/git/url）、`policy.installation`、`policy.authentication`、`category`、`interface.displayName` — 用于 UI，不进入 Agent 运行时。

### 19.4 PluginLoadResult 扩展（修订）

```python
@dataclass(frozen=True)
class PluginHookContribution:
    plugin_id: str
    registry: HookRegistry
    plugin_root: Path
    plugin_data_dir: Path

@dataclass
class PluginLoadResult:
    skill_sources: list[SkillSource]
    hook_registries: list[PluginHookContribution]
    mcp_servers: dict[str, dict]
    command_defs: list[CommandDef]
    agent_defs: list[AgentDef]              # 新增：agents/*.md
    settings_patch: dict[str, Any]          # 新增：settings.json 片段
    bin_paths: list[Path]                   # 新增：bin/
    user_config_schema: dict[str, Any]      # 新增：manifest userConfig
    ui_metadata: dict[str, Any]             # 新增：interface/assets
    unsupported: list[UnsupportedCapability]  # 新增：lsp/themes/monitors/...
```

### 19.5 修订后的分阶段交付（补充）

在 §15 基础上补充分阶段验收，避免把 MCP / agents 执行混入 Phase 1：

| Phase | 交付项 | 验收 |
|-------|--------|------|
| 0 | Manifest 多路径 | `.claude-plugin` / `.codex-plugin` / 根 `plugin.json`；多 manifest 冲突需显式 `--format` |
| 0 | 根 `SKILL.md` 单 skill | 安装后 catalog 可见 |
| 0 | Plugin hooks 迁移 | `PluginLoader` 产出 hook registry，`build_hook_runtime()` 不再自行扫描并双加载 |
| 1 | `commands/*.md` → skill/command | 至少一种路径可用 |
| 1 | `agents/*.md` 解析 | `list_all` 展示；P1 可先不执行 delegate |
| 1 | `bin/` PATH | shell 工具可调用 plugin 内命令 |
| 1 | `userConfig` 表单 + 变量展开 | `${user_config.key}` 在 hook command 中生效 |
| 1 | `dependencies` 安装顺序 | 依赖 plugin 先于主包 install |
| 1 | `compatibility` 完整报告 | §16 + §19 全部组件状态 |
| 1 | **黄金测例 hookify E2E** | 附录 D 中非 MCP 断言通过 |
| 2 | `.mcp.json` + `tools/mcp.json` 双路径 | `example-plugin` / synthetic fixture 单测，server 出现在 `MCPRuntime.list_servers()` |

---

## 附录 D：黄金测例 — hookify

> **选定结论**：MS-Agent Plugin 体系的**最终集成测例**采用 Anthropic 官方社区目录中的 [**hookify**](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/hookify)（`hookify@claude-plugins-official`）。  
> 选型时间：2026-06-18；对照 §19 组件全景与真实社区分发路径。

### D.1 为何选 hookify（而非 demo 包或其它 official plugin）

| 候选 | 来源 | 覆盖组件 | 不选原因 |
|------|------|----------|----------|
| `yasun1/claude-code-plugin-demo` → `my-first-plugin` | 社区 demo | 声称 5 类 | **非标准**：无 `hooks/hooks.json`（仅散落 `.sh`）；MCP 在 `mcp-server/` 而非 `.mcp.json`；agents 用 `AGENT.md` 非 `*.md` |
| `example-plugin` | official | skills + commands + `.mcp.json` | 过薄；无 hooks/agents；MCP 仅为 HTTP 占位 |
| `feature-dev` | official | agents + commands | 无 hooks、无 MCP |
| `security-guidance` | official | hooks（复杂 Python） | 仅 hooks 单组件；依赖多、CI 重 |
| **`hookify`** | **official community** | **manifest + skills + commands + agents + hooks** | ✅ **选用** |

**hookify** 优势：

1. **真实分发路径**：`anthropics/claude-plugins-official` 社区 marketplace，与 Playground「安装社区 Plugin」一致。
2. **标准 Claude 布局**：`.claude-plugin/plugin.json` + 约定目录，非教学用非标结构。
3. **`hooks/hooks.json` 含包装层**（`{"hooks": {...}}`），与 `PluginHooksLoader` 路径一致。
4. **四类 Canonical 事件**：`PreToolUse`、`PostToolUse`、`Stop`、`UserPromptSubmit`。
5. **`${CLAUDE_PLUGIN_ROOT}`** 出现在 command 字符串，可验收路径展开与环境变量桥接。
6. **多组件并存**：同包内 skills / commands / agents / hooks，一次 install 测分发链。
7. **体积适中**：无 LSP/bin/userConfig，CI 可跑；比 `security-guidance` 轻、比 `example-plugin` 全。

**已知不覆盖**（由同仓库 **`example-plugin`** 作 MCP 补充冒烟，非黄金主测例）：

- `.mcp.json` → `example-plugin`（HTTP MCP 占位）
- `bin/`、`settings.json`、`userConfig`、LSP → 后续 synthetic fixture

### D.2 包结构与安装源

```plaintext
anthropics/claude-plugins-official/plugins/hookify/
├── .claude-plugin/
│   └── plugin.json              # name: hookify
├── hooks/
│   ├── hooks.json               # plugin 包装格式 + 4 事件
│   ├── pretooluse.py
│   ├── posttooluse.py
│   ├── stop.py
│   └── userpromptsubmit.py
├── skills/
│   └── writing-rules/
│       └── SKILL.md             # skill_id: writing-hookify-rules
├── commands/
│   ├── hookify.md
│   ├── configure.md
│   ├── help.md
│   └── list.md
├── agents/
│   └── conversation-analyzer.md
├── core/                        # hook 运行时依赖（Python 模块）
├── matchers/
└── examples/                    # 示例 .local.md 规则
```

**安装 URI（测试 / Playground）**：

```text
github://anthropics/claude-plugins-official@main#plugins/hookify
```

或 marketplace 本地路径（开发）：

```text
file:///path/to/claude-plugins-official/plugins/hookify
```

`plugins.json` 记录示例：

```json
{
  "id": "hookify",
  "enabled": true,
  "managed_by": "ms-agent",
  "format": "claude",
  "manifest_path": ".claude-plugin/plugin.json",
  "source": {
    "type": "github",
    "uri": "github://anthropics/claude-plugins-official@main#plugins/hookify",
    "resolved_sha": "<pin-at-install>"
  },
  "path": "~/.ms_agent/plugins/hookify",
  "installed_at": "2026-06-18T12:00:00Z"
}
```

### D.3 组件 → MS-Agent 验收映射

| hookify 组件 | 预期 MS-Agent 行为 | 验收方式 |
|--------------|-------------------|----------|
| `.claude-plugin/plugin.json` | `PluginManifest.parse` → `plugin_id=hookify` | 单元测试 |
| `skills/writing-rules/SKILL.md` | `SkillCatalog` 含 `writing-hookify-rules` | `SkillRuntime.list_all()` |
| `commands/*.md` (×4) | 注册为 slash 或转 skill；`capabilities_status.commands=ready` | `/hookify` 可识别 |
| `agents/conversation-analyzer.md` | `list_all` 展示；`capabilities_status.agents=ready`；P1 可不执行 delegate | metadata 断言 |
| `hooks/hooks.json` | merge 进 `HookRegistry`（`enabled_sources` 含 `plugin`） | registry 含 4 事件 |
| `${CLAUDE_PLUGIN_ROOT}` | 展开为安装绝对路径 | hook command 不含未展开变量 |
| `MS_AGENT_PLUGIN_DATA` | pretooluse.py 可写规则状态目录 | 环境变量单测 |
| `core/`、`matchers/` | 不单独加载；随 Python hook 引用 | 无 assert |
| — 无 `.mcp.json` | `capabilities_status.mcp=skipped` | `list_all` 报告 |

### D.4 E2E 场景（最终测例脚本）

```python
# tests/plugins/test_golden_hookify.py  — 目标文件（实现 Phase 1 后启用）

HOOKIFY_URI = "github://anthropics/claude-plugins-official@main#plugins/hookify"

async def test_golden_hookify_install_and_manifest():
    manifest = await PluginRuntime.install(HOOKIFY_URI, scope="global")
    assert manifest.plugin_id == "hookify"
    assert manifest.format in ("claude", "mixed")
    assert "hooks" in manifest.capabilities

async def test_golden_hookify_skills_loaded():
    runtime = await start_session_with_plugins(["hookify"])
    skills = runtime.skill_runtime.list_all()
    ids = {s["skill_id"] for s in skills}
    assert "writing-hookify-rules" in ids
    assert any(s.get("plugin_id") == "hookify" for s in skills)

async def test_golden_hookify_hooks_registered():
    load_result = PluginLoader.load_all([manifest_for("hookify")], ctx_for_test())
    hr = build_hook_runtime(
        config_with_plugin_source_enabled(),
        session_id="t1",
        plugin_hook_registries=load_result.hook_registries,
    )
    assert not hr.registry.is_empty
    for event in ("PreToolUse", "PostToolUse", "Stop", "UserPromptSubmit"):
        assert event in hr.registry._index

async def test_golden_hookify_pretooluse_runs():
    """安装后执行一次 read_file；pretooluse.py 应被调用（exit 0，不阻断）。"""
    ...

async def test_golden_hookify_slash_command():
    router = build_command_router(skill_catalog=...)
    result = await router.dispatch(parse("/hookify"))
    assert result is not None  # MESSAGE 或 SUBMIT_PROMPT

async def test_golden_hookify_toggle_disable():
    await runtime.toggle("hookify", enabled=False)
    assert "writing-hookify-rules" not in visible_skill_ids()
    assert hook_registry_for_plugin("hookify").is_empty
```

### D.5 Fixture 策略

| 方式 | 路径 | 用途 |
|------|------|------|
| **CI 推荐** | `git sparse-checkout` 仅 `plugins/hookify` | 网络安装集成测 |
| **离线单测** | `tests/plugins/fixtures/hookify/`（vendor 快照，pin commit SHA） | 无网 / 确定性回归 |
| **MCP 补充** | 同仓库 `plugins/example-plugin`（仅 `.mcp.json` 冒烟） | 不并入黄金主流程 |

Vendor 命令（维护者）：

```bash
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/anthropics/claude-plugins-official.git /tmp/cc-plugins
cd /tmp/cc-plugins && git sparse-checkout set plugins/hookify
cp -R plugins/hookify tests/plugins/fixtures/hookify
# 在 fixtures/hookify/VENDOR_SHA 记录 commit SHA
```

### D.6 与 §15 交付的关系

- **Phase 0 完成标准**：`PluginManifest.parse`、skills 加载、plugin hooks registry 注入通过 hookify 本地 fixture；不要求远程安装和 slash command。
- **Phase 1 完成标准**：附录 D.4 中 hookify 非 MCP 场景全绿（含 github 安装、commands、agents list、toggle）。
- **Phase 2 MCP**：另跑 `example-plugin`，不阻塞 hookify 黄金测例。

---

## 附录 A：plugins.json 示例

**~/.ms_agent/plugins.json**

```json
{
  "plugins": [
    {
      "id": "commit-helper",
      "enabled": true,
      "managed_by": "ms-agent",
      "format": "claude",
      "manifest_path": ".claude-plugin/plugin.json",
      "source": {
        "type": "github",
        "uri": "github://org/commit-helper@v1.2.0",
        "resolved_sha": "abc123def456..."
      },
      "path": "/Users/me/.ms_agent/plugins/commit-helper",
      "installed_at": "2026-06-18T10:00:00Z"
    },
    {
      "id": "local-linter",
      "enabled": false,
      "source": {
        "type": "local",
        "uri": "/path/to/local-linter"
      },
      "path": "/Users/me/.ms_agent/plugins/local-linter",
      "installed_at": "2026-06-17T08:00:00Z"
    }
  ]
}
```

**项目级 `<project>/.ms-agent/plugins.json`**：结构相同；同 id 覆盖 global 的 `enabled`。

---

## 附录 B：plugin.json 字段对照（Claude Code / Codex）

| 字段 | Claude | Codex | MS-Agent 处理 |
|------|--------|-------|---------------|
| `name` | ✅ 必填 | ✅ | `plugin_id` |
| `version` | 可选 | ✅ | 升级检测 |
| `description` | ✅ | ✅ | UI |
| `author` / `homepage` / `repository` / `license` / `keywords` | ✅ | ✅ | UI 元数据 |
| `displayName` | ✅ | — | UI（`interface.displayName`） |
| `skills` | 路径 | 路径 | → SkillCatalog |
| `commands` | 路径 | — | → Skill / Command |
| `agents` | 路径 | — | → AgentDef（P1） |
| `hooks` | 路径/inline | 路径/inline | → HookRegistry |
| `mcpServers` | 路径/inline | 路径/inline | → MCPRuntime |
| `apps` | — | 路径 | → AppConnector（P2） |
| `lspServers` | 路径/inline | — | detect-only（P3） |
| `outputStyles` | 路径 | — | ignore P3 |
| `experimental.themes` | 路径 | — | ignore |
| `experimental.monitors` | 路径 | — | P3 |
| `userConfig` | ✅ | — | 启用表单 + `${user_config.*}` |
| `dependencies` | ✅ | — | 安装拓扑 |
| `defaultEnabled` | ✅ | — | plugins.json 默认 |
| `channels` | ✅ | — | P3 |
| `interface` | — | ✅ | UI only |
| `ms_agent.*` | — | — | MS-Agent 扩展 |

Claude 未在 manifest 声明路径时，使用 **约定目录**（§4.1）。Codex 额外约定：无 manifest `hooks` 字段时自动读 `hooks/hooks.json`。

---

## 附录 C：跨文档约定

| 主题 | 约定 |
|------|------|
| 工具名分隔符 | `---`（`permission-design.md` / `hooks-design.md`） |
| MCP server 合并 | `ConfigResolver.resolve_mcp()`（`mcp_runtime_management.md` §5） |
| Skill disabled vs Plugin disabled | Plugin off = 全部子资源 off；Skill off = 仅 prompt 注入 off，`/` 仍可触发 |
| Hook source 开关 | `hooks.enabled_sources` 含 `plugin` 才加载 Plugin hooks |
| 工作空间元数据目录 | `.ms-agent/plugins/`、`plugins.json` 与 `mcp.json` 同级 |
| WebUI 迁移 | 与 MCP §10.1 相同三阶段：并存 → 收敛 |

---

**文档维护**：实现 Phase 0 完成后，在 `hooks-design.md` §15 增加指向本文的链接；`mcp_runtime_management.md` Phase 3 Plugin tools 条目标记为「设计见 plugins-design.md」。
