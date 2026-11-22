---
slug: rfc-hooks-executors
title: "RFC：Hooks 执行器扩展（HTTP / Prompt / Agent）"
description: 在既有 command 执行器之外，新增 HTTP / Prompt / Agent 三类 Hook 执行器，及统一路由、SubagentStop 触发与 doctor 工具。
---

# RFC：Hooks 执行器扩展（HTTP / Prompt / Agent）

> **状态：Draft（提案）** · 关联现状 [ARCHITECTURE 附录 B](../ARCHITECTURE.md#附录-bhooks-协议与事件参考) · ROADMAP 主题 3
>
> 现状：Hooks 的事件、协议、决策映射、matcher、多平台 loader **已实现**（附录 B），但**仅 `command` 执行器落地**。`http / prompt / agent` 的配置字段可被解析，但后端未注册；`SubagentStop` 可配置但运行时不触发。

## 背景与动机

`command` 执行器覆盖"子进程策略脚本"场景，但存在局限：远程策略要自备脚本、轻量判定要起进程、多步校验无从表达。三类新执行器补齐这些场景，且**复用同一 `HookResult` 管线与 `ResponseAdapter` 输出契约**（附录 B.2/B.3），对上层语义零新增。

## 1. 统一路由

`HookExecutor` 依据 `hooks.enabled_executors` 并列注册 `command | http | prompt | agent`；未启用的类型在执行时返回 `action='error'`（reason：`Hook type '…' not enabled`）而非静默丢弃，并由 `hooks doctor` 给出告警。全局 YAML 追加：`allowed_http_hook_urls`（`undefined`=不限、`[]`=全禁、否则通配白名单）、`http_hook_allowed_env_vars`、`default_model`（prompt/agent 用）。

## 2. `HttpHookExecutor`（P2）

**用途**：把 Canonical 事件 JSON POST 到 `handler.url`，响应体走同一 `ResponseAdapter`。

```json
{
  "type": "http",
  "url": "https://policy.example/v1/pre-tool",
  "timeout": 10,
  "headers": { "Authorization": "Bearer ${POLICY_TOKEN}" },
  "allowedEnvVars": ["POLICY_TOKEN"]
}
```

**语义**：URL 白名单校验 → header 环境变量插值（`allowed_env_vars` ∩ 全局）→ POST（`Content-Type: application/json`，`max_redirects=0`）→ 2xx 交 `ResponseAdapter`；非 2xx/网络错误 → `error`（`fail_closed` 时 `deny`）。

**安全**：URL 白名单；SSRF 拒绝私网/链路本地地址（走代理/沙箱时豁免）；清洗 header 中的 CR/LF/NUL；禁开放重定向。相比直接 `curl`：统一超时/白名单/SSRF/契约，企业可只放行 URL 而不下发脚本。

## 3. `PromptHookExecutor`（P2）

**用途**：单次 LLM 调用（非完整 agent loop）。把事件 JSON 代入 `$ARGUMENTS` / `${ARGUMENTS}`，要求返回结构化 `{ok: bool, reason?: string}`。

**语义**：`ok:true` → `pass`（**不**自动 `allow`）；`ok:false` → `deny`（Stop 事件下为 `block`）；解析失败 → `error`（除非 `fail_closed`）。

**约束**：不递归触发 `UserPromptSubmit`；默认不注入完整历史；无 ToolManager。Cursor 的 `type: prompt` 可共用本执行器。**开放**：要跳过权限弹窗须显式 `permissionDecision: allow`；后续若注入历史需评估 token 成本。

## 4. `AgentHookExecutor`（P3）

**用途**：短生命周期子 agent（带工具）做多步校验，尤其用于 **Stop** 事件（"任务真的完成了吗"），或昂贵的 `PreToolUse`。

**配置**：`type: agent`、`prompt`、`model`、`max_turns`（默认 20，硬上限 50）、`timeout`。

**语义**：过滤危险工具（`agent_tool` / `plan_mode` …）；`permission_mode=dontAsk`（仅在该 hook 子会话内）；结构化 `{ok,reason}` → `deny`/`pass`；Stop 的 `ok:false` → `block`；超时/无结构化输出 → `error`。

**安全**：受限工具面；禁止再派生子 agent / 编辑 hooks / 开新顶层会话；transcript 路径经允许规则可读。

## 5. 其他

- **`SubagentStop` 运行时触发**：目前可配置但不触发；补 `HookRuntime.run_subagent_stop` 及触发点。
- **`hooks doctor`**：诊断未启用类型、白名单缺失、matcher 失配等。

## 明确不纳入

- Hermes 进程内 Python 插件、OpenClaw TS 模块（`api.on()` 类型化 hook）——超出执行器安全边界；至多做"检测 + 转换建议"。
- Hook 附加内容（`hook_attachments`）在 UI 的专用渲染块（属 UI 侧，非本 RFC）。

## 开放问题

- Prompt/Agent 执行器的默认模型来源（`hooks.default_model` vs 主 LLM）与成本上限如何设定？
- HTTP 执行器在企业代理场景下的 SSRF 豁免边界如何声明？
