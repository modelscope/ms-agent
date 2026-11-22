---
slug: rfc-mcp-runtime-api
title: "RFC：MCP 运行时对外 API 与投产"
description: 为 MCPRuntime 补齐面向 Server 的管理 API、旧接口迁移路径，以及失败事件持久化、会话级 override、Plugin-MCP、OAuth 等 Phase 3 收尾。
---

# RFC：MCP 运行时对外 API 与投产

> **状态：Draft（提案）** · 关联现状 [ARCHITECTURE 附录 C](../ARCHITECTURE.md#附录-cmcp-运行时状态机与配置) · ROADMAP 主题 2
>
> 现状：`MCPRuntime` 的状态机、失败分类/降级、公开 API 与 `MCPConfigManager` 配置模型**已实现**（附录 C）。本 RFC 覆盖**尚未落地**的对外 API 面、与现有接口衔接及后续工作。

## 背景与动机

新版 WebUI 已提供 `/api/mcps` 的配置增删改查、按作用域管理和按需连通性探测，底层复用 SDK 配置服务。健康探测会临时连接服务器，不等同于运行中会话的连接状态、失败历史或工具同步状态。

`MCPRuntime` 已实现这些运行时机制，但当前常规入口仍默认使用 `MCPClient`。本提案的目标是把已有配置管理与会话运行时连接起来。下文 `/api/mcp/*` 是候选接口，实施时应优先扩展现有 `/api/mcps`，再决定是否需要新路径。

## 1. 对外 API 面（提案）

| Method | Path | 用途 |
|--------|------|------|
| GET | `/api/mcp/servers` | 合并后的服务器 + 运行时状态 |
| POST | `/api/mcp/servers` | 新建服务器（写 project 作用域） |
| PATCH | `/api/mcp/servers/{name}` | 更新配置 / `enabled` |
| DELETE | `/api/mcp/servers/{name}` | 删除 project 级条目 |
| POST | `/api/mcp/servers/{name}/reload` | 热重载单个服务器 |
| POST | `/api/mcp/import` | 导入 Cursor / Claude 的 `mcp.json` |
| GET | `/api/mcp/status` | 聚合连接健康 |

`GET /api/mcp/servers` 响应形态（示例）：

```json
{
  "servers": [
    {
      "name": "fetch", "enabled": true, "status": "degraded",
      "source": "global", "tool_count": 1, "tools": ["fetch---fetch"],
      "last_error": "...", "last_failure_at": "...", "last_success_at": "...",
      "consecutive_failures": 2,
      "failure_history": [
        {"at": "...", "phase": "call_tool", "tool_name": "fetch", "message": "..."}
      ]
    }
  ]
}
```

UI 展示最近 5 条 `failure_history` + **Reconnect** 动作（映射运行时 `reconnect_server`）。

**配置变更管线（提案）**：`MCPConfigManager` → `ConfigResolver.resolve_mcp()` → `MCPRuntime.apply_config()` → `sync_tools()`。运行时字段取自 `MCPRuntime.list_servers()`。

## 2. 与现有接口的衔接

| 阶段 | 配置管理 | 运行时管理 |
|------|----------|-----------|
| 当前实现 | `/api/mcps`，支持作用域配置与按需探测 | 常规会话默认使用 `MCPClient` |
| 接入目标 | 复用现有配置服务与 API | 在会话中注入 `MCPRuntime`，提供连接状态与重新连接 |
| 后续完善 | 保持既有客户端兼容，按需扩展响应字段 | 失败历史、热重载、会话级覆盖的持久化 |

旧设计中的 `/config/mcp` 不再作为新版 WebUI 的现状或迁移起点。

## 3. Phase 3 收尾（未完成项）

- **失败事件持久化**：`sessions/<id>/mcp_events.jsonl` 落盘失败事件（对齐 SessionLog 侧车思路），供回放与诊断。
- **会话级 override 持久化**：合并逻辑已支持会话级 `enabled` override 参数，但尚未与 `session.json` 持久化打通。
- **Plugin-MCP**：插件 `tools/` 目录声明的 MCP server 注册（装配侧已接，完整生命周期投产待收）。
- **OAuth**：后端处理的鉴权重定向流程。

## 开放问题

- `/api/mcp/*` 的 POST/PATCH/DELETE/import/status 请求/响应 schema 需细化（现仅有列表与 `GET servers` 示例）。
- 会话级 override 与项目/全局配置的优先级在 UI 上如何呈现与解释？
- 失败事件 jsonl 的保留策略（轮转/清理）与 `session_log` 是否共用一套机制？
