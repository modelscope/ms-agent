# Hooks 系统设计文档

> 参考 Claude Code / Cursor / Codex / Hermes Agent 的 shell hook 协议与社区生态。
>
> 原始产品需求见仓库根目录 `playground_prototype_design.md`（F6 Hooks 系统、F9 Plugins 兼容、智能体设置中的 Hooks 配置）。
>
> 本文档是 Hooks 模块的**完整可执行方案**，涵盖子进程协议、Canonical 事件体系、多平台配置加载、匹配器、执行引擎、与旧 Callback 的桥接、与权限系统的协作、以及 Claude / Cursor / Hermes 三方 shell hook 生态兼容边界。

---

## 目录

- [1. 现状分析](#1-现状分析)
- [2. 总体架构](#2-总体架构)
- [3. 子进程协议](#3-子进程协议)
- [4. 事件体系](#4-事件体系)
- [5. 配置格式](#5-配置格式)
- [6. 匹配器](#6-匹配器)
- [7. HookRegistry — 配置加载与合并](#7-hookregistry--配置加载与合并)
- [8. HookExecutor — 执行引擎（Dispatcher）](#8-hookexecutor--执行引擎dispatcher--command-后端)
- [9. CallbackToHookBridge — 向后兼容桥](#9-callbacktohookbridge--向后兼容桥)
- [10. 与权限系统的协作](#10-与权限系统的协作)
- [11. 集成点与代码变更](#11-集成点与代码变更)
- [12. 文件结构](#12-文件结构)
- [13. 与外部生态的对比](#13-与外部生态的对比)
- [14. 验证方式](#14-验证方式)
- [15. 多平台生态兼容设计](#15-多平台生态兼容设计)
- [16. 分阶段交付与验收](#16-分阶段交付与验收)
- [17. 扩展 Executor：HTTP / Prompt / Agent](#17-扩展-executorhttppromptagent)
- [附录 A：Hook Handler 类型与应用场景](#附录-ahook-handler-类型与应用场景)
- [附录 B：Hermes 三套 Hook 体系与功能关系](#附录-bhermes-三套-hook-体系与功能关系)
- [附录 C：实现待办与跨文档约定](#附录-c实现待办与跨文档约定)

---

## 1. 现状分析

### 1.1 当前 Callback 机制的问题

| 问题 | 说明 |
|------|------|
| **需继承 Python 类** | 用户必须写 `class MyCallback(Callback)` 子类，无法用 Shell/Node 等 |
| **需 `trust_remote_code`** | 加载用户脚本时必须开启 trust，存在安全隐患 |
| **仅 5 个固定方法** | `on_task_begin`、`on_generate_response`、`on_tool_call`、`after_tool_call`、`on_task_end` |
| **无阻断能力** | 所有 Callback 方法返回 `None`，无法拒绝或修改工具调用 |
| **无外部脚本扩展** | 无法从外部注入策略脚本，社区生态无法复用 |

### 1.2 现有 Callback 类盘点

```python
# ms_agent/callbacks/base.py
class Callback:
    async def on_task_begin(self, runtime, messages) -> None
    async def on_generate_response(self, runtime, messages) -> None
    async def on_tool_call(self, runtime, messages) -> None
    async def after_tool_call(self, runtime, messages) -> None
    async def on_task_end(self, runtime, messages) -> None
```

唯一内置实现：`InputCallback` — 在 `after_tool_call` 中等待用户输入，控制多轮对话。

### 1.3 工具管线

`ms_agent/tools/tool_manager.py` 已重写，工具调用统一经 `single_call_tool()`：

- `LLMAgent.parallel_tool_call()` → `ToolManager.parallel_call_tool()` → **N × `single_call_tool()`**
- 权限双层检查已就位：`SafetyGuard`（L296–308）→ `PermissionEnforcer`（L309–315）→ `call_tool()`（L337–343）
- 工具名格式：`{server_name}---{tool_name}`（`TOOL_SPLITER = '---'`），与 Hooks matcher 及 `permission-design.md` 一致

Hooks 模块的 **PreToolUse / PostToolUse 应插入此函数**，而非依赖 `Callback.on_tool_call`（触发时机在 `parallel_tool_call` 之前，无法拦截 `single_call_tool` 内部逻辑）。

### 1.4 设计目标

对齐 `playground_prototype_design.md` F6 / 智能体设置「Hooks：支持 python 和 sh，不需要继承父类」：

1. **语言中立**：支持 Python、Shell、任意可执行文件，无需继承 `Callback`
2. **可阻断**：关键事件（`PreToolUse`、`UserPromptSubmit`、`Stop`）支持策略性阻断与参数改写
3. **社区兼容**：协议对标 Claude Code / Codex / Cursor 的 `stdin/stdout/exit code` 约定；**优先兼容三家的 shell-based third-party hooks**
4. **多源配置**：除 `agent.yaml` 外，可选加载 `.claude/settings.json`、`.cursor/hooks.json`、Hermes shell hooks（`config.yaml`）
5. **向后兼容**：旧 Callback 与 `HookRuntime` 共存，不废弃
6. **工具管线优先**：`PreToolUse` / `PostToolUse` / `PermissionRequest` 嵌入 `ToolManager.single_call_tool()`，与 `SafetyGuard` / `PermissionEnforcer` 同层协作
7. **生命周期精确挂点**：`SessionStart` / `UserPromptSubmit` / `Stop` 在 `LLMAgent` 主循环的**语义等价位置**触发（见 §4.5、§9），**不复用** `on_generate_response` / `on_task_end`
8. **Plugin 联动**：`hooks/hooks.json` 经 `PluginLoader` 转换后并入 `HookRegistry`（F9）

---

## 2. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│  HookLoaders（多平台配置 → Canonical IR）                      │
│  - NativeYamlLoader      agent.yaml 或 ~/.ms_agent/hooks.yaml│
│  - ClaudeSettingsLoader  .claude/settings.json               │
│  - CursorHooksLoader     .cursor/hooks.json                  │
│  - HermesShellLoader     ~/.hermes/config.yaml (hooks: 段)   │
│  - PluginHooksLoader     plugin hooks/hooks.json (F9)        │
├─────────────────────────────────────────────────────────────┤
│  HookRegistry（Canonical 事件 → MatcherGroup 索引）          │
│  - merge(sources...) 按优先级合并                             │
│  - get_handlers(canonical_event, normalized_tool_name)     │
├─────────────────────────────────────────────────────────────┤
│  HookExecutorDispatcher（按 handler.type 路由）                  │
│  - command  → CommandHookExecutor（子进程，§8）                 │
│  - http     → HttpHookExecutor（§17.2）                        │
│  - prompt   → PromptHookExecutor（§17.3）                      │
│  - agent    → AgentHookExecutor（§17.4）                       │
│  统一出口 → ResponseAdapter → HookResult                         │
├─────────────────────────────────────────────────────────────┤
│  ToolNameMapper + PatternMatcher                              │
│  - Bash/Shell/terminal ↔ ms-agent tool 名                     │
│  - fnmatch + | 分隔（与 permission 共用）                      │
├─────────────────────────────────────────────────────────────┤
│  HookRuntime（facade：registry + executor + mapper + adapter）   │
│  - run_pre_tool_use / run_post_tool_use → ToolManager 调用     │
│  - run_session_start → CallbackToHookBridge                    │
│  - run_user_prompt_submit / run_stop → LLMAgent 直接调用       │
├─────────────────────────────────────────────────────────────┤
│  CallbackToHookBridge（仅 SessionStart）                       │
│  UserPromptSubmit / Stop → LLMAgent 直接调 HookRuntime（§9）   │
└─────────────────────────────────────────────────────────────┘
```

**数据流**

```
【工具事件 — 主路径】
LLMAgent.parallel_tool_call()
  └─ ToolManager.parallel_call_tool()
        └─ ToolManager.single_call_tool()
              ├─ 1. SafetyGuard.check()
              ├─ 2. HookRuntime.run_pre_tool_use()   ← PreToolUse
              ├─ 3. PermissionEnforcer.check()     ← hooks pass 时
              ├─ 4. tool_ins.call_tool()
              └─ 5. HookRuntime.run_post_tool_use()  ← PostToolUse

【非工具事件 — LLMAgent 主循环挂点】
run_loop() / step()
  ├─ create_messages() 或 InputCallback 追加 user 后
  │     └─ HookRuntime.run_user_prompt_submit()   ← UserPromptSubmit
  ├─ on_task_begin (round==0)
  │     └─ HookRuntime.run_session_start()        ← SessionStart
  └─ after_tool_call() 判定 should_stop 之前
        └─ HookRuntime.run_stop()                 ← Stop
```

`on_generate_response` **不**映射 `UserPromptSubmit`——它在每轮 LLM 调用前触发，语义是「turn 内 pre-LLM」而非「用户提交 prompt」。`on_task_end` **不**映射 `Stop`——此时主循环已结束，无法再 `block` 停止决策。

`on_tool_call` **不再**作为 PreToolUse 的主触发点——它在 LLM 产出 tool_calls 之后、`parallel_tool_call` 之前触发，时机偏晚且无法改写 `single_call_tool` 内的参数与返回值。PR#906 之后工具类 hook 以 `ToolManager` 为准。

---

## 3. 子进程协议

### 3.1 核心协议

对标 Claude Code 和 Codex 的共同约定，语言中立：

```
stdin  ──→ JSON 事件数据（紧凑格式，一次性写入后关闭 stdin）
stdout ←── JSON 决策数据（可选，仅需返回有意义的字段）
stderr ←── 错误信息或阻断原因文本
exit code:
  0 = 通过（解析 stdout JSON 获取详细决策）
  2 = 阻断（策略性拒绝，stderr 为原因）
  1 / 其他 = 非阻断错误（脚本 bug 不应误拦，记 warning 后继续）
```

### 3.2 为什么 exit 2 专用于阻断

- `exit 1` 是最常见的脚本错误退出码，如果 `exit 1 = 阻断`，那么脚本中的任何 uncaught exception 都会导致工具被拒绝
- `exit 2` 需要用户显式选择，必须有意为之才会触发
- 这是 Claude Code 和 Codex 共同验证过的约定，避免脚本 bug 误拦

### 3.3 stdin 事件数据格式（CanonicalPayload）

最小字段：

```json
{
  "event": "PreToolUse",
  "session_id": "abc123",
  "tool_name": "code_executor---shell_executor",
  "tool_args": {
    "command": "pip install requests"
  }
}
```

启用多平台兼容时，Executor 应附加 `tool_input`（与 `tool_args` 同值）及 `tool_name_claude` / `tool_name_cursor` / `tool_name_hermes` 等别名，详见 [§15.6](#156-stdin-canonicalpayload-格式)。

### 3.4 stdout 决策数据格式

```json
{
  "decision": "deny",
  "reason": "Package installation not allowed in production",
  "additionalContext": "Consider using a requirements.txt instead"
}
```

可选字段（ms-agent **原生 / Canonical** 格式）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `decision` | `"allow"` / `"deny"` / `"block"` | 决策（不提供则默认 `"pass"` 即通过） |
| `reason` | `str` | 阻断/放行的原因 |
| `additionalContext` | `str` | 注入到后续 LLM 上下文的附加信息 |
| `updatedArgs` | `dict` | 修改后的工具参数（仅 PreToolUse） |

### 3.6 外部生态 stdout 格式适配（ResponseAdapter）

执行引擎在解析 stdout 时，除 Canonical 字段外，还应识别以下**社区常见格式**并归一化为 `HookResult`：

| 来源 | 阻断/放行字段示例 | 归一化 `HookResult.action` |
|------|------------------|---------------------------|
| **ms-agent / Codex** | `{"decision": "deny\|allow", ...}` | 直接映射 |
| **Claude Code** | `hookSpecificOutput.permissionDecision: "deny\|allow\|ask"` | → `deny` / `allow` / `ask` |
| **Claude Code** | `{"decision": "approve"}` / `{"decision": "block"}` | → `allow` / `deny` |
| **Cursor** | `{"permission": "deny", "user_message": "..."}` | → `deny` |
| **Hermes shell** | `{"decision": "block", ...}` / `{"action": "block", ...}` | → `deny` |
| **通用** | exit code `2` + stderr 文本 | → `deny` |

参数改写字段映射：

| 来源 | 字段 | Canonical |
|------|------|-----------|
| Claude `hookSpecificOutput.updatedInput` | 工具参数对象 | `updated_args` |
| Cursor `updated_input` | 同上 | `updated_args` |
| ms-agent | `updatedArgs` | `updated_args` |

> **社区兼容要点**：仅 `updated_args`、无 `permissionDecision` / `decision` 时 → `action=pass`（passthrough），只改参数，**不**改变 permission 决策。对齐 Claude `toolHooks.ts` L556–563。

上下文注入字段映射：

| 来源 | 注入字段 | Canonical |
|------|---------|-----------|
| Claude / Cursor | `additional_context` / `agent_message` | `additionalContext` |
| Hermes | `{"context": "..."}` on `pre_llm_call` | `additionalContext`（映射到 `UserPromptSubmit` 或 turn 前注入） |
| Cursor `preToolUse` | `updated_input` | `updatedArgs` |

#### 3.6.1 生态兼容 ≠ 原生执行所有 hook 类型

我们要兼容的是 **Claude Code / Cursor / Hermes /（部分）OpenClaw** 这些框架，但每个框架内部 hook 有**多种实现形态**，按优先级支持能在 ms-agent 里「原样加载、原样跑」。

| 层次 | v1 目标 | 说明 |
|------|---------|------|
| **生态层** | ✅ 兼容 | 识别各平台配置路径、Plugin 目录、Skills、`hooks.json` / `settings.json` |
| **可移植层（shell command）** | ✅ v1 主路径 | 子进程 + stdin/stdout JSON；三方社区 hook **绝大多数**属于此类 |
| **平台原生运行时** | ⏳ v2+ 或适配器 | 需 ms-agent 自己实现对应 **Executor 后端**，不能靠 spawn 脚本完成 |

因此 §3.6 下列类型标为 **v1 非目标**，指的是 **不在 v1 实现其原生执行后端**，而不是「不做这些框架的兼容」：

| 类型 | 所属生态 | 为何不纳入 v1 | v1 仍如何兼容该生态 |
|------|---------|--------------|-------------------|
| Claude **HTTP** hook | Claude Code | v1 仅 `command`；**P2** 原生 `HttpHookExecutor`（§17.2） | v1：loader warning + 可用 command 包装 `curl` |
| Claude **prompt** hook | Claude Code | v1 仅 `command`；**P2** `PromptHookExecutor`（§17.3） | 同上 |
| Claude **agent** hook | Claude Code | v1 仅 `command`；**P3** `AgentHookExecutor`（§17.4） | Stop 验证类场景 P3 补齐 |
| Hermes **Python plugin** hook | Hermes | `ctx.register_hook()` 是 **Hermes 进程内 API**，不是独立脚本 | v1 兼容 **Hermes shell hooks** + **同仓库内的 command 脚本**；Python plugin 需在 Hermes 中运行，或作者提供等价 `.sh`（见 [附录 B](#附录-bhermes-三套-hook-体系与功能关系)） |
| OpenClaw **typed `api.on()`** | OpenClaw | **TypeScript 进程内**中间件 | OpenClaw 对 Claude `hooks.json` 本身也是 detect-only；v1 不 ingest TS 模块 |
| Cursor **`type: prompt`** | Cursor | 同 Claude prompt，需 LLM 后端 | v2；v1 兼容 command hook |

**总结**：兼容框架 = 兼容其 **配置发现、Plugin 打包、shell hook 脚本与阻断语义**；不等于在 ms-agent 内嵌 Claude/Hermes/OpenClaw 的完整 hook **虚拟机**。

#### 3.6.2 扩展 Executor 路线

| 能力 | Executor | 阶段 | 详见 |
|------|----------|------|------|
| `type: command` | `CommandHookExecutor` | **P0** | §8 |
| `type: http` | `HttpHookExecutor` | **P2** | §17.2 |
| `type: prompt` | `PromptHookExecutor` | **P2** | §17.3 |
| `type: agent` | `AgentHookExecutor` | **P3** | §17.4 |
| Hermes plugin 迁移 | 文档 + `hermes-to-shell` | P1 文档 | 附录 B |
| OpenClaw HOOK pack | command 转换或 TS 沙箱 | P3 | §17.6 |

社区 hook 的 **形态分布**（经验值）：command/shell **>80%**；HTTP/prompt/agent 多见于企业集成与官方 partner，v1 用 shell 覆盖主体场景后，再按需求加 Executor 类型。详见 [附录 A](#附录-ahook-handler-类型与应用场景)。

### 3.5 exit code 解析逻辑

```python
if exit_code == 0:
    # 解析 stdout JSON
    if stdout_json.get("decision") == "deny":
        return HookResult(action="deny", reason=stdout_json.get("reason", ""))
    elif stdout_json.get("decision") == "allow":
        return HookResult(action="allow", ...)
    else:
        return HookResult(action="pass")  # 无明确决策 = 通过
elif exit_code == 2:
    return HookResult(action="deny", reason=stderr_text)
else:
    # 非阻断错误：记录 warning，继续（除非 fail_closed / handler.fail_closed 为 true，则视为 deny）
    logger.warning(f"Hook script error (exit {exit_code}): {stderr_text}")
    return HookResult(action="error", reason=stderr_text)
```

> **fail_closed**：全局 `hooks.fail_closed` 或 per-handler `failClosed` 为 `true` 时，超时、命令不存在、exit 1 等非 exit-2 错误在可阻断事件上视为 `deny`（§8.6）。

### 3.7 `deny` / `block` 与事件类型的归一化链

子进程协议层（exit 2、stdout `decision:block`）统一先产出 `HookResult(action="deny")`；**按事件类型**在消费端再映射：

| 阶段 | PreToolUse / UserPromptSubmit / PermissionRequest | Stop |
|------|---------------------------------------------------|------|
| `CommandHookExecutor` / `ResponseAdapter` | `exit 2` → `deny`；`decision:block` → `deny` | 同上 |
| `HookExecutor.execute_all`（可阻断） | 短路时 `action="deny"` | 短路时保留 `action="block"`（若脚本直接返回 `block`） |
| `HookRuntime._run_event` | 原样传递 | `deny` → **`block`**（对齐 Claude「阻止停止并继续」） |
| 消费端 | `deny` 拒绝工具 / prompt | `block` → `append_stop_blocking_feedback()` |

因此社区脚本在 **Stop** 上使用 `exit 2` 或 `{"decision":"block"}` 均可生效；无需脚本感知 ms-agent 的 `block` 与 `deny` 差异。

---

## 4. 事件体系

### 4.1 事件总览

| 事件 | 触发时机 | 可阻断 | 关键字段 |
|------|---------|--------|---------|
| `SessionStart` | `run_loop()` 开始 | 否 | `session_id`, `project_path` |
| `PreToolUse` | 工具调用执行前 | 是（`deny` / `allow`） | `tool_name`, `tool_args` |
| `PostToolUse` | 工具调用完成后 | 否（但可注入 `additionalContext`） | `tool_name`, `tool_args`, `tool_result` |
| `UserPromptSubmit` | **用户消息进入 agent 循环前**（见 §4.5） | 是 | `prompt` |
| `Stop` | **Agent 本轮将结束、尚未退出循环前**（见 §4.5） | 是（`block` = 阻止停止并继续） | `reason`, `last_assistant_message` |
| `PermissionRequest` | 权限请求时（interactive 模式，`resolve_hook_permission_decision` 内） | 是 | `tool_name`, `tool_args` |

**配置可加载、运行时触发待 P2**（loader 已映射入 `VALID_EVENTS`，尚无 `HookRuntime.run_*` 挂点）：

| 事件 | 触发时机 | 可阻断 |
|------|---------|--------|
| `SubagentStop` | 子 agent 任务结束（**P2**） | 否（可注入 context） |

**P2 可选扩展**（主要为 Cursor / Hermes 生态独立事件，见 §15.3）：

| 事件 | 触发时机 | 可阻断 |
|------|---------|--------|
| `ShellBefore` | 仅 shell 类工具执行前 | 是 |
| `FileAfterEdit` | 文件写入/编辑后 | 否（可触发 format） |

### 4.2 事件数据结构

```python
from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass(frozen=True)
class SessionStartEvent:
    session_id: str
    project_path: str = ""
    event: str = field(default="SessionStart", init=False)

@dataclass(frozen=True)
class PreToolUseEvent:
    session_id: str
    tool_name: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    event: str = field(default="PreToolUse", init=False)

@dataclass(frozen=True)
class PostToolUseEvent:
    session_id: str
    tool_name: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    tool_result: str = ""
    event: str = field(default="PostToolUse", init=False)

@dataclass(frozen=True)
class UserPromptSubmitEvent:
    session_id: str
    prompt: str
    event: str = field(default="UserPromptSubmit", init=False)

@dataclass(frozen=True)
class StopEvent:
    session_id: str
    reason: str = ""
    last_assistant_message: str = ""   # 与 Claude Stop hook 输入对齐
    stop_hook_active: bool = False     # 是否处于 Stop hook 反馈后的重入
    event: str = field(default="Stop", init=False)

@dataclass(frozen=True)
class PermissionRequestEvent:
    session_id: str
    tool_name: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    event: str = field(default="PermissionRequest", init=False)
```

### 4.3 HookResult（统一返回信封）

```python
@dataclass(frozen=True)
class HookResult:
    action: str         # "allow" | "deny" | "ask" | "block" | "pass" | "error"
    reason: str = ""
    additional_context: str = ""
    updated_args: dict[str, Any] | None = None
    exit_code: int = 0
    stderr: str = ""
```

- `"pass"` 表示 hook 无明确决策，继续后续 permission 流程
- `"allow"`（PreToolUse）：**建议免交互弹窗**，但仍须过 **规则层校验**（blacklist / ask rule，见 §10.6）；**不**等同跳过整个 PermissionEnforcer
- `"ask"`（PreToolUse）：强制进入 PermissionEnforcer / handler，可携带 hook 的 `reason` 作为 `force_decision` 文案
- `"deny"`（PreToolUse / UserPromptSubmit / PermissionRequest）：直接拒绝，不再询问用户
- `"block"`（**仅 Stop 事件**）：阻止 Agent 停止，继续执行；其他事件上 `block` 在协议层归一为 `deny`
- `"error"`：脚本出错，不阻断流程（除非 `fail_closed`）

### 4.4 事件的可阻断语义

**PreToolUse**（对齐 Claude `resolveHookPermissionDecision`，见 §10.6）：

| Hook 返回 | 行为 |
|-----------|------|
| `deny` | 直接拒绝，不进入 PermissionEnforcer |
| `ask` | 进入 PermissionEnforcer，弹窗文案优先用 hook `reason` |
| `allow` | **跳过「无规则命中」时的 ask 弹窗**；blacklist **仍 deny**；显式 ask rule **仍弹窗** |
| `pass` / `{}` / 无返回 | 完整 PermissionEnforcer 流程（含 ask） |
| `updated_args` 且无 permission 字段 | 仅改参（passthrough），permission 用新参数再匹配 |
| `allow` + `updated_args` | 规则校验与放行均基于改写后参数 |

**UserPromptSubmit:**

| Hook 返回 | 行为 |
|-----------|------|
| `deny` | 拒绝该 prompt，不送入 LLM |
| `pass` / 无返回 | 正常提交 |

**Stop:**

| Hook 返回 | 行为（对齐 Claude `query/stopHooks.ts`） |
|-----------|----------------------------------------|
| `block` / `deny`（exit 2 或 `decision:block`） | 注入 **Stop hook feedback** 元消息，**不**设置 `should_stop`，主循环继续 |
| `pass` / 无返回 | 允许停止（`should_stop` 保持 `True`） |
| `additionalContext` | 写入 `hook_additional_context`（见 §8.4、§9.5） |

> Claude 另有 stdout `continue: false` → `preventContinuation`，语义为**确认结束本轮**（v1 经 `ResponseAdapter` 映射为 `pass`）。Cursor `stop` 的 `followup_message` 对齐 ms-agent 的 `block` + 注入 user 消息。

### 4.5 来源框架中的执行位置（UserPromptSubmit / Stop）

两事件在 Claude Code、Cursor、Hermes 中**均存在**（名称不同），但触发粒度不同：

| Canonical | Claude Code | 触发位置（源码） | Cursor | 触发位置 | Hermes Shell | 触发位置 |
|-----------|-------------|-----------------|--------|---------|--------------|---------|
| `UserPromptSubmit` | `UserPromptSubmit` | `processUserInput.ts`：用户输入进入 query **之前**（`executeUserPromptSubmitHooks`） | `beforeSubmitPrompt` | 用户提交 prompt、送模型**之前** | `pre_llm_call` | 每次 LLM 调用前（**粒度更宽**） |
| `Stop` | `Stop` / `SubagentStop` | `query.ts`：`!needsFollowUp` 时、`handleStopHooks`（一轮结束、无后续 tool） | `stop` | Agent 任务完成时 | `on_session_end` 等（**无完全等价 Stop**） | 会话级 |

**Claude Code — UserPromptSubmit**

```
用户输入 → processUserInput()
  → executeUserPromptSubmitHooks(prompt)     # 在 query 循环之前
  → deny/block → shouldQuery=false，不进入 LLM
  → additionalContext → hook_additional_context 附件
  → 通过后才进入 query 主循环
```

**Claude Code — Stop**

```
query 主循环一轮结束（assistant 无待执行 tool）
  → handleStopHooks() / executeStopHooks()
  → block（exit 2）→ 注入 Stop hook feedback 元 user 消息 → 继续 query（stopHookActive=true）
  → pass → 正常结束
```

**ms-agent 对齐挂点**

| 事件 | ms-agent 挂点 | 不复用 |
|------|--------------|--------|
| `UserPromptSubmit` | ① `run_loop()` 中 `create_messages()` 之后、首步 `step()` 之前；② `InputCallback.after_tool_call` 追加 user 之后、下一轮 `step()` 之前 | ~~`on_generate_response`~~（每轮 LLM 前，非用户提交） |
| `Stop` | `after_tool_call()` 内：判定 `should_stop` **之前**（assistant 无 `tool_calls` 时） | ~~`on_task_end`~~（循环已退出） |
| `SessionStart` | `on_task_begin`（`round==0`） | — |

`CallbackToHookBridge` 仅负责 `SessionStart`；`UserPromptSubmit` / `Stop` 由 `LLMAgent` 直接调用 `HookRuntime`（见 §9）。

---

## 5. 配置格式

### 5.1 YAML 配置结构

配置位于 `agent.yaml` 或独立的 hooks 配置文件中，支持全局和项目两级：

```yaml
hooks:
  PreToolUse:
    - matcher: "file_system---*"
      hooks:
        - type: command
          command: "./hooks/validate-path.py"
          timeout: 30
    - matcher: "code_executor---shell_executor"
      hooks:
        - type: command
          command: "./hooks/check-shell.sh"
          timeout: 10
        # --- P2 扩展 handler（§17）---
        - type: http
          url: "https://policy.corp.example/hooks/pre-tool"
          timeout: 10
          headers:
            Authorization: "Bearer ${POLICY_TOKEN}"
          allowed_env_vars: ["POLICY_TOKEN"]
        - type: prompt
          prompt: |
            Evaluate whether this shell command is safe for production.
            Input: $ARGUMENTS
            Reply JSON only: {"ok": true} or {"ok": false, "reason": "..."}
          model: "qwen-plus"
          timeout: 30

  PostToolUse:
    - matcher: "*"
      hooks:
        - type: command
          command: "./hooks/log-tool-use.py"
          timeout: 5

  SessionStart:
    - hooks:
        - type: command
          command: "./hooks/session-init.sh"

  UserPromptSubmit:
    - hooks:
        - type: command
          command: "./hooks/validate-prompt.py"

  Stop:
    - hooks:
        - type: command
          command: "./hooks/cleanup.sh"
        # --- P3 agent hook（§17.4）---
        - type: agent
          prompt: |
            Verify the agent completed the plan in $ARGUMENTS.
            Read transcript if needed. Return structured ok/reason.
          model: "qwen-plus"
          max_turns: 20
          timeout: 120
```

### 5.2 配置层级

三层嵌套：**事件类型 → MatcherGroup 列表 → Hook 处理器列表**

```python
@dataclass(frozen=True)
class HookHandlerConfig:
    type: str = "command"              # command | http | prompt | agent
    timeout: float = 30.0
    fail_closed: bool = False
    # command
    command: str | None = None
    # http（对齐 Claude HttpHook）
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    allowed_env_vars: tuple[str, ...] = ()   # headers 内 ${VAR} 可解析的白名单
    # prompt / agent（对齐 Claude PromptHook / AgentHook）
    prompt: str | None = None          # 支持 $ARGUMENTS / ${ARGUMENTS} 占位符
    model: str | None = None           # 默认 hooks.default_model 或 fast 模型
    max_turns: int = 20                # 仅 agent；Claude MAX_AGENT_TURNS=50，ms-agent 默认更保守

@dataclass(frozen=True)
class MatcherGroup:
    matcher: str | None                 # 工具名匹配模式（非工具事件为 None）
    hooks: tuple[HookHandlerConfig, ...]
```

### 5.3 配置来源与合并规则

对齐 Playground「全局 + 项目继承」与 F9 Plugin 加载：

| 优先级（低→高，后者追加） | 路径 | Loader |
|--------------------------|------|--------|
| 1 全局原生 | `~/.ms_agent/hooks.yaml` | `NativeYamlLoader`（**需** `hooks.enabled_sources` 含 `native`） |
| 2 全局 Claude | `~/.claude/settings.json` → `hooks` | `ClaudeSettingsLoader`（`enabled_sources` 含 `claude` 时） |
| 3 全局 Cursor | `~/.cursor/hooks.json` | `CursorHooksLoader`（`enabled_sources` 含 `cursor` 时） |
| 4 项目 Claude | `.claude/settings.json` | 同上 |
| 5 项目 Cursor | `.cursor/hooks.json` | 同上 |
| 6 项目原生 | `agent.yaml` → `hooks:` | `HookRegistry.from_dict`（**需** `enabled_sources` 含 `native`） |
| 7 项目目录 | `.ms-agent/hooks.json` | `NativeJsonLoader`（**需** `native`） |
| 8 Plugin | `hooks/hooks.json` | `PluginHooksLoader`（`enabled_sources` 含 `plugin` 时） |
| 9 Hermes（可选） | `~/.hermes/config.yaml` → `hooks:` | `HermesShellLoader`（`enabled_sources` 含 `hermes` 时） |

**合并策略**：

- 按事件类型 **追加**（append），同优先级内保持文件声明顺序
- **执行顺序**：低优先级先执行，高优先级后执行；可阻断事件上首个 `deny` 短路
- **默认**：仅加载 ms-agent 原生配置（`enabled_sources: [native]`）；外部生态需显式开启
- **`agent.yaml` 的 `hooks:` 事件段**与 `~/.ms_agent/hooks.yaml`、`.ms-agent/hooks.json` 同属 **native** 源，需 `enabled_sources` 含 `native` 才会加载

```yaml
hooks:
  enabled_sources: [native]          # 唯一配置键；可选: claude, cursor, hermes, plugin
  enabled_executors: [command]       # P2: http, prompt；P3: agent
  default_model: "qwen-plus"         # prompt/agent 默认模型
  fail_closed: false                 # 脚本崩溃/超时是否阻断（对标 Cursor failClosed）
  # allowed_http_hook_urls: [...]    # P2 HTTP 白名单，见 §17.1
```

> **配置键命名**：统一使用 `enabled_sources`（非 `hooks.enabled`）。所有外部生态加载均受此开关控制；`agent.yaml` 内事件段同属 `native` 源。

**Playground 工作区约定**：项目级 hooks 脚本推荐放在 `.ms-agent/hooks/`，配置放在 `.ms-agent/hooks.json` 或 `agent.yaml`，与 session log、memory 等同属 `.ms-agent/` 命名空间。

### 5.4 匹配器规则

- 仅 **工具事件**（`PreToolUse`、`PostToolUse`、`PermissionRequest`）使用 matcher
- 非工具事件（`SessionStart`、`UserPromptSubmit`、`Stop`）无 matcher，所有 hooks 都触发
- matcher 格式与权限系统一致：`server_name---tool_name`，支持 `*`/`?` 通配符和 `|` 分隔

---

## 6. 匹配器

### 6.1 共享 PatternMatcher

Hooks 和 Permission 模块共用同一个通配符匹配函数，提取到 `ms_agent/utils/pattern_matcher.py`。

> **实现注记（permission 已落地）**：`ms_agent/permission/matcher.py` 中 `PermissionMatcher.match()` 已内联 fnmatch + `|` 逻辑（与下文等价）。P0 实施时**提取**为 `match_pattern()` 并让 `PermissionMatcher` 委托，避免两套实现漂移。Hooks matcher **v1 仅匹配工具名**（`server---tool`），**不**支持 Permission 的 `:content_pattern` 后缀；内容级策略用 PreToolUse 脚本内判断。

```python
import fnmatch

def match_pattern(pattern: str, target: str) -> bool:
    """fnmatch 通配符匹配，支持 | 分隔的多模式。

    Examples:
        match_pattern("file_system---*", "file_system---read_file")  → True
        match_pattern("read_file|write_file", "read_file")           → True
        match_pattern("code_executor---shell_*", "web_search---*")   → False
    """
    for alt in pattern.split('|'):
        alt = alt.strip()
        if alt and fnmatch.fnmatch(target, alt):
            return True
    return False
```

### 6.2 Permission 模块适配

`ms_agent/permission/matcher.py` 中的 `PermissionMatcher.match()` 改为调用 `match_pattern()`，保持接口不变：

```python
from ms_agent.utils.pattern_matcher import match_pattern

class PermissionMatcher:
    def match(self, pattern: str, tool_call: str) -> bool:
        return match_pattern(pattern, tool_call)

    def match_with_content(self, pattern, tool_name, tool_args) -> bool:
        # ... 保持不变，内部 self.match() 已委托到 match_pattern
```

### 6.3 HookRegistry 中的使用

```python
class HookRegistry:
    def get_handlers(self, event_type: str, tool_name: str | None = None) -> list[HookHandlerConfig]:
        groups = self._index.get(event_type, [])
        result = []
        for group in groups:
            if event_type not in cls.TOOL_EVENTS:
                result.extend(group.hooks)
            elif group.matcher is None:
                result.extend(group.hooks)
            elif tool_name is not None and match_pattern(group.matcher, tool_name):
                result.extend(group.hooks)
        return result
```

> **实现注记**：工具事件在 `tool_name is None` 时不匹配任何带 matcher 的组，避免误触发全部 handler。

---

## 7. HookRegistry — 配置加载与合并

### 7.1 类设计

```python
@dataclass(frozen=True)
class HookRegistry:
    _index: dict[str, tuple[MatcherGroup, ...]]

    VALID_EVENTS: ClassVar[frozenset[str]] = frozenset({
        "SessionStart", "PreToolUse", "PostToolUse",
        "UserPromptSubmit", "Stop", "PermissionRequest",
        "SubagentStop",  # 配置可加载；运行时触发见 §4.1（P2）
    })

    TOOL_EVENTS: ClassVar[frozenset[str]] = frozenset({
        "PreToolUse", "PostToolUse", "PermissionRequest",
    })

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HookRegistry: ...

    def merge(self, other: HookRegistry) -> HookRegistry: ...

    def get_handlers(self, event_type: str,
                     tool_name: str | None = None) -> list[HookHandlerConfig]: ...

    @property
    def is_empty(self) -> bool: ...
```

### 7.2 from_dict 解析逻辑

```python
@classmethod
def from_dict(
    cls,
    d: dict[str, Any],
    *,
    enabled_executors: frozenset[str] = frozenset({"command"}),
    source: str = "config",
) -> HookRegistry:
    if not d:
        return cls(_index={})

    index: dict[str, tuple[MatcherGroup, ...]] = {}
    for event_type, groups_raw in d.items():
        if event_type in ("enabled_sources", "enabled_executors", "default_model",
                          "fail_closed", "allowed_http_hook_urls",
                          "http_hook_allowed_env_vars"):
            continue
        if event_type not in cls.VALID_EVENTS:
            logger.warning(f"Unknown hook event type: {event_type}")
            continue
        groups = []
        for g in (groups_raw or []):
            matcher = g.get("matcher") if event_type in cls.TOOL_EVENTS else None
            hooks_raw = g.get("hooks", [])
            handlers = _filter_handlers_by_executor(hooks_raw, enabled_executors, source=source)
            if handlers:
                groups.append(MatcherGroup(matcher=matcher, hooks=handlers))
        if groups:
            index[event_type] = tuple(groups)
    return cls(_index=index)


def _parse_hook_handler(h: dict[str, Any]) -> HookHandlerConfig | None:
    t = h.get("type", "command")
    timeout = float(h.get("timeout", 30.0))
    fail_closed = bool(h.get("failClosed", h.get("fail_closed", False)))
    if t == "command":
        if not h.get("command"):
            return None
        return HookHandlerConfig(type="command", command=h["command"],
                                 timeout=timeout, fail_closed=fail_closed)
    if t == "http":
        if not h.get("url"):
            return None
        return HookHandlerConfig(
            type="http", url=h["url"], headers=dict(h.get("headers") or {}),
            allowed_env_vars=tuple(h.get("allowedEnvVars", h.get("allowed_env_vars", []))),
            timeout=timeout, fail_closed=fail_closed,
        )
    if t in ("prompt", "agent"):
        if not h.get("prompt"):
            return None
        return HookHandlerConfig(
            type=t, prompt=h["prompt"], model=h.get("model"),
            max_turns=int(h.get("maxTurns", h.get("max_turns", 20))),
            timeout=timeout, fail_closed=fail_closed,
        )
    logger.warning(f"Unknown hook handler type: {t}")
    return None
```

### 7.3 merge 合并逻辑

```python
def merge(self, other: HookRegistry) -> HookRegistry:
    """合并两个 registry（全局 + 项目），同事件类型下 append。"""
    merged: dict[str, tuple[MatcherGroup, ...]] = {}
    all_events = set(self._index) | set(other._index)
    for event in all_events:
        self_groups = self._index.get(event, ())
        other_groups = other._index.get(event, ())
        merged[event] = self_groups + other_groups
    return HookRegistry(_index=merged)
```

---

## 8. HookExecutor — 执行引擎（Dispatcher + Command 后端）

### 8.1 类设计（Dispatcher）

`HookExecutor` 为**调度门面**，按 `HookHandlerConfig.type` 路由到各后端；所有后端统一返回 `HookResult`，stdout/HTTP body 均经 `ResponseAdapter`（§3.6）。

```python
class HookExecutor:
    def __init__(
        self,
        working_dir: str | None = None,
        *,
        command: CommandHookExecutor,
        http: HttpHookExecutor | None = None,      # P2
        prompt: PromptHookExecutor | None = None,  # P2
        agent: AgentHookExecutor | None = None,    # P3
        response_adapter: ResponseAdapter,
    ) -> None: ...

    async def execute(self, handler: HookHandlerConfig,
                      event_data: dict[str, Any],
                      ctx: HookExecutionContext) -> HookResult:
        backend = self._backends.get(handler.type)
        if backend is None:
            return HookResult(action="error",
                              reason=f"Hook type '{handler.type}' not enabled")
        return await backend.execute(handler, event_data, ctx)

@dataclass
class HookExecutionContext:
    """prompt/agent 后端需要 session 上下文；command/http 可选。"""
    session_id: str
    project_path: str
    llm: LLM | None = None              # 当前 session LLM（prompt/agent）
    messages: list[Message] | None = None  # agent hook 可读历史
    abort_signal: asyncio.Event | None = None
    tool_manager: ToolManager | None = None  # agent hook 受限工具集
```

P0 仅注册 `command`；P2 起按 `hooks.enabled_executors: [command, http, prompt]` 启用扩展后端。

### 8.2 CommandHookExecutor — 子进程执行

```python
async def execute(self, handler: HookHandlerConfig,
                  event_data: dict[str, Any]) -> HookResult:
    stdin_data = json.dumps(event_data, ensure_ascii=False).encode("utf-8")

    try:
        proc = await asyncio.create_subprocess_exec(
            *shlex.split(handler.command),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._working_dir,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin_data),
            timeout=handler.timeout,
        )
    except asyncio.TimeoutError:
        # 超时：非阻断错误
        proc.kill()
        return HookResult(action="error", reason=f"Hook timed out after {handler.timeout}s",
                          exit_code=-1)
    except FileNotFoundError:
        return HookResult(action="error", reason=f"Hook command not found: {handler.command}",
                          exit_code=-1)
    except Exception as e:
        return HookResult(action="error", reason=str(e), exit_code=-1)

    exit_code = proc.returncode or 0
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    stdout_text = stdout.decode("utf-8", errors="replace").strip()

    # exit 2 → 策略性阻断
    if exit_code == 2:
        return HookResult(action="deny", reason=stderr_text or "Blocked by hook",
                          exit_code=exit_code, stderr=stderr_text)

    # exit 非 0 且非 2 → 非阻断错误
    if exit_code != 0:
        logger.warning(f"Hook '{handler.command}' exited {exit_code}: {stderr_text}")
        return HookResult(action="error", reason=stderr_text, exit_code=exit_code,
                          stderr=stderr_text)

    # exit 0 → 经 ResponseAdapter 解析 stdout（§3.6），勿在此重复解析
    return self._response_adapter.parse(stdout_text, exit_code, stderr_text, event_data.get("event"))
```

### 8.3 execute_all — 批量执行与合并

对齐 Claude `executeHooks`（`hooks.ts`）：多个 handler **顺序执行**（v1；Claude 为并行，语义等价），合并 permission 决策时优先级 **`deny` > `ask` > `allow`**。仅 `deny`/`block` 立即短路；`allow` **不**短路后续 handler（审计 hook 可继续跑）。

```python
async def execute_all(
    self,
    handlers: list[HookHandlerConfig],
    event_data: dict[str, Any],
    *,
    blockable: bool = False,
    on_handler_complete: Callable | None = None,  # 上报 hook_name / duration_ms
) -> HookResult:
    ...
    for handler in handlers:
        result = await self.execute(handler, event_data, ctx)
        if on_handler_complete:
            await on_handler_complete(handler, result, duration_ms)

        if blockable and result.action in ("deny", "block"):
            # Stop 保留 block；其余事件为 deny
            return HookResult(
                action=result.action if result.action == "block" else "deny",
                ...
            )
        ...
```

> **注意**：`allow` 不再在 `execute_all` 层跳过 PermissionEnforcer；跳过弹窗逻辑统一在 `resolve_hook_permission_decision()`（§10.6）。Stop 事件的 `deny` → `block` 映射在 `HookRuntime._run_event`（§3.7）。

### 8.4 子进程环境变量与 command 解析

`HookExecutor.execute()` 启动子进程时注入（兼容 Claude 社区脚本）。

**环境变量策略（`build_hook_env`）**

| 类别 | 行为 |
|------|------|
| 父进程 `os.environ` | **不整包继承**；仅 allowlist：`PATH`、`HOME`、`USER`、`LANG`、`TMPDIR`、`TERM` 等运行所需项 |
| 敏感变量 | `OPENAI_API_KEY`、`AWS_SECRET_ACCESS_KEY`、`ANTHROPIC_API_KEY` 等 **不传递** 给 hook 子进程 |
| Hook 元数据 | 始终注入下表变量（覆盖/补充 allowlist） |

| 变量 | 含义 |
|------|------|
| `MS_AGENT_PROJECT_DIR` | 项目根目录 |
| `MS_AGENT_PLUGIN_ROOT` | 当前 plugin 根（如有） |
| `MS_AGENT_PLUGIN_DATA` | plugin 数据目录（如有） |
| `MS_AGENT_SESSION_ID` | 当前 session |
| `CLAUDE_PROJECT_DIR` | `MS_AGENT_PROJECT_DIR` 别名 |
| `CLAUDE_PLUGIN_ROOT` | `MS_AGENT_PLUGIN_ROOT` 别名 |
| `CLAUDE_PLUGIN_DATA` | `MS_AGENT_PLUGIN_DATA` 别名 |

> HTTP hook 另有 per-handler `allowedEnvVars` ∩ 全局 `http_hook_allowed_env_vars`（§19）；command hook v1 采用固定 allowlist，后续可按 handler 扩展额外白名单。

**超时与子进程回收**：`CommandHookExecutor` 在 `asyncio.TimeoutError` 时对子进程 `kill()` 后 `await wait()`，避免僵尸进程。

**command 解析（v1）**：

- 默认 `shlex.split(handler.command)`——**按空格分词**，不支持 shell 引号语义；`bash -c "foo bar"` 会被错误拆分
- 推荐写法：可执行脚本路径无空格（`./hooks/check.sh`、`/abs/path/hook.py`），复杂逻辑写在脚本内部
- v2 可选支持 `command: ["bash", "-c", "..."]` 列表形式
- 相对路径以 `agent.yaml` / hooks 配置所在目录为 cwd（`HookExecutor(working_dir=...)`）

### 8.5 PostToolUse — additionalContext 回流路径

对齐 Claude Code `services/tools/toolHooks.ts` + `utils/messages.ts`：**不**把 context 拼进 tool result 字符串（避免破坏 JSON 工具输出）。

**Claude 数据流**

```
tool 执行完成
  → executePostToolHooks()
  → hook 返回 additionalContext
  → createAttachmentMessage({ type: 'hook_additional_context', hookEvent: 'PostToolUse', toolUseID })
  → 插入 transcript：assistant(tool_use) → [hook 附件] → user(tool_result)
  → 渲染为 isMeta user 消息，包在 <system-reminder> 内送给模型
  → smooshSystemReminderSiblings：合并进同轮 tool_result 旁侧（Gap F）
```

**ms-agent 对齐方案**

```python
# ms_agent/hooks/context.py
@dataclass(frozen=True)
class HookAttachment:
    type: Literal["hook_additional_context", "hook_blocking_feedback", "hook_stopped_continuation"]
    hook_event: str
    tool_call_id: str | None
    content: str | list[str]

# ToolManager.single_call_tool — Pre/PostToolUse
pre_result, pre_attachments = await hook_runtime.run_pre_tool_use(...)
...
post_result, post_attachments = await hook_runtime.run_post_tool_use(...)
hook_attachments = list(pre_attachments) + list(post_attachments)
# 挂到 tool Message.hook_attachments（见 parallel_tool_call）
```

`LLMAgent.parallel_tool_call()` 组装 `Message(role='tool', ...)` 后：

1. 将 `hook_attachments` 挂到对应 `Message` 的 **`hook_attachments` 字段**（与 `tool_detail` 同级，**不进** `to_dict_clean()`）
2. `step()` 在调用 LLM 前，经 `condense_hook_attachments_for_llm(messages)` 把附件转为 **user 元消息**（`[hook:PostToolUse]` 前缀或 Stop 的 `Stop hook feedback:`），插入 **原消息之后**
3. **禁止**修改 `tool` 消息的 `content` 本体

**PreToolUse additionalContext**：与 PostToolUse 相同，经 `hook_attachments` 挂在 tool 消息上，下轮 LLM 前 condense（v1 不 smoosh 进 tool_result 字符串）。

**Stop blocking feedback**：挂在 assistant 消息上的 `HookAttachment(type=hook_blocking_feedback)`，由 `append_stop_blocking_feedback()` 写入（§9.4）。

**WebUI（Hold）**：`hook_attachments` 经 SSE/API 透出供 UI 展示；具体渲染见 §9.6 预留接口。

### 8.6 fail_closed 粒度

| 粒度 | v1 | 说明 |
|------|-----|------|
| `hooks.fail_closed`（全局） | ✅ | 超时/exit≠2/命令不存在 → 可阻断事件视为 `deny` |
| per-handler `failClosed` | ✅ | 覆盖单条 handler；与全局为 OR 关系 |

---

## 9. 生命周期 Hook 集成与阻断消费

### 9.1 职责划分（PR#906 后）

| 事件 | 集成位置 | 说明 |
|------|---------|------|
| `PreToolUse` / `PostToolUse` / `PermissionRequest` | **`ToolManager.single_call_tool()`** | 工具名/参数/返回值 |
| `SessionStart` | **`CallbackToHookBridge.on_task_begin`** | `round==0` |
| `UserPromptSubmit` | **`LLMAgent.run_loop()` / `InputCallback` 路径** | 用户消息进循环前（§4.5） |
| `Stop` | **`LLMAgent.after_tool_call()`** | `should_stop` 判定前（§4.5） |

`CallbackToHookBridge` **仅**转发 `SessionStart`；`UserPromptSubmit` / `Stop` 由 `LLMAgent` 直接调 `HookRuntime`，避免误绑到 `on_generate_response` / `on_task_end`。

### 9.2 CallbackToHookBridge（SessionStart 专用）

```python
class CallbackToHookBridge(Callback):
    def __init__(self, config, hook_runtime: HookRuntime) -> None:
        super().__init__(config)
        self._hooks = hook_runtime

    async def on_task_begin(self, runtime, messages) -> None:
        await self._hooks.run_session_start(runtime, messages)
```

### 9.3 UserPromptSubmit — 挂点与消费

**挂点 A — 首条用户消息**（`run_loop()`，`create_messages()` 之后）：

执行顺序：**`SessionStart`（`on_task_begin`）→ `UserPromptSubmit`**。SessionStart 负责会话初始化；UserPromptSubmit 在校验通过后才进入 `step()` / LLM。

```python
# llm_agent.py — run_loop() round==0
messages = await self.create_messages(messages)
await self.on_task_begin(messages)          # SessionStart（CallbackToHookBridge）
prompt_text = _extract_latest_user_prompt(messages)
submit = await self._hook_runtime.run_user_prompt_submit(prompt=prompt_text, ...)
if submit.action == "deny":
    # 对齐 Claude processUserInput.ts：不进入 step()
    messages.append(Message(
        role="system",
        content=f"UserPromptSubmit operation blocked by hook:\n{submit.reason}\n\nOriginal prompt: {prompt_text}",
    ))
    await self.on_task_end(messages)
    yield messages
    return
_apply_hook_attachments(messages, submit)  # additionalContext → hook_additional_context
```

**挂点 B — 多轮 `InputCallback`**（`after_tool_call` 追加 user 后、下一轮 `step()` 前）：

在 `InputCallback` 之后、`runtime.should_stop = False` 分支内，对新增 user 内容再跑一遍 `run_user_prompt_submit`；`deny` 时撤销该 user 消息并 `should_stop = True`。

**消费语义**（对齐 Claude `processUserInput.ts`）：

| HookResult | ms-agent 行为 |
|------------|--------------|
| `deny` / exit 2 | **不调用** `step()` / LLM；写入 system 警告 + 原始 prompt 摘要；结束或等待新输入 |
| `additional_context` | 追加 `HookAttachment(type=hook_additional_context, hook_event=UserPromptSubmit)`，下轮 LLM 前渲染为元 user 消息 |
| `pass` | 正常进入 `step()` |

### 9.4 Stop — 挂点与消费

**挂点** — `LLMAgent.after_tool_call()`，在现有 `should_stop` 逻辑**之前**：

```python
async def after_tool_call(self, messages: List[Message]) -> None:
    assistant = messages[-1]
    would_stop = assistant.role == "assistant" and not assistant.tool_calls

    if would_stop and self._hook_runtime is not None:
        last_text = assistant.content if isinstance(assistant.content, str) else ""
        stop = await self._hook_runtime.run_stop(
            reason="no_tool_calls",
            last_assistant_message=last_text,
            stop_hook_active=getattr(self.runtime, "stop_hook_active", False),
        )
        if stop.action in ("block", "deny"):
            # 对齐 Claude stopHooks.ts：HookAttachment 承载，下轮 condense 为 user 元消息
            append_stop_blocking_feedback(messages, stop.reason)
            self.runtime.should_stop = False
            self.runtime.stop_hook_active = True
            await self.loop_callback("after_tool_call", messages)
            return
        apply_hook_result_to_messages(messages, stop, hook_event="Stop")

    if would_stop:
        self.runtime.should_stop = True
    await self.loop_callback("after_tool_call", messages)
```

| HookResult | ms-agent 行为 |
|------------|--------------|
| `block` / `deny` | `should_stop = False`；`append_stop_blocking_feedback` → 下轮 condense 为 `Stop hook feedback` 元 user 消息；`stop_hook_active = True` |
| `additional_context` | `hook_additional_context` 附件，下轮 LLM 前注入 |
| `pass` | `should_stop = True`（默认停止） |

### 9.5 HookAttachment 统一消费（阻断 + context）

```python
# ms_agent/hooks/context.py
def apply_hook_result_to_messages(...) -> bool:
    """返回 False 表示调用方应中止后续流程（UserPromptSubmit deny）。"""
    ...

def append_stop_blocking_feedback(messages, reason: str) -> None:
    """Stop block：挂 hook_blocking_feedback 到当前 assistant 消息。"""
    ...

def condense_hook_attachments_for_llm(messages: list[Message]) -> list[Message]:
    """hook_additional_context → [hook:Event]；hook_blocking_feedback → Stop hook feedback。"""
    ...
```

### 9.6 WebUI 预留接口（实现 Hold）

以下接口在 `ms_agent/hooks/` 与 `webui/backend/` 间预留，**具体 UI 延后**：

```python
# 供 SSE / agent_runner 消费
class HookEventNotification(TypedDict, total=False):
    hook_event: str
    hook_name: str
    action: str
    reason: str
    duration_ms: float

# HookRuntime 可选 callback
on_hook_event: Callable[[HookEventNotification], Awaitable[None]] | None = None
```

WebUI 仅需订阅 `on_hook_event` 与 message 上的 `hook_attachments`；阻断态用现有 run 中止 + system 消息展示，不做专用弹窗（P2）。

### 9.7 注册方式

```python
async def prepare_tools(self):
    ...
    session_id = self.runtime.session_id or self.tag or str(uuid.uuid4())
    hook_runtime = build_hook_runtime(self.config, session_id=session_id)

    self.tool_manager = ToolManager(..., hook_runtime=hook_runtime, ...)
    if hook_runtime.has_session_handlers:
        self.register_callback(CallbackToHookBridge(self.config, hook_runtime))
    self._hook_runtime = hook_runtime
    await self.tool_manager.connect()
```

---

## 10. 与权限系统的协作

> **权限模块已落地**（见 `docs/zh/design/permission-design.md` §1.1）：`SafetyGuard` + `PermissionEnforcer` 已在 `ToolManager.single_call_tool()` L294–344 运行。本文档仅描述 **Hooks 插入点**；不在 `permission-design.md` 重复实现，但需在 permission 文档 §2 判定流程图补一行「1.5 Hooks PreToolUse」（见 [附录 C](#附录-c实现待办与跨文档约定)）。

### 10.1 权限基线（PR#906）与 Hooks 集成后流程

PR#906 落地时 `single_call_tool` 仅有 SafetyGuard + PermissionEnforcer；**Hooks 已在此基础上插入**（见 §10.2）。以下为插入前的权限摘录（步骤 1 仍保持不变）：

```python
# ms_agent/tools/tool_manager.py — single_call_tool() 摘录
args_dict = dict(tool_args) if isinstance(tool_args, dict) else {}

if self._safety_guard is not None:
    safety_decision = self._safety_guard.check(tool_name, args_dict)
    if safety_decision.action == 'deny':
        return f'Blocked by safety policy: {safety_decision.reason}'
    # ask → resolve_ask() ...

if self._permission_enforcer is not None:
    perm_decision = await self._permission_enforcer.check(tool_name, args_dict)
    if perm_decision.action == 'deny':
        return f'Tool call denied: {perm_decision.reason}'
    if perm_decision.updated_args is not None:
        tool_args = perm_decision.updated_args

response = await asyncio.wait_for(tool_ins.call_tool(...), timeout=wait_sec)
return response
```

### 10.2 目标执行顺序（插入 Hooks 后）

```
ToolManager.single_call_tool(tool_info)
  │
  ├─ 1. SafetyGuard.check()              ← 安全底线（不可绕过，已实现）
  │
  ├─ 2. HookRuntime.run_pre_tool_use()   ← PreToolUse（已实现）
  │     └─ 产出 HookResult + pre_attachments（additionalContext）
  │
  ├─ 3. resolve_hook_permission_decision()  ← Hook × Permission 合并（§10.6）
  │     ├─ deny  → return 'Blocked by hook: ...'
  │     ├─ allow → 规则层无异议则放行；blacklist / ask rule 仍可拦截
  │     └─ pass/ask → PermissionEnforcer.check()（ask 可带 hook reason）
  │
  ├─ 4. tool_ins.call_tool()             ← 执行（已实现）
  │
  └─ 5. HookRuntime.run_post_tool_use()  ← PostToolUse（已实现）
        └─ pre + post hook_attachments → §8.5
```

与 `permission-design.md` §2 对齐：**SafetyGuard → PreToolUse →（resolve）→ PermissionEnforcer → call_tool → PostToolUse**。

#### 10.2.1 F7 MCP Runtime 扩展（交叉引用）

当 Playground 启用 `MCPRuntime` 时，[`mcp_runtime_management.md` §7.4](../../design/mcp_runtime_management.md#74-与-hooks-管线协作single_call_tool-完整顺序) 在**本节前**插入：

1. `_tool_index` 快照
2. **MCP callable 检查**（`degraded` / `error` 短路，不进入下文 SafetyGuard）

此后步骤与本节 §10.2 编号对齐（本文步骤 1 → MCP 文档步骤 2，依此类推）。`degraded` 的 MCP 工具**不触发** PreToolUse，因其在 MCP callable 步骤已拒绝 RPC。

### 10.3 为什么 PreToolUse 在 PermissionEnforcer 之前、SafetyGuard 之后

- **SafetyGuard 不可绕过**：已在步骤 1 拒绝的调用不会进入 Hook（与 Claude bypass-immune safety checks 同层）
- **Hook 可提前 deny**：避免无意义的 confirm 弹窗
- **Hook `allow` ≠ 全权放行**：对齐 Claude `resolveHookPermissionDecision`——`allow` 仅表示**建议免弹窗**，`permission:` blacklist 与显式 ask rule **仍可覆盖**
- **参数改写前置**：`updated_args` 在 permission 匹配前生效，黑白名单匹配最终参数

### 10.4 ToolManager 集成代码（目标补丁）

```python
# ms_agent/tools/tool_manager.py

from ms_agent.hooks.permission_resolve import resolve_hook_permission_decision

args_dict = dict(tool_args) if isinstance(tool_args, dict) else {}

# 1. SafetyGuard（已有）
if self._safety_guard is not None:
    ...

# 2. PreToolUse
hook_result: HookResult | None = None
pre_attachments: list[HookAttachment] = []
if self._hook_runtime is not None:
    hook_result, pre_attachments = await self._hook_runtime.run_pre_tool_use(
        tool_name=tool_name,
        tool_args=args_dict,
    )
    if hook_result.updated_args is not None:
        tool_args = hook_result.updated_args
        args_dict = dict(hook_result.updated_args)
        tool_info['arguments'] = tool_args

# 3. Hook × Permission 合并
perm_out = await resolve_hook_permission_decision(
    hook_result=hook_result,
    tool_name=tool_name,
    tool_args=args_dict,
    permission_enforcer=self._permission_enforcer,
    permission_config=self._permission_config,
)
if isinstance(perm_out, str):
    return perm_out
if perm_out.action == 'deny':
    return f'Tool call denied: {perm_out.reason}'
if perm_out.updated_args is not None:
    tool_args = perm_out.updated_args
    tool_info['arguments'] = tool_args

response = await asyncio.wait_for(tool_ins.call_tool(...), timeout=wait_sec)

# 5. PostToolUse
if self._hook_runtime is not None:
    post = await self._hook_runtime.run_post_tool_use(...)
return response
```

### 10.5 hooks 与权限的边界

| 维度 | Permission 系统 | Hooks 系统 |
|------|---------------|------------|
| 职责 | 内置的工具访问控制（YAML 规则 + 用户确认） | 可扩展策略脚本（社区 hook） |
| 配置来源 | YAML `permission:` 段 | YAML `hooks:` / `.claude/settings.json` 等 |
| 执行方式 | In-process Python | 子进程（语言中立） |
| PreToolUse `allow` | blacklist **仍可 deny**；无规则命中时可免弹窗 | 产出 `allow` **建议**，由 `resolve_hook_permission_decision` 合并 |
| PreToolUse `deny` | 不再执行 | 硬拒绝，优先于 permission |
| PreToolUse `pass` / `{}` | 完整 `check()` 流程 | 社区脚本「只审计不干预」的默认写法 |
| 用户交互 | `ask` → handler 弹窗 | `ask` 可强制带 hook 文案进入 handler |
| 记忆持久化 | PermissionMemory（allow_always） | 无（每次执行脚本） |

`ToolManager.__init__` 新增 `hook_runtime: HookRuntime | None = None`；`LLMAgent.prepare_tools()` 构造共享实例并传入。

### 10.6 `resolve_hook_permission_decision` — 社区 Hook 兼容核心

对齐 Claude Code `services/tools/toolHooks.ts` → `resolveHookPermissionDecision()` 与 `utils/permissions/permissions.ts` → `checkRuleBasedPermissions()`。

**设计原则**：Hook 产出 **permission 建议**，不与 Permission 整层互斥；`allow` **不**等于 `hook_skip_permission=True`。

```python
# ms_agent/hooks/permission_resolve.py

async def check_rule_based_permissions(
    tool_name: str,
    tool_args: dict[str, Any],
    config: PermissionConfig,
    matcher: PermissionMatcher,
) -> PermissionDecision | None:
    """仅规则层：blacklist deny、显式 ask rule。不跑 handler 弹窗。
    返回 None 表示规则层无异议（对齐 Claude checkRuleBasedPermissions → null）。"""
    for pattern in config.blacklist:
        if matcher.match_with_content(pattern, tool_name, tool_args):
            return PermissionDecision(action='deny', reason=f'Denied by blacklist: {pattern}')
    for pattern in config.ask_rules:
        if matcher.match_with_content(pattern, tool_name, tool_args):
            return PermissionDecision(action='ask', reason=f'Ask rule matched: {pattern}')
    return None


async def resolve_hook_permission_decision(
    hook_result: HookResult | None,
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    permission_enforcer: PermissionEnforcer | None,
    permission_config: PermissionConfig | None,
    hook_runtime: HookRuntime | None = None,
) -> PermissionDecision | str:
    """合并 PreToolUse 与 PermissionEnforcer。返回 str 表示工具层错误文案。"""

    # Hook deny — 直接拒绝（优先于 permission）
    if hook_result and hook_result.action == 'deny':
        return f'Blocked by hook: {hook_result.reason}'

    args = hook_result.updated_args if (hook_result and hook_result.updated_args) else tool_args

    # Hook allow — 跳过「无规则命中」时的 ask，但规则层仍可拦截
    if hook_result and hook_result.action == 'allow':
        if permission_config:
            rule = await check_rule_based_permissions(
                tool_name, args, permission_config, PermissionMatcher())
            if rule and rule.action == 'deny':
                return rule  # blacklist 覆盖 hook allow（Claude inc-4788）
            if rule and rule.action == 'ask':
                # 显式 ask rule：仍走 enforcer / handler
                if permission_enforcer:
                    return await permission_enforcer.check(
                        tool_name, args, force_decision=rule)
        return PermissionDecision(
            action='allow',
            reason=hook_result.reason or 'Allowed by PreToolUse hook',
        )

    # Hook ask — 带 hook 文案进入完整 permission 流程
    if hook_result and hook_result.action == 'ask':
        if permission_enforcer:
            return await permission_enforcer.check(
                tool_name, args,
                force_decision=PermissionDecision(
                    action='ask', reason=hook_result.reason),
            )

    # pass / 无 hook — PermissionRequest（P1，interactive 模式）→ PermissionEnforcer
    if hook_runtime and permission_config and permission_config.mode == 'interactive':
        pr = await hook_runtime.run_permission_request(tool_name, args)
        if pr.action == 'deny':
            return f'Blocked by hook: {pr.reason}'
        if pr.action == 'ask' and permission_enforcer:
            return await permission_enforcer.check(
                tool_name, args,
                force_decision=PermissionDecision(action='ask', reason=pr.reason),
            )

    if permission_enforcer:
        return await permission_enforcer.check(tool_name, args)
    return PermissionDecision(action='allow', reason='No permission enforcer')
```

**`PermissionEnforcer.check()` 扩展**（小改，已实现类上追加可选参数）：

```python
async def check(
    self,
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    force_decision: PermissionDecision | None = None,
) -> PermissionDecision:
    if force_decision and force_decision.action == 'ask':
        # handler.ask() 使用 force_decision.reason 作为弹窗说明
        ...
```

**社区脚本典型场景对照**：

| 社区脚本写法 | ms-agent 行为 |
|-------------|--------------|
| `echo '{}'` / 只写日志 | `pass` → 完整 permission（含 ask） |
| `permissionDecision: "allow"` | 无 blacklist 时免弹窗；**blacklist 仍 deny** |
| `permissionDecision: "deny"` | 直接拒绝 |
| `permissionDecision: "ask"` | 强制弹窗，带 hook reason |
| 仅 `updatedInput` | 改参后走完整 permission |
| `decision: "approve"`（Codex 风格） | 同 `allow` |

**与 ms-agent 双层架构的映射**：

| Claude 概念 | ms-agent 等价 |
|------------|-------------|
| `tool.checkPermissions` + safetyCheck bypass-immune | **SafetyGuard**（在 Hook 之前） |
| `checkRuleBasedPermissions` | `check_rule_based_permissions()`（blacklist / ask rule） |
| `canUseTool` 弹窗 | `PermissionEnforcer.check()` + handler |
| Hook `allow` 跳过弹窗 | `resolve` 在规则层无异议时直接 `allow` |

---

## 11. 集成点与代码变更

PR#906 已合入，集成策略调整为 **双入口、单 HookRuntime**：

| 模块 | 变更 | 侵入度 |
|------|------|--------|
| `ms_agent/tools/tool_manager.py` | `hook_runtime` + Pre/Post；Post 返回 `hook_attachments` | **必要** |
| `ms_agent/agent/llm_agent.py` | `prepare_tools()`；`run_loop` UserPromptSubmit；`after_tool_call` Stop；`condense_hook_attachments_for_llm` | **中等** |
| `ms_agent/llm/utils.py` | `Message.hook_attachments`；`Runtime.stop_hook_active` | 小 |
| `ms_agent/hooks/*` | Hooks 模块（含 `permission_resolve.py`、loaders） | **已实现** |
| `ms_agent/permission/enforcer.py` | `check(..., force_decision=)` 可选扩展 | 小改 |
| `ms_agent/utils/pattern_matcher.py` | 从 `permission/matcher.py` 提取 | 重构 |
| `ms_agent/hooks/bridge.py` | `CallbackToHookBridge`（仅 SessionStart） | **已实现** |

### 11.1 `prepare_tools()` 接线（`llm_agent.py`）

`session_id` 与 `Runtime.session_id` 同步（默认 `agent.tag`，否则 UUID），并写入 hook stdin。

```python
async def prepare_tools(self):
    safety_guard, permission_enforcer, perm_config = self._build_permission_objects()
    session_id = self.runtime.session_id or self.tag or str(uuid.uuid4())
    hook_runtime = build_hook_runtime(self.config, session_id=session_id)

    self.tool_manager = ToolManager(
        self.config,
        self.mcp_config,
        self.mcp_client,
        permission_enforcer=permission_enforcer,
        safety_guard=safety_guard,
        permission_mode=perm_config.mode,
        read_policy=perm_config.safety.read_policy,
        hook_runtime=hook_runtime,
        trust_remote_code=self.trust_remote_code,
    )
    if hook_runtime.has_session_handlers:
        self.register_callback(CallbackToHookBridge(self.config, hook_runtime))
    self._hook_runtime = hook_runtime
    await self.tool_manager.connect()
```

### 11.2 `parallel_tool_call` 与并发

`parallel_call_tool()` 对每个 `ToolCall` 独立调用 `single_call_tool()`。PreToolUse / PostToolUse **按单工具粒度**触发，与 Claude `PreToolUse` 一致。并发下：

- 各调用使用独立 `tool_info` 副本，避免 `updated_args` 竞态
- `HookExecutor` 子进程彼此隔离；handler 脚本须自身保证可重入
- `session_id` 从 `HookRuntime` 或 `LLMAgent.runtime` 读取，跨并行 tool 共享

### 11.3 与旧 Callback 共存

- `InputCallback` 等内置 Callback **保留**，与 `CallbackToHookBridge` 同链执行
- 旧 Python Callback **不废弃**；仅新增 shell hook 能力
- `trust_remote_code` 与 shell hook **无关**——hook 脚本通过配置路径显式声明，不经 `importlib` 加载

---

## 12. 文件结构

```
ms_agent/
├── utils/
│   └── pattern_matcher.py          # 共享 fnmatch（从 permission/matcher 提取）
├── hooks/
│   ├── __init__.py
│   ├── events.py                   # Canonical 事件 + HookResult
│   ├── registry.py
│   ├── executor.py                 # Dispatcher 门面
│   ├── executors/
│   │   ├── __init__.py
│   │   ├── command.py              # P0
│   │   ├── http.py                 # P2 §17.2
│   │   ├── prompt.py               # P2 §17.3
│   │   └── agent.py                # P3 §17.4
│   ├── runtime.py
│   ├── factory.py
│   ├── response_adapter.py
│   ├── tool_name_mapper.py
│   ├── context.py
│   ├── bridge.py
│   ├── hook_helpers.py             # add_arguments_to_prompt、HookOkReasonSchema
│   ├── permission_resolve.py       # resolve_hook_permission_decision（§10.6）
│   └── loaders/
│       ├── __init__.py
│       ├── native.py
│       ├── claude.py
│       ├── cursor.py
│       ├── hermes.py
│       └── plugin.py              # F9 Plugin hooks/hooks.json
├── permission/                     # 已实现，见 permission-design.md
│   └── matcher.py                  # 委托 pattern_matcher.match_pattern
docs/zh/design/
├── hooks-design.md
└── permission-design.md
tests/
├── test_hooks.py
├── test_hooks_loaders.py
├── test_hooks_context.py
└── fixtures/hooks/
```

> **注**：F9 通用 `PluginLoader`（manifest 发现）若独立于 hooks，可置于 `ms_agent/plugins/`；当前 **hooks 加载** 由 `hooks/loaders/plugin.py` 的 `PluginHooksLoader` 完成。

---

## 13. 与外部生态的对比

### 13.1 执行模型

| 平台 | Hook 形态 | 执行方式 | ms-agent v1 |
|------|-----------|----------|-------------|
| Claude Code | settings + plugin `hooks.json` | 子进程 / HTTP / prompt / agent | **command 子进程** |
| Cursor | `.cursor/hooks.json` | 子进程 / prompt | **command 子进程**（兼容 Claude third-party） |
| Hermes | Plugin / Shell / Gateway | Python 进程内 / 子进程 | **Shell hook 子进程** |
| OpenClaw | Typed `api.on()` + HOOK pack | TS 进程内 | Claude `hooks.json` **不执行** |
| ms-agent | Canonical + 多源 loader | asyncio 子进程 | 原生 |

### 13.2 ms-agent vs Claude Code（核心协议）

| 特性 | Claude Code | MS-Agent |
|------|-------------|----------|
| 协议 | stdin/stdout/exit code | 一致 |
| 阻断 exit code | exit 2 | exit 2 |
| v1 事件 | 30+ | 6 核心 + 3 可选扩展（§15.3） |
| 原生配置 | `.claude/settings.json` | `agent.yaml` / `.ms-agent/hooks.json` |
| Plugin | `hooks/hooks.json` | F9 转换 merge |
| 权限协作 | Hook `allow` 仍受 settings deny/ask 约束 | `resolve_hook_permission_decision`（§10.6） |
| handler v1 | command/http/prompt/agent | **command only**（P2: http/prompt；P3: agent） |

---

## 14. 验证方式

### 14.1 单元测试

| 模块 | 测试要点 |
|------|---------|
| `pattern_matcher` | 通配符匹配、`\|` 分隔、空模式、边界情况 |
| `HookRegistry.from_dict` | YAML 解析、未知事件 warning、空配置 |
| `HookRegistry.merge` | 全局 + 项目追加、事件独立、空合并 |
| `HookRegistry.get_handlers` | matcher 过滤、非工具事件全匹配、无 handler |
| `HookExecutor.execute` | exit 0 + JSON、exit 2 阻断、exit 1 非阻断、超时、找不到命令 |
| `HookExecutor.execute_all` | deny 短路；deny > ask > allow 合并；allow 不短路后续 handler |
| `resolve_hook_permission_decision` | allow + blacklist 覆盖；pass 走完整 enforcer；ask 带 force_decision |
| `HookRuntime` + `ToolManager` | 端到端 PreToolUse；PostToolUse `hook_attachments` |
| `CallbackToHookBridge` | 仅 SessionStart |
| `LLMAgent` UserPromptSubmit / Stop | §9.3 / §9.4 deny 与 block 消费 |
| `condense_hook_attachments_for_llm` | PostToolUse context 不污染 tool content |
| `HttpHookExecutor`（P2） | URL 白名单、header env 插值、SSRF、ResponseAdapter 解析 body |
| `PromptHookExecutor`（P2） | `$ARGUMENTS`、ok/reason schema、不触发 UserPromptSubmit |
| `AgentHookExecutor`（P3） | max_turns、structured output、工具过滤、Stop block |
| `_parse_hook_handler` | command/http/prompt/agent 字段解析；未知 type warning |

### 14.2 集成测试

| 场景 | 验证内容 |
|------|---------|
| 真实脚本执行 | 写一个 Python hook 脚本，验证 stdin 收到 JSON、stdout 返回 JSON、exit code 正确处理 |
| Shell 脚本执行 | 写一个 bash hook 脚本（`exit 2 + stderr`），验证阻断行为 |
| Bridge + LLMAgent | Mock 生命周期，验证 SessionStart / Stop 等非工具事件 |
| ToolManager + hooks | allow 免弹窗；blacklist 覆盖 hook allow；`{}` 仍走 permission ask |
| 配置合并 | 全局 + 项目配置合并后，同事件下 handlers 追加且顺序正确 |
| Claude 配置加载 | 解析 `.claude/settings.json` 中 `PreToolUse` 嵌套结构，脚本可执行 |
| Cursor 配置加载 | 解析 `.cursor/hooks.json` 扁平结构，`beforeShellExecution` 映射正确 |
| Hermes block 格式 | `decision:block` 与 `action:block` 均归一化为 `deny` |
| 跨平台脚本 | 同一份 `block-rm.sh` 经 wrapper 在三方配置下均可阻断 |
| HTTP Policy hook（P2） | mock 远端返回 `decision:deny`，PreToolUse 短路 |
| Prompt guardrail（P2） | mock LLM `ok:false`，UserPromptSubmit 阻断 |
| Agent Stop 验证（P3） | mock 子 agent `ok:false`，Stop 被 block、agent 继续 |

### 14.3 Hook 脚本示例

**PreToolUse：社区脚本放行（须显式 allow）**

```python
#!/usr/bin/env python3
import json, sys
event = json.load(sys.stdin)
if event.get("tool_name", "").endswith("shell_executor"):
    cmd = event.get("tool_args", {}).get("command", "")
    if cmd.startswith("pip install"):
        # 仅审计、不干预 → pass（仍会走 permission ask）
        print(json.dumps({}))
        sys.exit(0)
    if cmd.startswith("npm test"):
        # 建议免弹窗 → allow（blacklist 仍可覆盖）
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }))
        sys.exit(0)
print(json.dumps({}))
```

**PreToolUse：硬拒绝**
```python
#!/usr/bin/env python3
import json, sys
event = json.load(sys.stdin)
if event.get("tool_name", "").endswith("shell_executor"):
    cmd = event.get("tool_args", {}).get("command", "")
    if cmd.startswith("pip install"):
        print(json.dumps({"decision": "deny", "reason": "pip install not allowed"}))
        sys.exit(0)
print(json.dumps({}))
```

**PostToolUse：日志记录（Shell）**
```bash
#!/bin/bash
read event_json
tool_name=$(echo "$event_json" | jq -r '.tool_name')
echo "[$(date)] Tool used: $tool_name" >> /tmp/hook-log.txt
echo '{}'
```

**PreToolUse：阻断（Shell exit 2）**
```bash
#!/bin/bash
read event_json
tool_name=$(echo "$event_json" | jq -r '.tool_name')
if [[ "$tool_name" == *"shell_executor"* ]]; then
    echo "Shell commands are disabled" >&2
    exit 2
fi
echo '{}'
```

---

## 15. 多平台生态兼容设计

### 15.1 兼容目标与边界

**目标（对外承诺）**：

> ms-agent 兼容 Claude Code、Cursor、Hermes 的 **shell-based third-party hooks**（工具拦截、审计、auto-format、context 注入）。用户可将社区 hook **脚本** 与 **配置文件** 以最小改动迁移到 ms-agent 或与之并存。

**边界（v1 执行后端）**：

> 上表「不兼容项」指 **v1 不实现其原生 Executor**，不是放弃对应框架。各框架的 shell/command hook、Plugin 清单、Skills 仍在兼容范围内（见 §3.6.1）。

| v1 不原生执行 | 原因 | 该框架 v1 仍兼容什么 |
|--------------|------|---------------------|
| Claude HTTP / prompt / agent hook | 需独立 HTTP/LLM/子 agent 后端 | `type: command` hook、plugin `hooks.json`、settings 加载 |
| Hermes Python `register_hook()` | Hermes 进程内 API | Hermes **shell** hooks、`config.yaml` 加载 |
| OpenClaw `api.on()` | TS 进程内 | Skills/MCP bundle；Claude hooks.json 仅 detect（与 OpenClaw 一致） |
| 全量专有事件 | 非最小交集 | 8 个 Canonical 事件 + P2 扩展 |

**覆盖率预期**：

| 阶段 | 覆盖社区 hook 场景 |
|------|-------------------|
| P0 原生 + Bridge | ms-agent 自有配置，~40% |
| P1 Claude + Cursor loader | ~70%（审计/阻断/format 类） |
| P1 Hermes shell + Plugin | ~80% |
| P2 扩展事件 | ~85%，仍非 100% |

### 15.2 三家 shell hook 生态关系

```
                    ┌──────────────────────────────┐
                    │  社区 hook 脚本 (.sh/.py)     │  ← 最易复用
                    └──────────────┬───────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
   Claude Code              Cursor                   Hermes Shell
 settings.json            hooks.json              config.yaml hooks:
         │                         │                         │
         └─────────────────────────┴─────────────────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │  ms-agent ExternalLoaders     │
                    │  → Canonical IR → HookExecutor │
                    └──────────────────────────────┘
```

- **Claude ↔ Cursor**：互通最好；Cursor 官方支持 third-party Claude hooks，事件名为 camelCase 映射
- **Hermes shell**：文档明确接受 Claude 风格 `{"decision":"block","reason":"..."}`；配置为 YAML
- **OpenClaw**：单列；Claude `hooks.json` 不执行，需 Codex `HOOK.md` 布局或 native plugin

### 15.3 Canonical 事件模型与映射表

ms-agent 内部统一使用 **Canonical 事件名**（PascalCase，与 Claude 对齐），各 loader 负责入站映射：

| Canonical | 触发时机（ms-agent） | Claude Code | Cursor | Hermes Shell |
|-----------|---------------------|-------------|--------|--------------|
| `SessionStart` | `on_task_begin` | `SessionStart` | `sessionStart` | `on_session_start` |
| `UserPromptSubmit` | 用户输入进入 run 前 | `UserPromptSubmit` | `beforeSubmitPrompt` | `pre_llm_call`（注入 context） |
| `PreToolUse` | 工具执行前 | `PreToolUse` | `preToolUse` | `pre_tool_call` |
| `PostToolUse` | 工具执行后 | `PostToolUse` | `postToolUse` | `post_tool_call` |
| `Stop` | `after_tool_call()` 内、`should_stop` 判定前（§9.4） | `Stop` | `stop` | `on_session_end`（**近似**，会话级） |
| `PermissionRequest` | `PermissionEnforcer.check` 前（interactive，`P1`） | `PermissionRequest` | — | `pre_approval_request`（仅观察） |
| `SubagentStop` | 配置可加载（`VALID_EVENTS`）；**运行时触发 P2** | `SubagentStop` | `subagentStop` | `subagent_stop`（loader 映射） |
| `ShellBefore`（P2 独立事件） | v1 经 Cursor 合成 `PreToolUse`+shell matcher | `PreToolUse(Bash)` | `beforeShellExecution` → **P1 合成** | `pre_tool_call`+`terminal` matcher |
| `FileAfterEdit`（P2 独立事件） | v1 经 Cursor 合成 `PostToolUse`+write matcher | `PostToolUse(Write)` | `afterFileEdit` → **P1 合成** | `post_tool_call`+`write_file` matcher |

> **⚠️ Hermes 兼容边界（必读）**
>
> | Hermes 事件 | ms-agent 映射 | 语义差异 |
> |-------------|--------------|---------|
> | `pre_llm_call` | `UserPromptSubmit` | Hermes：**每次** LLM 调用前；ms-agent：**仅用户消息进入循环时** |
> | `on_session_end` | `Stop` | Hermes：会话级结束；ms-agent：单轮 assistant 无 tool_calls 时，支持 **block 继续** |
> | `pre_approval_request` | `PermissionRequest` | Hermes 偏观察；ms-agent 在 interactive permission 流程中可阻断 |
>
> 迁移 Hermes shell hooks 时，勿假设触发频率与 Hermes 完全一致。

> **Cursor P1 策略**：`beforeShellExecution` / `afterFileEdit` 在 v1 通过 `CursorHooksLoader` 合成为带默认 matcher 的 `PreToolUse` / `PostToolUse`；P2 可拆为独立 Canonical 事件 `ShellBefore` / `FileAfterEdit`。

未知外部事件：**记录 warning 并跳过**，不导致 agent 崩溃。

### 15.4 工具名归一化（ToolNameMapper）

外部 matcher 常按平台工具名编写，执行前需双向映射：

| 语义 | Claude | Cursor | Hermes | ms-agent（示例） |
|------|--------|--------|--------|------------------|
| 执行命令 | `Bash` | `Shell` | `terminal` | `code_executor---shell_executor` |
| 读文件 | `Read` | `Read` | `read_file` | `file_system---read_file` |
| 写文件 | `Write` / `Edit` | `Write` | `write_file` / `patch` | `file_system---write_file` |
| 子 agent | `Task` | `Task` | `delegate_task` | `agent_tool---*` |

`ToolNameMapper` 职责：

1. **出站**（构造 stdin）：Canonical payload 携带 `tool_name` 及按 `enabled_sources` 启用的 `tool_name_claude` / `tool_name_cursor` / `tool_name_hermes` 别名（见 §15.6）
2. **入站**（matcher 匹配）：各 ExternalLoader 在加载时将外部 matcher **转换为** ms-agent `server---tool` 格式（`ToolNameMapper.external_matcher_to_native`）；运行时按 ms-agent 工具名匹配，不做二次 `tool_name_*` 字段过滤

### 15.5 ExternalHookLoaders 设计

```python
class HookLoader(Protocol):
    def load(self, ctx: HookLoadContext) -> HookRegistry: ...

@dataclass(frozen=True)
class HookLoadContext:
    project_root: str
    global_ms_agent_dir: str  # ~/.ms_agent
    plugin_roots: tuple[str, ...]
    enabled_sources: frozenset[str]
```

#### ClaudeSettingsLoader

- 输入：`.claude/settings.json` 或 `~/.claude/settings.json` 的 `hooks` 段
- 解析 Claude 三层嵌套：`event → [{matcher, hooks:[{type, ...}]}]`
- **P0/P1**：`type` 缺失或为 `command` 时入库；`http` / `prompt` / `agent` 若未在 `enabled_executors` 中启用 → **warning + 跳过**（不进入 registry；P2 `hooks doctor` 可扫描源文件提示）
- **P2+**：解析全部 `type`，字段映射见 §17.1
- 路径变量：`${CLAUDE_PROJECT_DIR}` → `project_root`；`${CLAUDE_PLUGIN_ROOT}` → plugin root（F9）

#### CursorHooksLoader

- 输入：`.cursor/hooks.json` 的 `hooks` 对象
- 扁平结构：`{ "preToolUse": [{ "command", "matcher", "timeout", "failClosed" }] }`
- 事件名 camelCase → Canonical PascalCase
- `beforeShellExecution` → 合成 `ShellBefore` 或带 `tool_class: shell` 的 `PreToolUse` matcher
- `failClosed` 透传到 handler 元数据

#### HermesShellLoader

- 输入：`~/.hermes/config.yaml` 的 `hooks:` 段（**v1 仅全局**；项目级 Hermes 配置 P2）
- 事件名 snake_case → Canonical
- 仅加载 shell hook 条目（非 Python plugin）

#### PluginHooksLoader（F9）

对齐 `playground_prototype_design.md` F9：

```python
# ms_agent/plugins/loader.py（示意）
def load_plugin_hooks(manifest: PluginManifest) -> HookRegistry:
    hooks_path = manifest.root / "hooks" / "hooks.json"
    if manifest.format == "claude":
        return ClaudeSettingsLoader.parse_hooks_file(hooks_path, plugin_root=manifest.root)
    ...
```

环境变量（脚本运行时注入，兼容 Claude Code plugin）：

| 变量 | 含义 |
|------|------|
| `MS_AGENT_PROJECT_DIR` | 项目根目录 |
| `MS_AGENT_PLUGIN_ROOT` | 当前 plugin 根目录 |
| `MS_AGENT_PLUGIN_DATA` | 可变数据目录 `~/.ms_agent/plugins/data/<id>/` |
| `CLAUDE_PROJECT_DIR` | **别名**，便于复用 Claude 社区脚本 |

### 15.6 stdin CanonicalPayload 格式

对外部脚本，ms-agent 统一发送：

```json
{
  "event": "PreToolUse",
  "hook_event_name": "PreToolUse",
  "session_id": "abc123",
  "project_path": "/path/to/project",
  "tool_name": "code_executor---shell_executor",
  "tool_name_claude": "Bash",
  "tool_name_cursor": "Shell",
  "tool_name_hermes": "terminal",
  "tool_args": {"command": "rm -rf /tmp/x"},
  "tool_input": {"command": "rm -rf /tmp/x"},
  "cwd": "/path/to/project",
  "extra": {}
}
```

- `tool_args` / `tool_input` **同值**，兼容 Claude（`tool_input`）与 Hermes（`tool_input`）习惯
- 多平台工具名字段可选；简单脚本可只读 `tool_args`

### 15.7 兼容矩阵（能否直接换用）

| 从 → 到 ms-agent | 配置文件 | 脚本 | 说明 |
|------------------|---------|------|------|
| Claude Code | 经 loader 转换 | **高** | 改 jq 路径即可跑大多数社区脚本 |
| Cursor | 经 loader 转换 | **高** | third-party Claude hooks 同理 |
| Hermes shell | 经 loader 转换 | **高** | block 双格式已在 ResponseAdapter 处理 |
| Claude plugin `hooks.json` | F9 merge | **高** | 需 `${CLAUDE_PLUGIN_ROOT}` 别名 |
| Hermes Python plugin | ✗ | ✗ | 需改写为 shell 或 ms-agent 原生 |
| OpenClaw Claude bundle | ✗（detect only） | 视脚本 | 仅当用户单独提供可执行脚本 |

### 15.8 可移植脚本编写规范（推荐）

供 Agent Hub / Playground 导出与社区文档使用：

```bash
#!/usr/bin/env bash
# portable-pre-tool.sh — 尽量只依赖 jq 与 Canonical 字段
payload=$(cat)
tool=$(echo "$payload" | jq -r '.tool_name_claude // .tool_name_cursor // .tool_name // empty')
cmd=$(echo "$payload" | jq -r '.tool_input.command // .tool_args.command // empty')

if [[ "$tool" =~ ^(Bash|Shell|terminal)$ ]] && echo "$cmd" | grep -qE 'rm[[:space:]]+-rf'; then
  jq -n '{"decision":"deny","reason":"rm -rf blocked","action":"block","message":"rm -rf blocked"}'
  exit 0
fi
printf '{}\n'
```

---

## 16. 分阶段交付与验收

对齐 `playground_prototype_design.md` F6（P0.5）与 F9（P1）：

### 16.1 P0 — 引擎 + ToolManager 主路径（权限集成点已就绪）

> PR#906 / `permission-design.md` 已落地双层权限；**P0 + P1 loader 生态已实现**（`ms_agent/hooks/`），P2/P3 扩展 Executor 待做。

| 交付项 | 验收 |
|--------|------|
| `HookRegistry` / `HookExecutor` / `HookRuntime` / `pattern_matcher` | 单元测试通过 |
| **`ToolManager.single_call_tool` 集成** | PreToolUse deny/allow/updated_args；PostToolUse `hook_attachments` |
| `LLMAgent` UserPromptSubmit + Stop 挂点 | §9.3 / §9.4 语义测试 |
| `condense_hook_attachments_for_llm` | PostToolUse context 进入下轮 LLM，不污染 tool content |
| `CallbackToHookBridge` | 仅 SessionStart |
| `ResponseAdapter`（统一 stdout 解析） | `permissionDecision` / `approve`/`block` / `updatedInput` 归一化 |

### 16.2 P1 — 三方生态 + Plugin（已实现）

| 交付项 | 验收 |
|--------|------|
| `ClaudeSettingsLoader` | ✅ 加载 Claude `PreToolUse` 并在 ToolManager 执行 |
| `CursorHooksLoader` | ✅ `preToolUse` / `beforeShellExecution` 合成 |
| `HermesShellLoader` | ✅ `pre_tool_call` shell 配置 |
| `PluginHooksLoader`（F9） | ✅ plugin `hooks/hooks.json` merge |
| `ToolNameMapper` | ✅ Bash/Shell/terminal matcher |
| `PermissionRequest` hook | ✅ interactive 模式下 `resolve_hook_permission_decision` 内触发 |

### 16.3 P2 — 扩展 Executor + Playground 集成

| 交付项 | 验收 |
|--------|------|
| `HttpHookExecutor` + URL 白名单 / SSRF 防护 | §17.2；企业 Policy POST 可阻断 PreToolUse |
| `PromptHookExecutor` + `$ARGUMENTS` 替换 | §17.3；`ok:false` 阻断；不递归触发 UserPromptSubmit |
| `hooks.enabled_executors` | 默认 `[command]`；解析时过滤未启用 type（P2 开启 `http` / `prompt`） |
| `SubagentStop` 运行时挂点 / `ShellBefore` / `FileAfterEdit` 独立事件 | P2：配置已可加载 `SubagentStop`；独立事件与运行时待做 |
| `fail_closed` / `hooks doctor` | 对标 Cursor/Hermes 运维体验；doctor 列出被跳过的非 command handler |
| WebUI Hooks 设置页 | 展示 enabled_sources、enabled_executors、脚本路径、测试触发 |
| Agent Hub 导出 | 导出 `.ms-agent/hooks.json` + 可选 Claude/Cursor 并列配置 |

### 16.4 P3 — Agent Hook 与高级集成

| 交付项 | 验收 |
|--------|------|
| `AgentHookExecutor` | §17.4；Stop 验证、受限工具、`dontAsk` 模式、结构化 `{ok, reason}` |
| OpenClaw HOOK pack 适配 | §17.6；detect-only 或 command 转换 |
| 子 agent transcript 路径注入 | agent hook 可读 session log，对齐 Claude `getTranscriptPath()` |

### 16.5 对外表述（产品 / 文档）

建议使用：

> ms-agent 支持原生 Hooks，并兼容 Claude Code、Cursor、Hermes 的 **shell hook 脚本与配置**（通过 `hooks.enabled_sources` 开启）。v1 完整支持 `command` handler；`http` / `prompt` 在 P2、`agent` 在 P3 以独立 Executor 补齐（见 [§17](#17-扩展-executorhttppromptagent) 与 [附录 A](#附录-ahook-handler-类型与应用场景)）。

---

## 17. 扩展 Executor：HTTP / Prompt / Agent

> 对齐 Claude Code `execHttpHook.ts` / `execPromptHook.ts` / `execAgentHook.ts`；与 §8 Dispatcher 共用 `ResponseAdapter` 与 `HookResult` 语义。

### 17.1 统一路由与配置

`HookExecutor`（§8.1）按 `handler.type` 分发；扩展后端与 `CommandHookExecutor` **并列**，不嵌套。

```python
# ms_agent/hooks/executor.py
class HookExecutor:
    def __init__(self, ..., enabled_executors: frozenset[str] = frozenset({"command"})):
        self._backends: dict[str, HookExecutorBackend] = {}
        if "command" in enabled_executors:
            self._backends["command"] = command_executor
        if "http" in enabled_executors:
            self._backends["http"] = http_executor
        # prompt / agent 同理
```

**全局开关**（`agent.yaml` / `hooks.yaml`）：

```yaml
hooks:
  enabled_executors: [command]       # P2: 追加 http, prompt；P3: 追加 agent
  default_model: "qwen-plus"         # prompt/agent 未指定 model 时的 fast 模型
  # HTTP 策略（对齐 Claude allowedHttpHookUrls / httpHookAllowedEnvVars）
  allowed_http_hook_urls:            # undefined=不限制；[]=全禁；非空=通配符白名单
    - "https://policy.corp.example/*"
  http_hook_allowed_env_vars: ["POLICY_TOKEN", "AUDIT_API_KEY"]
```

**Claude settings → HookHandlerConfig 字段映射**：

| Claude 字段 | ms-agent | 说明 |
|-------------|----------|------|
| `type: http` + `url` | `type`, `url` | 必填 |
| `headers` | `headers` | 值支持 `$VAR` / `${VAR}`，仅 `allowed_env_vars` 白名单内解析 |
| `allowedEnvVars` | `allowed_env_vars` | 与全局 `http_hook_allowed_env_vars` 取交集 |
| `type: prompt` + `prompt` | `type`, `prompt` | `$ARGUMENTS` 替换为事件 JSON 字符串 |
| `model` | `model` | 缺省 → `hooks.default_model` |
| `type: agent` + `prompt` | `type`, `prompt`, `max_turns` | 默认 `max_turns=20`（Claude 硬上限 50） |
| `timeout` | `timeout` | 秒；各后端独立默认见 §17.2–17.4 |

**Loader 行为**：`ClaudeSettingsLoader` / `NativeYamlLoader` **解析并保留**全部 type；若 executor 未启用，`HookRegistry.get_handlers()` 过滤或 `HookExecutor.execute()` 返回 `action=error` + doctor warning，避免静默丢配置。

### 17.2 HttpHookExecutor

**职责**：将 Canonical 事件 JSON **POST** 到 `handler.url`，响应 body 经 `ResponseAdapter` 解析（与 command stdout 相同 schema：`decision` / `permissionDecision` / `updatedInput` / `additional_context` 等）。

**执行流程**（对齐 `execHttpHook.ts`）：

```
event_data ──json.dumps──► POST url
                │              │
                │         headers + Content-Type: application/json
                │              │
                ▼              ▼
         URL 白名单校验    SSRF lookup（无代理时）
                │              │
                └──────┬───────┘
                       ▼
              response body (text)
                       ▼
              ResponseAdapter.parse()
                       ▼
                   HookResult
```

**类设计**：

```python
# ms_agent/hooks/executors/http.py
class HttpHookExecutor:
  async def execute(
      self, handler: HookHandlerConfig,
      event_data: dict[str, Any],
      ctx: HookExecutionContext,
  ) -> HookResult:
      # 1. allowed_http_hook_urls 通配符匹配（* 语义同 Claude MCP allowlist）
      # 2. 构建 headers：interpolate_env_vars(value, allowed_env_vars ∩ policy)
      #    sanitize CR/LF/NUL 防 header injection
      # 3. aiohttp/httpx POST，timeout=handler.timeout，max_redirects=0
      # 4. 有 HTTP_PROXY 或沙箱代理时跳过直连 SSRF guard（与 Claude 一致）
      # 5. 2xx → ResponseAdapter.parse(body)；非 2xx / 网络错误 → action=error
```

**安全要点**：

| 项 | 策略 |
|----|------|
| URL 白名单 | `hooks.allowed_http_hook_urls`：`undefined` 不限制；`[]` 禁止全部；否则 `urlMatchesPattern()` |
| SSRF | 直连时 DNS 解析后拒绝 private/link-local（可配置允许 loopback 用于本地 dev） |
| 环境变量 | 仅 `allowed_env_vars` ∩ 全局白名单可注入 header；其余替换为空串 |
| 重定向 | `max_redirects=0`，防开放重定向绕过白名单 |
| fail_closed | handler 或全局 `fail_closed=true` 时，网络/解析失败 → 可阻断事件上视为 `deny` |

**与 command + curl 的差异**：统一超时、白名单、SSRF、响应 schema；Playground / 企业 MDM 可只开放 URL 而不分发脚本。

**典型配置**（Claude `settings.json` 等价）：

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{
        "type": "http",
        "url": "https://policy.example/v1/pre-tool",
        "timeout": 10,
        "headers": { "Authorization": "Bearer ${POLICY_TOKEN}" },
        "allowedEnvVars": ["POLICY_TOKEN"]
      }]
    }]
  }
}
```

### 17.3 PromptHookExecutor

**职责**：将 hook 事件 JSON 填入 `handler.prompt` 的 `$ARGUMENTS` / `${ARGUMENTS}` 占位符，调用**单次** LLM（非完整 agent 循环），解析结构化输出 `{ok: bool, reason?: string}`。

**执行流程**（对齐 `execPromptHook.ts`）：

```
event_data ──json.dumps──► add_arguments_to_prompt(prompt, json)
                                    │
                                    ▼
              构造单条 user Message（不经过 run_loop / InputCallback）
                                    │
                                    ▼
              llm.generate（structured output / json_schema）
              model = handler.model ?? hooks.default_model
              system: "return {ok:true} or {ok:false, reason}"
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
              ok == true                      ok == false
           HookResult(pass/allow)            HookResult(deny, reason)
```

**关键约束**：

| 约束 | 原因 |
|------|------|
| **禁止递归 UserPromptSubmit** | 不得走 `create_messages()` / `processUserInput()`；直接构造 hook 专用 message（Claude L40–41） |
| **不注入完整 session history（默认）** | v1 仅 hook prompt + 可选 `ctx.messages` 尾部摘要；避免 token 爆炸 |
| **结构化输出** | `ok:false` → `action=deny`（可阻断事件）或 `block`（Stop）；解析失败 → `action=error`（非阻断，除非 fail_closed） |
| **与 PreToolUse permission** | prompt 返回 `ok:true` 等价 `pass`（`{}`），**不**自动 `allow`；若需免弹窗须响应含 `permissionDecision: allow` 并经 `resolve_hook_permission_decision` |
| **工具不可用** | prompt hook **不**暴露 ToolManager；复杂判断用 agent hook |

**类设计**：

```python
# ms_agent/hooks/executors/prompt.py
class PromptHookExecutor:
  async def execute(...) -> HookResult:
      processed = add_arguments_to_prompt(handler.prompt, json.dumps(event_data))
      response = await ctx.llm.generate(
          messages=[Message(role="user", content=processed)],
          system_prompt=HOOK_PROMPT_SYSTEM,
          model=handler.model or self._default_model,
          response_format=HookOkReasonSchema,  # {ok, reason?}
          timeout=handler.timeout,
      )
      parsed = parse_hook_ok_reason(response)
      if parsed.ok:
          return HookResult(action="pass")
      return HookResult(action="deny", reason=parsed.reason or "Prompt hook condition not met")
```

**Cursor `type: prompt`**：`CursorHooksLoader` 映射为 `type: prompt`，共用本 Executor。

### 17.4 AgentHookExecutor

**职责**：启动**短生命周期子 agent**（多轮 tool loop），用于需读仓库 / transcript / 多步验证的场景；主要用于 **`Stop`** 事件（Claude Stop 验证），亦可用于高成本 `PreToolUse`（需显式配置）。

**执行流程**（对齐 `execAgentHook.ts`）：

```
event_data ──► add_arguments_to_prompt ──► 子 agent run_loop（受限）
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
            过滤危险工具              permission mode=dontAsk      max_turns 上限
         （无 spawn subagent）      transcript 路径可读            timeout abort
                    │                         │                         │
                    └─────────────────────────┴─────────────────────────┘
                                              ▼
                        StructuredOutputTool → {ok, reason}
                                              ▼
                                    HookResult(deny|pass)
```

**类设计**：

```python
# ms_agent/hooks/executors/agent.py
class AgentHookExecutor:
  DISALLOWED_TOOLS = frozenset({
      "agent_tool", "plan_mode", ...  # 禁止子 agent 再 spawn / 进 plan
  })

  async def execute(...) -> HookResult:
      hook_agent_id = f"hook-agent-{uuid4()}"
      tools = filter_tools(ctx.tool_manager, disallow=self.DISALLOWED_TOOLS)
      tools.append(StructuredOutputTool(schema=HookOkReasonSchema))

      sub_ctx = HookAgentContext(
          parent=ctx,
          agent_id=hook_agent_id,
          permission_mode="dontAsk",   # 对齐 Claude getAppState().mode
          extra_allow_rules=[f"read:{transcript_path}"],
          max_turns=min(handler.max_turns, 50),
      )
      result = await run_hook_agent_loop(
          messages=[user_msg_from_prompt],
          system_prompt=HOOK_AGENT_SYSTEM.format(transcript=transcript_path),
          tools=tools,
          ctx=sub_ctx,
          timeout=handler.timeout,
      )
      if result is None:  # 超时 / 未调用 structured output
          return HookResult(action="error", reason="Agent hook did not complete")
      if not result.ok:
          return HookResult(action="deny", reason=result.reason)
      return HookResult(action="pass")
```

**与 prompt 的选型**：

| | PromptHook | AgentHook |
|---|-----------|-----------|
| LLM 调用 | 单次 | 多轮 + 工具 |
| 延迟 / 成本 | 低 | 高 |
| 可读文件 / 跑命令 | 否 | 是（受限工具集） |
| 典型事件 | UserPromptSubmit、轻量 PreToolUse | **Stop**、复杂合规 |

**Stop 语义**：`ok:false` → `block`（阻止停止，agent 继续）；映射到 `HookResult(action="block", reason=...)`，由 `LLMAgent` §9.4 消费。

**安全**：子 agent 继承父 session 的工具面但经白名单过滤；`dontAsk` 仅作用于 hook 子会话；禁止修改 hooks 配置或启动新 top-level session。

### 17.5 扩展 Executor 与权限 / 阻断事件

三类扩展 Executor 的输出**统一**进入既有管线：

```
Executor → HookResult
    ├─ PreToolUse + deny → 短路，不调用工具
    ├─ PreToolUse + allow/pass → resolve_hook_permission_decision（§10.6）
    ├─ UserPromptSubmit + deny → 拒绝用户消息进入循环
    ├─ Stop + block/deny → 取消 should_stop，注入 reason 到 assistant 上下文
    └─ PostToolUse → additional_context → HookAttachment（§8.5）
```

**prompt/agent 的 `ok` 与 permission JSON 的关系**：

- 仅 `{ok:false}` → 策略性阻断（等价 exit 2 / `decision:deny`）
- `{ok:true}` + stdout 风格 `permissionDecision: allow` → 走 `resolve_hook_permission_decision`
- HTTP 响应 body 可同时携带 Claude 完整 JSON（`updatedInput` 等），由 `ResponseAdapter` 一次解析

### 17.6 OpenClaw 与其它扩展

OpenClaw **typed `api.on()`** hook 为 TS 进程内中间件，ms-agent **不**原生执行。P3 可选路径：

1. **detect-only**：识别 OpenClaw bundle，文档引导作者导出等价 `hooks.json` command 脚本
2. **command 转换**：将简单 HOOK pack 译为 shell 包装（只读场景）
3. **TS 沙箱**（远期）：独立 Node 子进程，不在 P2/P3 范围

### 17.7 测试与验收

| Executor | 单测要点 | 集成要点 |
|----------|---------|---------|
| Http | URL 白名单、env 插值、SSRF mock、2xx/4xx body 解析 | mock Policy server 阻断 PreToolUse |
| Prompt | `$ARGUMENTS` 替换、ok/schema 失败、不触发 UserPromptSubmit | UserPromptSubmit deny 端到端 |
| Agent | max_turns、structured output 缺失、工具过滤 | Stop block → agent 继续一轮 |

---

## 附录 A：Hook Handler 类型与应用场景

各平台（尤其 Claude Code、Cursor）的 hook 配置里，`type` 字段决定**用哪种执行后端**处理同一生命周期事件。与 §3.6.1 一致：ms-agent **兼容这些框架**，但 v1 仅原生实现 `command`；其余类型见下表「ms-agent 规划」列。

### A.1 四种 Handler 对比

| 类型 | 执行模型 | 确定性 | 典型延迟 | 社区占比（经验） |
|------|---------|--------|---------|-----------------|
| **command** | 子进程 + stdin/stdout JSON | 高 | 毫秒～秒级 | **>80%** |
| **http** | POST 事件 JSON 到 URL，解析响应 | 高（依赖远端） | 百毫秒～秒级 | 企业 / Partner 为主 |
| **prompt** | 将 hook input 填入 prompt，调 LLM 判断 | 低～中 | 秒级 | 少量 |
| **agent** | spawn 短生命周期子 agent 多步验证 | 中 | 秒～分钟级 | 很少 |

### A.2 command（shell / 可执行文件）

**机制：**

```
生命周期事件 → fork 子进程 → stdin(JSON) → 脚本 → stdout(JSON) 或 exit 2
```

**典型场景：**

| 场景 | 示例 |
|------|------|
| 硬规则拦截 | 拒绝 `rm -rf`、拒绝 `pip install` |
| 自动格式化 | `PostToolUse` 后对刚写入的 `.py` 跑 `black` |
| 本地审计 | 追加 tool 调用日志到 `/var/log/agent-audit.jsonl` |
| Secret 扫描 | 脚本内用 regex / trufflehog 扫描命令参数 |
| 会话初始化 | `SessionStart` 时检查环境变量、git 状态 |

**为何作为 v1 主路径：** 与 Claude / Cursor / Hermes shell hook 协议一致，可移植、可审计、无额外 LLM 成本。

### A.3 http

**机制：**

```
生命周期事件 → HTTP POST（JSON body）→ 远端服务 → 响应 JSON（allow/deny/...）
```

**典型场景：**

| 场景 | 示例 |
|------|------|
| 企业统一策略中心 | 每次 `PreToolUse` 询问公司 Policy API 是否允许 |
| SIEM / 可观测 | 将 tool 调用异步上报 Splunk、Datadog、自建 audit 服务 |
| Secrets / 合规 SaaS | Cursor Partner 类集成：POST 到厂商治理 endpoint |
| 集中留痕 | 金融/医疗：所有 shell 必须经合规网关登记 |
| 跨团队通知 | `Stop` / `agent:end` 时 POST Slack/Teams webhook |

**与 command + curl 的区别：** 平台对 http hook 约定统一超时、鉴权头、async、响应 schema；企业可只开放 URL 白名单，无需在每台机器分发脚本。

**ms-agent 规划：** P2 `HttpHookExecutor`（§17.2）；v1 加载配置时对未启用的 `type: http` **warning + 跳过**，或文档建议用户用 shell 脚本包装同一 HTTP 调用。

### A.4 prompt

**机制：**

```
生命周期事件 → 构造策略 prompt（含 hook input）→ 调 LLM → 解析 allow/deny
```

**典型场景：**

| 场景 | 示例 |
|------|------|
| 自然语言策略 | 「只允许只读操作」— 难以用正则穷举 |
| 意图判断 | 「这条 shell 是否在执行生产部署？」 |
| Prompt 合规 | `UserPromptSubmit` 前检查是否含 PII、违规内容 |
| 轻量 guardrail | 策略频繁变更，不想维护大量 shell |

**代价：** 多一次 LLM 调用（慢、花钱、非完全确定）。**不适合**必须 100% 确定的硬安全底线（应由 `SafetyGuard` + command hook 承担）。

**ms-agent 规划：** P2 `PromptHookExecutor`（§17.3，复用 `hooks.default_model`）；Cursor `type: prompt` 共用同一后端。

### A.5 agent

**机制：**

```
生命周期事件 → 启动子 agent（只读/受限工具）→ 多步推理 → 返回决策
```

**典型场景：**

| 场景 | 示例 |
|------|------|
| 复杂合规 | 子 agent 读内部 runbook + 当前 diff，判断 DB migration 是否允许 |
| 多文件上下文 | 需结合多个文件状态才能决定能否执行某命令 |
| 动态威胁分析 | 不仅看单条命令，还要看 branch、近期 commits、CI 状态 |

**与 prompt 的区别：** agent hook 可**调用工具、读仓库**，不仅是一次 LLM 问答。

**ms-agent 规划：** P3 `AgentHookExecutor`（§17.4），对接 ms-agent 子 agent / `AgentTool`，主要用于 Stop 验证。

### A.6 选型建议（产品 / 实施）

```
需要 100% 确定、可审计？     → command（+ SafetyGuard）
策略在远端、组织统一治理？   → http（P2，§17.2）
策略难脚本化、可接受 LLM？   → prompt（P2，§17.3）
需多步读库/读文件才能判断？ → agent（P3，§17.4）
```

---

## 附录 B：Hermes 三套 Hook 体系与功能关系

Hermes Agent 的 hook 常口语说成「两套」，实为 **三套**，按**注册方式、运行范围、能否阻断 agent 循环**划分。理解差异有助于 ms-agent 对齐 **Hermes shell hooks**（v1）而**不**追求原生执行 Python plugin hook 或 Gateway hook。

### B.1 三套体系总览

| 体系 | 注册方式 | 配置位置 | 语言 | 运行范围 | 能否 block 工具 |
|------|---------|---------|------|---------|----------------|
| **Plugin hooks** | `ctx.register_hook()` in `register(ctx)` | Python plugin 内 | Python 进程内 | CLI + Gateway + Cron | ✅ `pre_tool_call` 等 |
| **Shell hooks** | `hooks:` in `config.yaml` | `~/.hermes/config.yaml` | 任意（子进程） | CLI + Gateway | ✅ 同 Plugin |
| **Gateway hooks** | `HOOK.yaml` + `handler.py` | `~/.hermes/hooks/<name>/` | Python（Gateway 内） | **仅 Gateway** | ❌（观察/副作用） |

### B.2 为何拆成多套？

**1. 信任边界**

| 体系 | 信任模型 |
|------|---------|
| Shell hooks | 子进程隔离；每个 `(event, command)` 首次需用户 consent（`hooks_auto_accept` / `--accept-hooks`） |
| Plugin hooks | 与 agent 同进程；靠 `plugins.enabled` 白名单显式启用 |
| Gateway hooks | 信任 `~/.hermes/hooks/` 目录；错误只 log，不 crash Gateway |

**2. 事件命名空间不同**

**Plugin + Shell** 共用 `VALID_HOOKS`（agent 循环）：

```
pre_tool_call, post_tool_call, pre_llm_call, post_llm_call,
on_session_start, on_session_end, on_session_reset, on_session_finalize,
subagent_stop, pre_gateway_dispatch, pre_approval_request, ...
```

**Gateway hooks** 使用 Gateway 生命周期事件：

```
gateway:startup, session:start, session:end, session:reset,
agent:start, agent:step, agent:end, command:*, ...
```

CLI 没有「Telegram 用户发消息」等上下文，故 Gateway hooks **故意不在 CLI 加载**。

**3. 设计目标不同**

| 目标 | 适用体系 |
|------|---------|
| 拦截危险工具、注入 turn context | Plugin / Shell |
| 运维不写 Python、只要一个脚本 | Shell |
| 插件作者与 `register_tool` 同包发布 | Plugin |
| Gateway 启动巡检、IM 告警、slash 命令审计 | Gateway hooks |

### B.3 功能关系图

```
                    ┌─────────────────────────────────────┐
                    │     Agent 循环（CLI + Gateway）      │
                    │                                     │
   Python plugin ──►│  Plugin hooks ──┐                   │
                    │                 ├──► invoke_hook()  │
   config.yaml  ──►│  Shell hooks  ──┘      分发器       │
                    │         │                           │
                    │         ▼                           │
                    │  pre_tool_call / pre_llm_call / ... │
                    │  （可 block / 可注入 context）       │
                    └─────────────────────────────────────┘

                    ┌─────────────────────────────────────┐
                    │     仅 Gateway（Telegram/Discord/…）   │
   ~/.hermes/hooks/ │  Gateway hooks（HOOK.yaml）           │
                    │  gateway:startup / agent:step / ...   │
                    │  （观察为主，不 block 工具循环）       │
                    └─────────────────────────────────────┘
```

### B.4 Plugin hooks 与 Shell hooks 的协作

二者经 **同一 `invoke_hook()` 分发器**：

1. **执行顺序**：先 Plugin hooks（按插件发现顺序），后 Shell hooks  
2. **`pre_tool_call` 阻断**：第一个有效 `{"action":"block"}` / `{"decision":"block"}` 胜出  
3. **能力重叠**：同一事件可既有 Plugin 又有 Shell；Plugin 适合复杂逻辑，Shell 适合运维一键脚本  

Hermes 文档中的 **BOOT.md 启动清单** 是 Gateway hooks 的典型模式：在 `gateway:startup` 后台起一个 one-shot agent 执行 `~/.hermes/BOOT.md` 里的自然语言指令（与 Plugin/Shell 的 `pre_tool_call` 无关）。

### B.5 能力对照（节选）

| 能力 | Plugin | Shell | Gateway |
|------|--------|-------|---------|
| 阻断 `pre_tool_call` | ✅ | ✅ | ❌ |
| `pre_llm_call` 注入 context | ✅ | ✅ | ❌ |
| `post_tool_call` 后处理（format） | ✅ | ✅ | ❌ |
| Gateway 启动时跑 BOOT 检查 | ❌ | ❌ | ✅ |
| `agent:step` 超过 N 步发 Telegram 告警 | ❌ | ❌ | ✅ |
| 记录所有 `/command` 使用 | 部分 | 部分 | ✅（`command:*`） |
| 子进程隔离 | ❌ | ✅ | ❌（Gateway 进程内） |

### B.6 与 ms-agent 设计的映射

| Hermes | ms-agent 策略 |
|--------|--------------|
| **Shell hooks** | v1 **主兼容路径**（`HermesShellLoader` + `HookExecutor`） |
| **Plugin hooks** | 不执行 Python `register_hook()`；等价逻辑用 shell 或 ms-agent 自有 plugin |
| **Gateway hooks** | v1 不实现（无 IM Gateway 产品面）；若未来有 Gateway，可单列 `gateway:*` 事件族 |
| block 双格式 | `ResponseAdapter` 同时识别 `decision:block` 与 `action:block`（§3.6） |

### B.7 常见误解澄清

| 误解 | 说明 |
|------|------|
| 「兼容 Hermes = 能跑 Hermes Python plugin」 | ❌ Plugin hook 是 Hermes 运行时 API；兼容的是 **shell hook + 配置语义** |
| 「Gateway hook 也能拦工具」 | ❌ Gateway hooks 不进入 `invoke_hook()` 的 block 路径 |
| 「Shell 和 Plugin hook 是两套互斥系统」 | ❌ 互补，同一事件可叠加；Plugin 优先 |
| 「Hermes 只有两套」 | 通常指 **进程内（Plugin）vs 可配置（Shell/Gateway）**；严格说是三套 |

---

## 附录 C：实现状态与跨文档约定

permission 模块**已在当前仓库实现**（`ms_agent/permission/`）。Hooks **P0 + P1 已实现**；下表标注剩余 P2/P3 项。

| # | 项 | 状态 | 文档位置 |
|---|-----|------|---------|
| 4 | ResponseAdapter 统一解析 | ✅ | §8.2 |
| 5 | 子进程 env | ✅ | §8.4 |
| 6 | 多 hook 合并 | ✅ | §8.3 |
| 7 | `resolve_hook_permission_decision` | ✅ | §10.6 |
| 8 | pattern_matcher 提取 | ✅ | §6.1 |
| 9 | fail_closed（全局 + per-handler） | ✅ | §8.6 |
| 10 | permission 交叉引用 | 待补 `permission-design.md` §2 | §10 |
| 11 | HttpHookExecutor | P2 | §17.2 |
| 12 | PromptHookExecutor | P2 | §17.3 |
| 13 | AgentHookExecutor | P3 | §17.4 |
| 14 | `enabled_executors` 扩展后端注册 | 解析✅ / http·prompt·agent 执行器 P2/P3 | §17.1 |
| 15 | `SubagentStop` 运行时挂点 | P2 | §4.1 |
| 16 | `hooks doctor` | P2 | §16.3 |

**`permission-design.md` 建议补丁** — 在 §2 判定流程中，将原步骤 2 拆为：

```
  ├─ 1.5. HookRuntime.run_pre_tool_use()     ← 社区 hook（可选）
  ├─ 2. resolve_hook_permission_decision()  ← Hook allow/deny/ask × 规则层合并
  │     └─ 内部调用 PermissionEnforcer.check()（非 allow 短路整层）
  └─ 3. tool_ins.call_tool()
```

**`pass` ≠ `allow`**：社区脚本 `echo '{}'` 走完整 permission；仅 `permissionDecision: allow` / `decision: approve` 才触发免弹窗路径。

**Hook 脚本安全**：子进程 hook 等价于用户显式授权执行命令；v1 不做沙箱，依赖配置路径 + Playground 工作区隔离；与 `trust_remote_code` 无关但需在用户文档中警告。

**Cursor `beforeSubmitPrompt` 阻断**：官方 IDE 对输出 JSON 阻断支持仍在演进；ms-agent v1 按 Claude 语义实现 deny，经 `ResponseAdapter` 兼容 Cursor 字段名即可。
