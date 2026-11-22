---
slug: rfc-plugins
title: "RFC：Plugins 生态完善"
description: 插件系统的未落地增量——按插件增量热重载、管理 API/UI、Hook 执行上下文完整性、供应链安全与 P2/P3 能力。
---

# RFC：Plugins 生态完善

> **状态：Draft（提案）** · 关联现状 [ARCHITECTURE §9.4](../ARCHITECTURE.md#94-pluginsplugins) · ROADMAP 主题 4
>
> 本 RFC 描述后续增量，并标明已实现的相关基础。插件系统的核心装配（skills/commands/agents/hooks/mcp/bin/settings/userConfig 分发、多格式清单检测、配置分层、`install/uninstall/toggle/reload`）**已实现**，见 ARCHITECTURE §9.4，不在此重复。

## 背景

`PluginRuntime` 已能把一个 Claude 兼容插件的多种子资源装配进运行时。要形成完整生态闭环，还需在"热重载粒度、可管理性、执行上下文完整性、供应链安全"四方面补齐。以下为待建条目。

## 1. 按插件的增量热重载

**现状**：`reload()` 忽略 `plugin_id`，执行整体 `start()` 全量重启。

**提案**：按能力做增量重载，避免一次改动触发全量重扫：

| 能力 | 增量重载行为 |
|------|-------------|
| skills / commands | 移除旧源 → 重扫该插件 → 刷新系统提示 |
| agents | 重建该插件的 AgentRegistry 分段 |
| hooks | 替换该插件的 HookRegistry 分段 |
| mcp | `MCPRuntime.apply_config` diff，仅断开被移除项 |
| settings | 回滚旧补丁 → 应用新补丁 |
| bin | 更新 PATH 快照 |
| user_config | 重读数据，不自动弹表单 |

配套一个更细的插件状态机：`installed → disabled → enabled → loading → ready | error`，支持按能力的部分成功/部分失败 UX。热重载竞态由已有的 `_reload_lock`（+ MCP 同步锁）保护。

## 2. 管理 API 与设置 UI

**现状**：无 `/api/plugins` 路由；`list_all()` 的数据模型已基本齐备（`plugin_id/name/version/enabled/scope/path/capabilities/status/...`）。

**提案（面向外部 Server/UI）**：

| Method | Path | 用途 |
|--------|------|------|
| GET | `/api/plugins` | 列出合并后的插件 + 各能力状态 |
| POST | `/api/plugins/install` | 安装（body 携带 source） |
| DELETE | `/api/plugins/{id}?purge=true` | 卸载（可选清除文件） |
| PATCH | `/api/plugins/{id}` | `{enabled}` 开关 |
| POST | `/api/plugins/{id}/reload` | 重载单插件 |

设置页把 Plugins 与 MCP/Skill/Hooks 并列；插件来源的 skills 只读展示并标注 origin；hook 主开关沿用 `enabled_sources`（默认不含 `plugin`，需用户显式开启并确认风险）。

## 3. 已实现的 Hook 来源上下文

`HookRegistry.with_plugin_source()` 已为 handler 写入 `source_plugin_id`、`source_plugin_root` 与 `source_plugin_data_dir`，执行器通过 `_context_for_handler()` 使用对应上下文。工厂在收到插件运行时提供的 registry 时，不再走旧的目录发现分支。这部分已实现；后续增量重载应保持来源信息与隔离语义，不能将它作为待开发功能重复实现。

## 4. 供应链与配置安全

- 安装包**校验/签名**：`github://` 的 `@sha` 固定已支持并会持久化 `resolved_sha`；进一步支持包级 `sha256` / GPG 校验（当前未实现）。
- 安装前**体积检查**与浅克隆，避免超大插件拖垮环境。
- `userConfig` 敏感字段的**安全存储**（keychain），避免明文落 `data/<id>/config.json`；导出时对敏感值脱敏。

## 5. P2/P3 能力与 detect-only 资源

- `commands` 的 `allowed-tools` frontmatter 影响执行（P2）；在 WebUI 中完善子智能体的选择与参数传递（P3）。
- detect-only 资源（`lsp / themes / monitors / apps / channels`）：当前仅扫描并给出状态，未来补 `migration_hints` 与 UI 呈现。
- 明确**不纳入**：OpenClaw `handler.ts`（TS 运行时）、Hermes 进程内 Python 插件——超出插件装配的安全边界。

## 开放问题

- 增量热重载与"部分失败"状态如何在 UI 上表达（整体 degraded vs 逐能力标注）？
- 插件数据目录是否需要项目级隔离（当前全局 `plugins/data/<id>/`）？
- 供应链校验（sha256/GPG）默认强制还是可选？企业模式是否强制？
