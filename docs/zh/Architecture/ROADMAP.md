---
slug: roadmap
title: 架构演进路线
description: MS-Agent 框架的宏观架构演进方向——方向主题、动机与现状，配套 rfcs/ 承载具体提案。
---

# 架构演进路线（ROADMAP）

本文记录 MS-Agent 框架**宏观、架构性**的演进方向：每个"方向主题"给出目标/动机、一句现状、以及关联的提案链接。它是与贡献者协作的骨架，**不**列细粒度任务清单（那属于 issue / RFC）。

- 当前实现见 [ARCHITECTURE](./ARCHITECTURE.md)。
- 尚未落地的提案见 `rfcs/`（[plugins](./rfcs/plugins.md)、[hooks-executors](./rfcs/hooks-executors.md)、[mcp-runtime-api](./rfcs/mcp-runtime-api.md)），每份带状态横幅。

## 维护约定

- **架构落地** → 回写 `ARCHITECTURE.md`，并把本文对应主题的现状更新为"已落地/部分落地"。
- **新提案** → 先在 `rfcs/` 建档（含状态横幅：Draft / Accepted / In Progress / Done / Superseded），再在本文登记为一个方向主题或挂到既有主题下。
- **本文只增删"方向"**，不追踪任务粒度进度；一个方向可以关联 0..N 个 RFC。

---

## 方向主题

### 1. 跨界面的服务契约

- **动机**：CLI、TUI 与 WebUI 已复用 SDK 的执行、权限和会话能力。下一步是稳定事件、错误和会话控制契约，降低第三方界面与自动化系统的接入成本。
- **现状**：WebUI 已通过 FastAPI、`SessionRuntime` 和流式事件适配 SDK；面向外部服务的版本化契约仍需完善。
- **关联**：MCP 运行时与 Plugins 管理提案应复用已有服务，避免新增重复存储与执行逻辑。

### 2. MCP 运行时投产

- **动机**：`MCPRuntime` 已提供完整的连接/健康/降级/工具同步状态机（见 ARCHITECTURE 附录 C），需要把它接到实际入口，替换 legacy `MCPClient` 直连路径，并补齐面向 Server 的管理 API 与失败事件持久化。
- **现状**：运行时能力已就绪；对外 API 面、会话级 override 持久化、失败事件落盘为提案。
- **关联**：[rfcs/mcp-runtime-api.md](./rfcs/mcp-runtime-api.md)。

### 3. Hooks 执行器扩展

- **动机**：当前只实现 `command` 执行器；HTTP / Prompt / Agent 执行器能覆盖"远程策略""轻量 LLM 判定""多步校验"等场景，且配置字段与决策管线已为它们预留。
- **现状**：`http/prompt/agent` 的配置可被解析，但后端未注册；`SubagentStop` 可配置但不触发。
- **关联**：[rfcs/hooks-executors.md](./rfcs/hooks-executors.md)。

### 4. Plugins 生态完善

- **动机**：插件系统已能装配 skills/commands/agents/hooks/mcp/bin/settings/userConfig（见 ARCHITECTURE §9.4）；下一步是把"按插件的增量热重载、在线安装与管理 UI、供应链安全（校验/签名）"补齐，形成完整生态闭环。
- **现状**：装配与基本运行时操作已落地；增量热重载、管理 API/UI、部分安全加固为提案。
- **关联**：[rfcs/plugins.md](./rfcs/plugins.md)。

### 5. 记忆的项目隔离与后端矩阵

- **动机**：记忆需在多项目/多工作目录间清晰隔离，并支持"文件 / 向量"等多后端按需切换，保证长期运行下的可移植与可清理。
- **现状**：记忆已按项目/工作目录隔离、支持文件与向量后端；跨后端一致性与迁移工具仍可打磨。

### 6. LLM Provider 层收敛 legacy

- **动机**：Provider 层已是数据驱动门面（`ProviderSpec` + 路由 + transport），目标是逐步把 legacy 直连实现收敛到注册表，减少双路径维护成本、统一重试/中断/思考块语义。
- **现状**：默认配置下，`modelscope/openai/anthropic/dashscope` 保持 legacy 路径，其他已注册供应商自动走 Provider 层；可用 `use_provider_router` 显式切换。

### 7. 权限校验遗留缺口

- **动机**：安全底线以代码实现为准（见 ARCHITECTURE 附录 A），个别配置项与覆盖面仍有缺口，属小而重要的加固。
- **现状（缺口）**：
  - `safety_rules.dangerous_removal_paths` 的 YAML 配置尚未在校验路径完全生效（当前主要依赖内置默认）。
  - `sensitive_paths` 对 shell 写路径的覆盖仍不完整（文件类工具覆盖较全）。
- **说明**：体量小，作为本主题下的加固条目跟踪，暂不单列 RFC。
