---
slug: architecture
title: 架构总览
description: MS-Agent 框架架构真值文档——设计原则与理念、运行时核心、工具与安全、会话与记忆、配置体系、核心模块设计与开发指南。
---

# MS-Agent 架构总览

复杂任务需要智能体在多次模型调用、工具执行和人工反馈之间持续推进。本篇从这一执行过程出发，解释 MS-Agent 如何组织运行时、管理上下文与权限，以及如何让 CLI、TUI 和 WebUI 复用同一套 SDK。

本文面向需要定制智能体或集成框架的开发者，描述当前代码中的机制。宏观演进方向见 [架构路线图](./ROADMAP.md)；尚未实现的设计见 [Plugins](./rfcs/plugins.md)、[Hooks 执行器](./rfcs/hooks-executors.md)和 [MCP 运行时 API](./rfcs/mcp-runtime-api.md) 提案。中文与英文文档保持同步。

---

## 目录

1. [MS-Agent 是什么](#1-ms-agent-是什么)
2. [设计原则与理念](#2-设计原则与理念)
3. [整体架构分层](#3-整体架构分层)
4. [运行时核心：LLMAgent 生命周期](#4-运行时核心llmagent-生命周期)
5. [工具调用与安全：双层权限 + Hooks](#5-工具调用与安全双层权限--hooks)
6. [System Prompt 组装](#6-system-prompt-组装)
7. [会话与上下文：SessionLog / ContextAssembler / Memory](#7-会话与上下文sessionlog--contextassembler--memory)
8. [配置体系](#8-配置体系)
9. [核心功能模块设计](#9-核心功能模块设计)
10. [磁盘存储布局](#10-磁盘存储布局)
11. [扩展与开发指南](#11-扩展与开发指南)
12. [术语表](#12-术语表)
- [附录 A：权限与 Shell 安全校验参考](#附录-a权限与-shell-安全校验参考)
- [附录 B：Hooks 协议与事件参考](#附录-bhooks-协议与事件参考)
- [附录 C：MCP 运行时状态机与配置](#附录-cmcp-运行时状态机与配置)
- [附录 D：配置字段参考](#附录-d配置字段参考)

---

## 1. MS-Agent 是什么

MS-Agent 是面向复杂任务的智能体框架。开发者可以组合模型、工具、技能与子智能体，通过自主委派或显式工作流组织任务，并为执行过程加入上下文管理、权限决策和反馈检查。这些围绕模型组织执行的机制共同构成可定制的 **Agent Harness**。

系统围绕三个工程问题展开：

- **如何组织复杂工作**：`LLMAgent` 负责模型与工具的交互，子智能体承担专项任务，`ChainWorkflow` / `DagWorkflow` 表达明确的阶段与依赖。
- **如何延续任务状态**：会话日志保存执行记录，上下文组装器按需压缩模型输入，记忆后端保存需要跨任务复用的信息；Cron 负责计划任务的调度。
- **如何接入不同应用**：CLI、TUI、WebUI 复用 SDK 的执行、配置、项目与会话服务，通过输入与事件接口处理交互差异。MCP、ACP、A2A 和 Agent Hub 连接外部工具、服务与跨框架资源。

研究、代码生成、金融分析和视频创作项目组合使用上述机制；Skill Evolution 则在可评测任务中通过执行反馈与验证集改进技能。应用特性及效果应以对应项目的配置和评测为准。

---

## 2. 设计原则与理念

| 原则 | 解决的问题 | 实现位置 |
| --- | --- | --- |
| **统一 SDK，多端复用** | 界面适配无需重新实现执行循环与数据管理 | `ms_agent/ui/`、`project/`、`config/`、`PermissionHandler` |
| **组合式编排** | 同时支持模型自主委派与明确的业务流程 | `LLMAgent`、`AgentTool`、`ChainWorkflow`、`DagWorkflow` |
| **分层权限控制** | 将操作规则、用户授权与业务扩展分开处理 | `SafetyGuard`、`PermissionEnforcer`、`HookRuntime` |
| **历史与模型上下文分离** | 控制输入长度，同时保留原始会话记录 | `SessionLog`、`ContextAssembler` |
| **明确扩展点** | 自定义工具、回调、技能和插件按接口接入 | `ToolBase`、`callbacks/`、`skill/`、`plugins/` |
| **渐进迁移** | 新旧配置和运行路径在过渡期共存 | `Config.from_task()` / `ConfigResolver`、legacy LLM / Provider 路由 |
| **开放生态** | 复用外部工具、技能与智能体资源 | MCP、ACP / A2A、插件加载器、Agent Hub |

权限规则的覆盖范围取决于工具适配与配置，不能替代操作系统或容器隔离。插件格式兼容指已支持的资源类型与加载规则，不意味着执行任意宿主的插件代码。

---

## 3. 整体架构分层

```{mermaid}
flowchart TB
    entry["交互与服务入口<br/>CLI · TUI · WebUI · ACP / A2A"]
    workflow["任务编排<br/>ChainWorkflow · DagWorkflow · 子智能体"]
    agent["Agent 运行时<br/>模型调用 · 工具执行 · 生命周期回调"]
    context["上下文与状态<br/>SessionLog · ContextAssembler · Memory"]
    tools["工具管线<br/>权限检查 · Hooks · ToolManager"]
    services["共享 SDK 服务<br/>项目 · 会话 · 配置 · 技能 · 插件"]
    ecosystem["外部能力<br/>模型服务 · MCP 工具 · 远端智能体"]
    entry --> agent
    entry --> workflow --> agent
    entry --> services
    agent --> context
    agent --> tools --> ecosystem
    agent --> services
```

入口层将请求转换为 SDK 调用，并把事件转为终端输出或 WebUI 的流式响应。单智能体的执行循环由 `LLMAgent.run_loop()` 管理；工作流与子智能体负责更高层的任务编排。项目、会话与配置由共享服务管理，界面层无需维护第二套存储。

---

## 4. 运行时核心：LLMAgent 生命周期

`LLMAgent.run_loop()` 组织单个智能体的执行生命周期。它先做一系列 `prepare_*` 装配，再进入"生成 → 工具调用 → 持久化"的主循环，直到任务完成或达到轮数上限。

```
run_loop(messages)
├─ 装配阶段
│   ├─ 解析交互模式 / 注册 callbacks
│   ├─ prepare_llm()        # LLM.from_config()（Provider 路由，见 §9.6）
│   ├─ prepare_runtime()
│   ├─ prepare_tools()      # 权限对象 + Plugin 装配 + Hook 运行时 + ToolManager
│   ├─ prepare_skills()     # SkillCatalog / Injector / ToolSet；注入 system content builder
│   ├─ load_memory()        # 记忆后端；unified_memory 时注册 MemoryTool
│   ├─ prepare_rag() / prepare_knowledge_search()
│   └─ _init_session_log()  # SessionLog + ContextAssembler
│
├─ 输入解析      # messages 为空时：交互式读取 / config.prompt.query / 管道 stdin
├─ 恢复历史      # 从 SessionLog 或历史缓存载入
│
├─ 若为新任务（round==0）
│   ├─ create_messages() → messages[0] = _build_system_content()   # §6
│   ├─ on_task_begin() → SessionStart hook
│   ├─ UserPromptSubmit hook（可阻断）
│   ├─ do_rag()
│   └─ SessionLog 写入初始消息
│
└─ while 未停止：
    ├─ context_assembler.assemble()               # 非破坏式重建上下文（§7）
    ├─ maybe_refresh_system_prompt()              # 刷新提示层（§6）
    ├─ condense_memory()                          # 注入长期记忆（§7）
    ├─ try: step()                                # 生成 + 工具调用（§5）
    │     └─ except Cancelled/GeneratorExit: 封存中断轮 → re-raise（§7）
    ├─ SessionLog 写入本轮产出（assistant + tool）
    ├─ 完整 assistant 回复后 add_memory()
    ├─ after_tool_call() → Stop hook + 交互式追加输入
    ├─ 为新输入附加提示/模型变化通知与记忆召回
    ├─ round += 1；写入追加输入；save_history
    └─ 达到轮数限制（含总结轮）→ 停止
        on_task_end() → cleanup_tools()
```

设计要点：

- **集成点而非硬编码**：权限、Hooks、Plugins、Skills、Memory 都在固定的 `prepare_*` 处装配、在固定位置被调用。扩展时应优先复用这些集成点，并检查生命周期和资源清理。
- **持久化紧跟产出**：本轮 assistant/tool 消息在 `after_tool_call`（可能阻塞等待下一条输入）之前就落盘，避免把最后一条回答的保存推迟到下一次输入之后。
- **中断可恢复**：`step()` 外层捕获取消，把中断轮忠实封存为可回放的日志（见 §7）。

---

## 5. 工具调用与安全：双层权限 + Hooks

经 `ToolManager` 调度的工具调用经过 `ToolManager.single_call_tool()` 这一个入口；`parallel_call_tool()` 对一批 tool_calls 并发调用它。判定管线（真实顺序）：

```
single_call_tool(tool_call)
├─ 解析参数；校验 tool_name 在索引内
├─ MCP 可用性检查（server 不可用 → 直接返回 mcp_unavailable）
├─ 【内层】SafetyGuard.check()               # 工具规则校验（附录 A）
│     ├─ deny → 拦截
│     └─ ask  → 按模式消歧（auto/strict/interactive）
├─ 【Hook】PreToolUse                        # 可改写参数 / 决策（§附录 B）
├─ 权限决策融合                              # 合并 hook 决策与外层 PermissionEnforcer
│     └─ PermissionEnforcer.check():
│          blacklist→deny · 强制询问/ask_rules · mode/whitelist · memory · handler.ask()
├─ call_tool()                              # 实际执行（带超时）
└─ 【Hook】PostToolUse                       # 附加上下文挂到返回值
```

**双层权限**是核心设计：

- **内层 `SafetyGuard`（规则校验）**：对 shell 命令做路径级校验，对文件类工具做路径校验。命中拒绝规则的调用会被拦截。直接调用工具实现、外部 MCP 服务内部操作，以及受信任的 Hook 脚本不等同于这条管线的权限覆盖。细节见[附录 A](#附录-a权限与-shell-安全校验参考)。
- **外层 `PermissionEnforcer`（用户意图）**：表达"这个用户/这个会话允许什么"，通过 blacklist / ask_rules / whitelist / 记忆（always-allow）/ 交互确认（`PermissionHandler`）实现。

**权限模式**（`PermissionConfig.mode`，默认 `auto`；`restricted` 归一化为 `interactive`）：

| 模式 | SafetyGuard 的 `ask` | Enforcer | 适用场景 |
|------|---------------------|----------|---------|
| `auto` | 按类别消歧（安全的放行、危险的拒绝） | 黑名单拒绝，ask_rules 仍需确认，其余放行 | 自动执行 |
| `strict` | 一律拒绝 | 黑名单拒绝，ask_rules 仍需确认，其余放行 | 保守处理不确定操作 |
| `interactive` | 保持询问，交给 handler | 完整链（黑名单→询问规则→白名单/记忆→交互确认） | 有人值守 CLI / Web |

**跨界面的权限交互**：内核按"模式 + 是否交互终端"选择 handler——交互终端下选 `CLIPermissionHandler`（弹 `[y/s/a/e/n]`），否则选 `AutoPermissionHandler`。外部 UI 可通过 `set_permission_handler()` 注入自定义实现（TUI 用 `TUIPermissionHandler`，Web 可注入基于 SSE/回传的 handler）。并发工具调用时，交互式询问由按事件循环惰性创建的锁串行化，避免多个确认抢占同一终端。

**Hooks** 在同一管线里提供生态扩展点（`PreToolUse` / `PostToolUse` 等），可改写参数、附加上下文或阻断执行；协议与事件见[附录 B](#附录-bhooks-协议与事件参考)。

---

## 6. System Prompt 组装

`_build_system_content()` 按层构建系统提示，使通用行为、项目约定与运行能力能够独立定制：

1. **基础提示**：显式 `prompt.system` 替换内置基础提示，仅替换这一层。
2. **个性化与项目指令**：启用 `personalization.enabled` 时，读取全局 `SOUL.md`、`AGENTS.md`、`PROFILE.md` 以及项目指令文件。
3. **工作区说明**：提供框架内部目录和会话记录的位置，帮助智能体区分用户文件与运行记录。
4. **记忆使用说明**：注册统一记忆工具后加入。
5. **技能摘要**：由技能注入器与 `SkillRuntime` 根据配置构建。

`prompting/workspace_files.py` 负责文件读取、模板初始化和缓存。Markdown frontmatter 与 HTML 注释不进入提示；空模板不会覆盖旧配置中的有效指令。个性化开关的缺省值为 `false`，随包的通用 `agent.yaml` 显式开启它。专用项目是否启用，以其实际配置为准。

每轮可刷新提示内容。`skills.update_notice=true` 固定的是**技能摘要段**，技能变化通过对话中的通知传递；其他提示层仍可更新，因此不保证整个系统提示始终不变或供应商缓存必然命中。提示文件与模型切换通知分别记录必要的会话状态，支持恢复后继续识别变化。

---

## 7. 会话与上下文：SessionLog / ContextAssembler / Memory

这一层把"历史真相""上下文视图""长期记忆"三件事分开，是框架可持续运行的基础。

- **SessionLog**（`session/session_log.py`）：append-only JSONL，带 `seq` 序号与 `round` 侧车，是历史的唯一真相源。除消息外还记录若干**侧车记录**（均排除出 LLM 上下文，仅供回放/统计）：
  - `metadata`（标题/状态/计数）、`compaction_event`（压缩事件）、`error`（工具/轮次错误）、`permission`（权限决策）、`skill_invocation`（`/skill` 展开前的用户原始输入，便于回放显示原文而非展开后的长 prompt）。
  - **中断轮忠实封存**：一轮被取消时正常的轮边界持久化不会执行，因此在 `step()` 外层捕获取消，把中断轮修成"两端协议都可回放"的记录——保留可解析的 `tool_calls` 并为其补 `is_error` 中断结果、无签名的思考内容降级为仅展示、空段落补占位；所有行标记 `interrupted`（回放可见，重建上下文时过滤）。

- **ContextAssembler**（`session/context_assembler.py`）：每轮（`round>0`）**非破坏式**地从 SessionLog 重建当轮上下文视图。策略管线默认为 `[ToolOutputPruner, SummaryCompactor]`，参数（上下文上限、保留缓冲、保护窗口）来自配置。压缩只改变模型可见的上下文视图，原始日志保留。配置了支持 `flush()` 的记忆后端时，会安排压缩前的记忆写入；这是异步处理，不保证摘要前已完成持久化。

- **Memory**（`memory/`）：`SharedMemoryManager` 按配置实例化记忆后端；启用统一记忆时把 `MemoryTool` 注册进 ToolManager 并注入用法提示。每轮 `condense_memory()` 把长期记忆注入消息。

**两种会话驱动模式**（是重要的架构分型）：

- **A. Agent 自驱**：一个 `run_loop` 跑到底，Agent 自己拥有 SessionLog + ContextAssembler 自动压缩 + 每会话一次的生命周期 hook。CLI 交互模式走此路。
- **B. 外层拥有会话**：外层每轮调用 Agent、自己持久化会话（TUI 即如此：以工作目录为项目、用 `SessionManager` 落盘，支持 `/sessions`、`/resume`、`/new`）。此模式下自动压缩需外层以 `/compact` 等手段补足。

要在外层拥有会话的同时保留"自动压缩 + 单次生命周期"，可走 A 模型 + **异步输入接口**（`input_source` 可 await 队列而非阻塞 stdin，配合 `event_sink` 输出事件），WebUI 的 `SessionRuntime` 使用这一模式，通过 `WebInputSource` 接收后续输入，并将 SDK 事件映射为流式响应。

---

## 8. 配置体系

三类配置共同决定运行行为：

1. **agent.yaml 家族（智能体定义）**：`Config.from_task(dir_or_id)` 读取，`agent/agent.yaml` 为框架默认。字段涵盖 `llm / generation_config / prompt / tools / skills / memory / permission / hooks / session_log / compaction / max_chat_round / output_dir` 等。
2. **全局设置 `~/.ms_agent/settings.json`（全局偏好）**：`ConfigResolver._settings_to_agent_config()` 映射到 agent config（如 `llm.provider → llm.service`、个性化、`output_dir`、`tools` 段等，详见[附录 D](#附录-d配置字段参考)）。
3. **项目补丁 `<work_dir>/.ms_agent/config.yaml`**：交互覆盖（如 `/model`）写入，胜过提交的 YAML，且不改动源文件。

**项目补丁以工作目录为作用域。** 配置文件可以来自共享模板，运行状态仍属于当前项目。

- 写：`/model` 等覆盖写入 `output_dir/.ms_agent/config.yaml`。
- 读/合并：`Agent.__init__`（`agent/base.py`）解析出 `output_dir` 后经 `ConfigResolver._load_project_patch(output_dir)` 合并（覆盖 run 与 tui）。
- `Config.from_task` 不再合并 config 文件目录的补丁——否则跑共享/模板 config 会把该目录的补丁泄漏进每次运行、并把 `.ms_agent/` 散落到模板目录。
- 一句话：**config 文件是"定义/模板"（可只读/共享），项目可变状态（含 `/model` 覆盖、memory、snapshots、sessions）归工作目录**。

完整的五层合并（框架默认 → 全局 settings → 用户 agent.yaml → 项目补丁 → 运行时 dict）由 `ConfigResolver.resolve()` 承担，主要用于外部 Server/UI 组装场景；CLI 主路径只做轻量合并。

---

## 9. 核心功能模块设计

### 9.1 项目 / 会话 / 工作空间（`project/`）

项目组织工作目录与会话，会话存储与用户文件目录分离：

| 类 | 职责 |
|----|------|
| `Project`（frozen） | 项目实体：`id / name / path / instruction / memory_enabled / memory_backend / 时间戳`。`id` 随建法而定：`create`→随机 12 位 hex、`open_folder`→按路径派生的 `project_key`、默认→`_default` |
| `ProjectManager` | 项目 CRUD；两种建项目路径——`create`（随机 id + 可选初始化 workspace，"从零开始"）与 `open_folder`（按路径去重，"使用已有文件夹"） |
| `Session` / `SessionManager` | 会话元数据 CRUD；消息委托给 `SessionLog` |
| `Workspace` | 工作空间文件操作（`list_dir/read_file/write_file/delete/import_path`），`_resolve_safe()` 防路径遍历 |
| `JSONFileStore` | 原子写（tmp + rename）的 JSON 存储 |

在框架内部，TUI 通过 `SessionManager` 亲自持久化会话（会话驱动模式 B，见 §7）；WebUI 已使用 `ProjectManager` / `Workspace` 管理项目与文件，并通过 `SessionManager` 和 `SessionLog` 管理会话。

### 9.2 命令系统（`command/`）

统一的斜杠命令与交互驱动：

- `CommandRouter` 四级级联：`priority`（锁外优先，如 `/stop`）→ `exact` → `prefix` → `interceptor`（Skill / Plugin 桥接）。
- 12 个内置命令：`/stop`、`/new`、`/status`、`/quit`、`/help`、`/version`、`/usage`、`/tools`、`/context`、`/model`、`/config`、`/compact`（各带别名）。
- `CommandResult.type ∈ {MESSAGE, SUBMIT_PROMPT, MUTATE_STATE, QUIT}`，把"命令做了什么"标准化。
- `InteractiveSession` 承担 `>>>` 读取与命令循环；初始 prompt 与多轮输入共享同一 router 实例。
- `SkillCommandBridge`（interceptor）把 `/<skill-id>` 展开为技能提示；展开语义抽成公共函数 `expand_skill()` / `expand_slash_text()`，供其他交互入口复用。

### 9.3 Skills（`skill/`, `config/skills_manager.py`）

技能以标准工具（`skills_list` / `skill_view` / `skill_manage`）暴露，并可注入系统提示。核心设计是**live-tree 发现**：

- 每个 scope 隐式预置一个"活动目录"源——`<global_home>/skills` 与 `<project>/.ms_agent/skills`。把技能目录丢进去即注册，无需改 `skills.json`（心智："**存在=文件系统，状态=disabled 列表**"）。
- `skills.json` 里的相对源锚定到 scope 根（不是进程 cwd）；loader 递归扫描（遇 `SKILL.md` 即视为叶子不再下钻，跳过隐藏目录）；按 identity 去重。
- **会话内热同步**：`SkillCatalog.resync()` 原地重建目录（长生命周期持有者不失效），`SkillRuntime.sync_with_config()` 仅当技能面（清单/元数据/disabled 集）真变才 bump version，驱动系统提示按需刷新。
- `SkillToolSet` 的创建/删除锚到 managed 活动树，删除守卫即树边界（外部/配置声明的源目录只读）。

### 9.4 Plugins（`plugins/`）

兼容 Claude Code `plugin.json` 格式的插件系统，一个插件可同时提供多种子资源：

- `PluginRuntime.start_sync()` 在 `prepare_tools` 阶段启动：解析清单 → 通过 `PluginLoader.load_all()` 装配 → 应用到 config。
- 组件分发：`skills/` → 技能源；MCP servers → `config.tools` + 合并索引（重名加 `plugin.<id>.` 前缀去重）；`hooks/hooks.json` → hook 注册表；`commands/` → 命令；`agents/` → 子 agent 注册表；`bin/` → 可执行路径；`settings` → config 补丁（白名单）；`userConfig` → 插件数据目录。
- 配置分层优先级：`config._merged_plugins`（resolver 产物）> `PluginConfigManager.load_merged()`（`~/.ms_agent/plugins.json` + 项目级）> legacy `config.plugins` 路径列表。
- 运行时操作：`toggle / reload / install / uninstall / get_user_config / set_user_config`。安装源覆盖本地 / tarball / `github://` / `modelscope://` / marketplace 别名。
- 清单检测兼容多生态格式（`.ms-agent-plugin/`、`.claude-plugin/`、`.codex-plugin/` 等），MS-Agent 原生格式在冲突时优先。

未落地的增量能力（如按插件的增量热重载、在线安装 UI、部分安全加固）见 [rfcs/plugins.md](./rfcs/plugins.md)。

插件 Hook 的来源标识与目录由 `HookRegistry.with_plugin_source()` 写入 handler，执行器据此构造上下文。工厂优先消费插件运行时提供的 registry，避免再走旧目录发现分支。

### 9.5 MCP 运行时（`mcp/runtime.py`, `config/mcp_manager.py`）

`MCPRuntime` 是配置驱动的 MCP 生命周期状态机，管理服务器的连接、健康、降级与工具索引同步。CLI 默认走 legacy `MCPClient` 路径；`MCPRuntime` 作为更完整的运行时能力，供外部 Server/UI 注入后启用。状态机、失败分类与配置模型见[附录 C](#附录-cmcp-运行时状态机与配置)；面向 Server 的 API 面见 [rfcs/mcp-runtime-api.md](./rfcs/mcp-runtime-api.md)。

### 9.6 LLM Provider 层（`llm/`）

数据驱动的多供应商接入：

- `ProviderSpec` + `ProviderRegistry`：以声明式规格描述每家供应商（服务名、别名、默认传输协议、凭据解析、模型关键词路由）。
- `CredentialResolver`（config → env → 默认）、`ResponseAdapter`（`Message ⇄ LLMResponse`）、`retry`（错误分类 + 指数退避）、`transport/`（`openai_compat` / `anthropic_messages`）。
- `LLM.from_config()` 保留两条路径：未设置 `use_provider_router` 时，`modelscope/openai/anthropic/dashscope` 使用 legacy 实现，注册表中的其他供应商自动走 Provider 层；设为 `true` 强制使用 Provider 路由，设为 `false` 强制使用 legacy 路径。
- 支持中途中断（`interrupt()`）：消费方放弃一轮时可关闭上游响应流；远端是否立即停止生成取决于供应商。
- 传输协议可按供应商覆盖（如让某供应商打另一 vendor 的兼容端点），并兼顾"思考 + 工具"（Anthropic 协议下回放带签名的思考块）。

新增供应商基本只需在 `spec.py` 增加一条 `ProviderSpec`（必要时加 transport），见 §11。

### 9.7 个性化（`personalization/`）

- `PersonalizationInjector.build()`（无状态纯函数）产出"Custom Instructions / Project Instructions / User Profile"三段，注入系统提示（见 §6）。
- `prompting/workspace_files.py` 管理当前的 `SOUL.md` / `AGENTS.md` / `PROFILE.md` 文件；旧的 `profile.md` 与配置字段仍有兼容读取或迁移逻辑。`PersonalizationSettings` 管理 settings.json 中的相关设置。

### 9.8 记忆（`memory/`）

见 §7。要点：`SharedMemoryManager` 按配置实例化后端；统一记忆把 `MemoryTool` 注册为工具；支持文件与向量两类后端；记忆按项目/工作目录隔离。

### 9.9 协议服务（`acp/`、`a2a/`）

把 ms-agent 既作为**协议服务端**对外提供，也作为**客户端**调用远端 agent：

- **ACP（Agent Client Protocol）**：`MSAgentACPServer` 以 stdio 或 HTTP/SSE 暴露 ms-agent；`MSAgentACPProxy` 做多后端代理；`generate_agent_manifest` 产出发现清单。CLI：`ms-agent acp` / `acp-proxy` / `acp-registry`。
- **A2A（Agent-to-Agent）**：`MSAgentA2AExecutor` 把 A2A 请求桥接到 ms-agent 运行时（服务端）；`A2AClientManager` 通过 HTTP 调用远端 A2A agent（客户端）；`build_agent_card` 产出发现文档（Agent Card）。CLI：`ms-agent a2a` / `a2a-registry`。SDK 依赖惰性导入，未装 `a2a-sdk` 时优雅降级。

两者也以工具形态（`acp_agent_tool` / `a2a_agent_tool`）供 LLMAgent 在会话内调用远端 agent。

### 9.10 Agent Hub（`agent_hub/`）

跨框架的 **agent 工作区管理**：把同一套 agent 资产（指令、技能、记忆等）在不同宿主框架之间定义、合并、转换与同步。

- `WorkspaceSpec` + `FRAMEWORK_REGISTRY`：以声明式规格描述各框架的工作区布局；内置 qoder / qwenpaw / openclaw / hermes / nanobot / openhuman / ms-agent，`register_framework()` 可运行时扩展。
- `convert_workspace()` / `merge_resources()`：在框架之间转换与按段合并资源；配合本地/远端同步、watch 守护、备份与恢复。
- 底层远端传输复用 `modelscope_hub.agent.AgentApi`。CLI：`ms-agent agent`（list / upload / download / convert / status / watch / restore …）。

### 9.11 定时任务（`cron/`）

`CronService` 提供进程级的定时调度：按固定周期或声明式 `jobs.d/*.yaml` 触发 agent 任务，管理执行历史与输出。它既是内置工具（`cron`），也有独立 CLI（`ms-agent cron start/stop/list/create/…`），支持 cron 表达式、固定间隔和单次时间点。调度进程需要持续运行；Cron 任务中的 `cron` 工具不允许再管理计划任务。

---

## 10. 磁盘存储布局

路径由 `ms_agent/project/paths.py` 等存储模块解析。分**全局 home**、**工作/项目目录**、**会话全局存储**三块：

```
# ── 全局 home（~/.ms_agent，或 $MS_AGENT_HOME）─────────────────────────────
~/.ms_agent/
├── settings.json            # 全局设置（llm / personalization …）        ← ConfigResolver
├── SOUL.md / AGENTS.md / PROFILE.md  # 个性化与全局指令（prompting/）
├── mcp.json / skills.json   # 全局 MCP / Skills
├── skills/                  # 全局 skill 活动树（丢目录即注册）           ← SkillCatalog
├── plugins.json + plugins/  # 已安装 plugin 记录 + 安装物 / data
└── projects/                # 【会话全局存储，与工作目录解耦】
    ├── <work-dir-key>/                 # key = 工作目录绝对路径转义（CLI/TUI 零配置）
    │   └── session_<id>.jsonl(+.meta)  # 运行时 SessionLog
    └── <project.id>/                   # 显式项目（ProjectManager）
        └── sessions/<sid>/{session.json, session_<sid>.jsonl}

# ── 工作 / 项目目录（== output_dir）───────────────────────────────────────
<work_dir>/
├── <任意工作产物>            # 产物可落工作目录任意位置
└── .ms_agent/               # 框架内部全部收拢于此
    ├── memory/              # 历史缓存 + 记忆后端
    ├── snapshots/           # 快照 git 仓
    ├── index/ · locks/      # 文件/代码索引、锁
    ├── artifacts/ · subagents/ · tmp/ · search_index/ · web_search/
    ├── AGENTS.md            # 项目私有指令；工作目录根也可有 AGENTS.md
    ├── settings.local.json  # 项目级配置（settings schema）
    ├── config.yaml          # 项目级 agent-schema 覆盖（/model 写入）
    ├── mcp.json / skills.json  # 项目级 MCP / Skills
    └── skills/              # 项目 skill 活动树
# 日志：默认 console-only；MS_AGENT_LOG_FILE 开启 → ~/.ms_agent/logs/
```

**兼容**：旧目录（`<work>/.memory`、`<work>/.ms_agent_snapshots`、`<work>/sessions`、连字符的 `<project>/.ms-agent/*`）保留读兼容 + 前向迁移；`MS_AGENT_HOME` 可重定向全局 home（测试隔离用）。

---

## 11. 扩展与开发指南

| 想做什么 | 怎么做 |
|---------|--------|
| 新增内置命令 | 在 `command/builtin/` 加 `CommandDef` + async handler，并在 `register_builtin_commands()` 注册 |
| 新增 Hook 事件挂点 | 在 `HookRuntime` 加 `run_*`，在 `LLMAgent`/`ToolManager` 语义等价位置调用，并登记进 `HookRegistry.VALID_EVENTS` |
| 新增 LLM 供应商 | 在 `llm/spec.py` 加一条声明式 `ProviderSpec`；必要时加 transport |
| 新增内置工具 | 实现 `ToolBase` 并在配置的 `tools` 段声明；用 `ToolManager.index_extra_tool()` 精准入索引（不重列 MCP） |
| 新增 settings.json 映射字段 | 在 `ConfigResolver._settings_to_agent_config()` 加映射 + 对应用例 |
| 给 Project/Session 加字段 | 在 `project/types.py` 的 dataclass 加带默认值字段；旧 JSON 反序列化用默认值 |
| 接入自定义交互式权限 | 用 `agent.set_permission_handler(...)` 注入实现，并自建 resolve 通道 |
| 持续驱动会话 | 用异步输入/事件接口（`input_source` / `event_sink`）走 Agent 自驱模型（§7） |

回归验证（模块单测）：

```bash
pytest tests/project tests/command tests/config tests/personalization \
       tests/skill tests/permission tests/hooks tests/plugins tests/mcp tests/llm -v
```

---

## 12. 术语表

| 术语 | 含义 |
|------|------|
| 双层权限 | 内层 `SafetyGuard`（工具规则校验）+ 外层 `PermissionEnforcer`（用户意图） |
| Canonical 事件 | Hooks 归一化后的事件类型（对齐 Claude Code / Codex / Cursor） |
| `TOOL_SPLITER='---'` | 工具名分隔：`server---tool`；权限 / Hook matcher 统一格式 |
| Provider 路由 | `LLM.from_config` 按注册表决定走 provider 层还是 legacy 实现 |
| live-tree（活动树） | 隐式的 skill 源目录，"存在即注册"，状态由 disabled 列表管理 |
| 会话驱动模式 A/B | Agent 自驱（自己拥有会话）/ 外层拥有会话 |
| 非破坏式上下文 | 上下文视图按轮从 SessionLog 重建，原始日志始终完整 |

---

## 附录 A：权限与 Shell 安全校验参考

内层 `SafetyGuard` 为工具调度提供规则校验，由 `permission/{safety,shell_validator,path_validator,path_extractors,wrapper_strip,ask_resolver}.py` 实现。

### A.1 SafetyConfig（安全底线配置）

| 字段 | 默认 | 说明 |
|------|------|------|
| `patterns` | `rm -rf /*` / `mkfs *` / `dd if=*` | 直接拒绝的危险命令模式 |
| `sensitive_paths` | `/etc/*`、`/sys/*`、`~/.ssh/*`、`**/.git/**` 等 | 敏感路径 |
| `dangerous_removal_paths` | `*`、`/*`、`/`、`~` | 危险删除目标 |
| `read_policy` | `loose` | 读操作超范围时的宽严策略（`loose` / `strict`） |
| `max_command_chars` | `8192` | 单条命令最大长度 |
| `allowed_directories` / `read_only_directories` | 空 | 允许写 / 只读目录白名单（支持 `${PROJECT_ROOT}` 展开） |

**默认黑名单为空**。`curl / wget / ssh / scp / rsync / nc / netcat` 等网络命令进入默认 `ask_rules`，在各模式下都要求确认；没有交互 handler 时会拒绝，已有匹配的记忆授权可复用。`allow_network: true`（兼容旧字段 `no_default_blacklist`）关闭这组默认询问规则，但不取消用户自定义黑名单和询问规则。这些是 shell 工具的匹配规则，不是对任意程序网络行为的隔离。

### A.2 Shell 路径级校验：五种提取策略 + 36 命令注册表

`build_extractor_registry()` 为每个受支持的 shell 命令登记一个"路径提取器 + 操作类型（read/write/create）+ 可选命令校验器"。提取出的路径再交给 `validate_path` 做范围校验。五种策略：

| 策略 | 命令 | 提取方式 |
|------|------|---------|
| A `filter_out_flags`（27 条） | `cat head tail sort uniq wc cut paste column file stat diff awk strings hexdump od base64 nl sha256sum sha1sum md5sum`（read）、`mkdir touch`（create）、`rm rmdir mv cp`（write） | 保留非 flag 参数，尊重 `--` 分隔符 |
| B `parse_pattern_command` | `grep rg` | 首个非 flag 是搜索模式（跳过），其余为路径；`-e/-f` 显式给模式时全部视为路径 |
| C 特殊跳过 | `sed`（write）、`jq`（read） | 跳过脚本/表达式参数，其余为路径 |
| D 搜索起点收集 | `find` | 收集搜索起点与路径型 flag 值；另有 `-exec` 子命令递归校验、`-delete`/`-fprintf` 等写操作拦截 |
| E 子命令分派 | `git` | 仅对 `git diff --no-index` 提取路径 |
| 特殊 | `cd ls tr` | 各自定制 |

**命令校验器**（除路径校验外的额外拦截）：`mv`/`cp` 带 flag 时拒绝（防 `--target-directory` 绕过）；`find` 的 `-fprintf`/`-fprint`/`-fls` 等写操作要求确认。

### A.3 纵深防御

- **safe-wrapper 剥离**（`wrapper_strip.py`）：剥离 `sudo`、`env`、`nice`、`timeout` 等包装器后再校验真实命令。
- **复合命令 / 重定向 / 进程替换**：拆分 `;`、`&&`、`||`、管道；解析输出重定向（`>`/`>>`）；递归处理进程替换 `<(...)` / `>(...)`、命令替换 `$(...)` 与变量展开。
- **文件类工具**：`write_file / edit_file / read_file / grep / glob` 直接 `validate_path`。

### A.4 权限 YAML 配置示例

```yaml
permission:
  mode: interactive            # auto | strict | interactive(=restricted)
  allow_network: false
  whitelist: []
  blacklist: []                # 用户自定义拒绝规则；默认空
  ask_rules: []                # 追加到默认网络命令询问规则
  safety_rules:
    # 省略危险模式和敏感路径列表以保留默认保护；显式列表会替换默认值。
    allowed_directories: ["${PROJECT_ROOT}"]
    read_only_directories: []
    path_validation:
      read_policy: loose       # loose | strict
      max_command_chars: 8192
```

---

## 附录 B：Hooks 协议与事件参考

Hooks 是生态扩展点，把外部脚本/策略挂进 Agent 与工具的关键时点。实现见 `hooks/`。

### B.1 Canonical 事件

| 事件 | 触发点 | 可阻断 |
|------|--------|--------|
| `SessionStart` | 新任务开始（经 `CallbackToHookBridge.on_task_begin`） | 否 |
| `UserPromptSubmit` | 首轮及多轮用户输入提交时 | 是 |
| `PreToolUse` | 工具执行前（SafetyGuard 之后、权限决策之前） | 是 |
| `PermissionRequest` | interactive 模式且有对应 handler 时 | 是 |
| `PostToolUse` | 工具成功执行后 | 否 |
| `Stop` | 判定停止之前（可阻止停止） | 是 |
| `SubagentStop` | 可被配置加载，但当前不触发 | — |

工具类事件（带 matcher）：`PreToolUse` / `PostToolUse` / `PermissionRequest`。

### B.2 命令执行器子进程协议（`command` executor）

- **输入（stdin）**：事件序列化为 JSON 写入 stdin。常见键：`event`、`session_id`、`project_path`、`cwd`、`hook_event_name`；工具事件另有 `tool_name` / `tool_args`（`tool_input`），`PostToolUse` 有 `tool_result`，`UserPromptSubmit` 有 `prompt`，`Stop` 有 `reason` / `last_assistant_message` 等。环境变量为允许列表 + `MS_AGENT_PROJECT_DIR` / `CLAUDE_PROJECT_DIR` 等。
- **输出（stdout）**：JSON，识别 `decision` / `permission` / `action` / `reason` / `additionalContext` / `updatedArgs`（及 `hookSpecificOutput.permissionDecision` 等嵌套形式）。
- **退出码语义**：`0` → 解析 stdout；`2` → 直接 `deny`（原因取 stderr，不解析 stdout）；其他非零 → `error`（`fail_closed` 时升级为 `deny`）；超时/异常同理。

### B.3 决策映射（ResponseAdapter）

按优先级：`hookSpecificOutput.permissionDecision`（deny/allow/ask）→ `decision`/`permission`（deny·block·reject / allow·approve·permit / ask）→ 顶层 `action`（block/deny）→ 仅 `updatedArgs`（放行 + 改参数）→ 仅 `additionalContext`（放行 + 附加上下文）→ Stop 专属（`continue:false` / `followup_message`）→ 否则 `pass`。附加上下文经 `Message.hook_attachments` 挂载，下轮转为 user 元消息回灌。

### B.4 Matcher 与配置

- **Matcher**：fnmatch 通配（`*`、`?`），支持 `|` 或分隔的多选；工具名统一为 `server---tool`（`TOOL_SPLITER='---'`）。非工具事件忽略 matcher。
- **配置结构**（`config.hooks` 或 `hooks.json`/YAML）：每个事件下是一组 `{matcher, hooks:[{type, command, timeout, failClosed}]}`。元键：`enabled_sources`（默认 `[native]`）、`enabled_executors`（默认 `[command]`）、`fail_closed`、`default_model`。
- **多平台 loader**：`native`（`~/.ms_agent/hooks.yaml`、agent.yaml、项目 `hooks.json`）、`claude`（`.claude/settings.json`）、`cursor`（`.cursor/hooks.json`）、`hermes`（`~/.hermes/config.yaml`）、`plugin`（插件 `hooks/hooks.json`）。各平台事件名归一化到 canonical 集合，按低→高优先级合并。

> 当前仅实现 `command` 执行器；`http` / `prompt` / `agent` 执行器为提案，见 [rfcs/hooks-executors.md](./rfcs/hooks-executors.md)。

---

## 附录 C：MCP 运行时状态机与配置

`MCPRuntime`（`mcp/runtime.py`）是配置驱动的 MCP 生命周期状态机。

### C.1 状态与转移

状态集（`MCPServerStatus`）：`registered / connecting / connected / degraded / error / disabled`。

```
(new, enabled)   → registered
(new, disabled)  → disabled
registered/error → connecting → connected        # 连接成功
connecting       → error                          # 连接失败
connected        → degraded                       # hard 失败，或连续失败 ≥ 3
任意 enabled     → disabled                        # disable_server / apply_config
degraded         → connected                       # 仅经成功重连（record_success 不解除 degraded）
```

`is_callable(server)` 仅当 `status == 'connected'`；`sync_tools()` 只为 connected + enabled 的 server 建索引。

### C.2 失败分类与降级

- 分类（`classify_mcp_failure`）：`transient`（超时 / 502 / 503）、`hard`（连接断开 / 重置 / 拒绝）、`none`（业务/参数错误，不改状态）。
- 阈值：`DEGRADED_FAILURE_THRESHOLD = 3`，`FAILURE_HISTORY_LIMIT = 20`。降级条件：`hard` 或连续失败 ≥ 3，且当前为 `connected`。`record_success` 重置连续失败计数但不解除 `degraded`。

### C.3 公开 API（摘要）

`start / stop`、`enable_server / disable_server`、`reload_server / reconnect_server`、`apply_config`（增删改 diff + 重连 + 同步）、`list_servers / get_server`、`is_callable / unavailable_detail`、`record_failure / record_success`、`bind_tool_manager / sync_tools`。

### C.4 配置模型

- `ResolvedMCPConfig.mcp_servers`：`{name: entry}`；`to_mcp_json()` → `{'mcpServers': ...}`；`enabled_servers()` 过滤 `enabled`。
- 服务器条目连接字段：`enabled / transport / type / command / args / url / env / headers / timeout / include / exclude / source / meta` 等；`source ∈ {global, project, agent_yaml, plugin, session}`。
- 合并（`merge_mcp_layers`）：后层按名覆盖前层，`meta` 深合并，`enabled` 仅在 override 层显式给出时才覆盖。
- `MCPConfigManager`（scope：`global / project / merged`）：全局读 `settings.json` 的 `mcp_servers` 与 `mcp.json`（settings 优先）、项目读 `.ms_agent/mcp.json`；写只落 `global` 或 `project`，项目删除以 `_removed` 掩码而非物理删。

> 面向外部 Server 的 `/api/mcp/*` 与热更新事件持久化等为提案，见 [rfcs/mcp-runtime-api.md](./rfcs/mcp-runtime-api.md)。

---

## 附录 D：配置字段参考

### D.1 agent.yaml 主要字段

`llm`（`service / model / {service}_api_key / {service}_base_url`）、`generation_config`（`temperature / top_k / stream / extra_body`）、`prompt.system`、`tools`、`skills`（`sources / disabled / prompt_injection / update_notice`）、`memory`、`permission`（见附录 A）、`hooks`（见附录 B）、`session_log`、`compaction`、`max_chat_round`、`callbacks`、`output_dir`。

### D.2 settings.json → agent config 映射

`ConfigResolver._settings_to_agent_config()`：

| settings.json | → agent config |
|---------------|----------------|
| `llm.provider` | `llm.service` |
| `llm.model` | `llm.model` |
| `llm.api_key` | `llm.{provider}_api_key`（动态前缀） |
| `llm.base_url` | `llm.{provider}_base_url` |
| `llm.temperature`（且 `temperature_enabled`） | `generation_config.temperature` |
| `llm.max_tokens` | `generation_config.max_tokens` |
| `default_model`（`provider/model` 或 `model`） | `llm.service` / `llm.model` 兜底 |
| `output_dir` | `output_dir` |
| `personalization.{global_instruction, memory_enabled, memory_backend}` | `personalization.*` |
| `tools` | `tools`（`tools.<id>.enabled: false` 可关闭某工具） |
