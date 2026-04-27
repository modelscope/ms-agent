# Shell / Grep / Glob 与策略内核架构方案

本文档描述在 modelscope-agent 中为 **Shell**、**Grep**、**Glob** 提供统一的安全、权限、沙箱与产物管理的设计，以及与 **`feat/agent-tool-overhaul`** 分支中 **TaskManager**（后台 Agent、预留 Shell）的兼容方式。

---

## 1. 目标与边界

### 目标

- 在「同一工作区、同一沙箱视图」下，为 **Shell / Grep / Glob** 提供统一的：
  - **安全**（命令与路径约束）
  - **权限**（只读 / 写工作区 / 网络等分级）
  - **沙箱**（本地子进程 vs Docker enclave 等与现有 `CodeExecutionTool` 对齐）
  - **产物管理**（大 stdout/stderr 落盘、预览、配额）
- **默认 `allow_list`（允许根路径）包含 `output_dir`**（及其规范化的绝对路径），可配置追加其它根。

### 边界

- **不替代** `FileSystemTool` 的精确编辑与读缓存等语义；Shell 面向构建、包管理、复杂管道。
- **Grep / Glob** 作为**只读发现面**的独立工具，减少对裸 shell 的依赖；复杂 `find -exec` 等仍可由受控 Shell 在更高权限模式下完成（若产品允许）。

---

## 2. 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│  Tool Facade 层                                              │
│  ShellTool │ GrepTool │ GlobTool  （独立 JSON Schema）        │
└────────────┬───────────────────────────────┬────────────────┘
             │                               │
┌────────────▼───────────────────────────────▼────────────────┐
│  WorkspacePolicyKernel（策略内核，纯逻辑、可单测）              │
│  - roots: 默认含 canonical(output_dir)，可配置追加            │
│  - allow_list / deny_list 合并与优先级                         │
│  - resolve_path(rel|abs) → 必须在 allow_roots 下               │
│  - classify(op): read | search | mutate | exec | network_hint │
└────────────┬────────────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────────────┐
│  SandboxRuntime（执行面，可替换实现）                         │
│  - LocalProcessRuntime（asyncio subprocess，cwd=workspace）   │
│  - EnclaveRuntime（现有 ms_enclave / CodeExecutionTool 路径）  │
│  - 会话级 sandbox_id / working_dir 与挂载点一致                │
└────────────┬────────────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────────────┐
│  ArtifactManager（产物管理）                                  │
│  - 超阈值 stdout/stderr → 落盘 + preview + 相对路径引用         │
│  - 按 task_id / tool_call_id 分目录                           │
│  - TTL / 总配额（建议：output_dir/.ms_agent_artifacts/）       │
└─────────────────────────────────────────────────────────────┘
```

**原则**：Grep/Glob 的**主路径**不是「拼一条 shell 给模型」；内部可调用 `rg` 或文件系统 walk，但必须经过 **PolicyKernel** 与 **SandboxRuntime**，输出经 **ArtifactManager**。

---

## 3. WorkspacePolicyKernel（共享策略内核）

### 3.1 默认 allow_list（允许根集合）

- 初始化：`allow_roots = { canonical_abs(output_dir) }`。
- 配置可追加，例如：`tools.code_executor.extra_allow_roots` 或 `tools.workspace_policy.allow`（列表），合并去重。
- Shell / Grep / Glob 涉及的 **`path`、`cwd`、搜索根目录** 均先执行 `resolve_under_allow_roots()`；失败则**拒绝**并返回结构化错误（不静默改路径到其它目录）。

### 3.2 权限与操作分类（建议）

| 类别 | 示例 | Shell | Grep | Glob |
|------|------|-------|------|------|
| read | 读取工作区内文件 | 受模式 + 策略约束 | ✓ | ✓ |
| search | 内容/文件名发现 | 可引导至 Grep/Glob | ✓ | ✓ |
| mutate | rm、chmod、git 写入等 | 需 `workspace_write` | — | — |
| network | curl、pip 等 | 需显式 **network** 能力位 | — | — |

Shell 在 **`read_only`** 模式下：仅允许白名单类命令（如 `git status`/`diff`/`log`、只读参数的 `rg` 等），并对重定向、写入工作区外等行为做拒绝或降级（可用前缀表 + 危险模式黑名单，必要时辅以轻量解析）。

### 3.3 Shell 安全补充

- **固定 cwd**：默认 `workspace_root`（与 `output_dir` 或沙箱内挂载点一致）。
- **环境变量**：最小集或白名单继承；避免将宿主敏感变量原样传入。
- **命令预处理**：与现有 `CodeExecutionTool.shell_executor` 思路一致——含 `| && ; > <` 等时使用 `sh -lc` 与安全 quoting；另加**命令长度上限**、**可配置的危险构造限制**（如嵌套命令替换，按产品分级）。
- **（暂时不做）** 与 `FileSystemTool` 的「写前必读 / staleness」策略对齐：对会修改工作区文件的 Shell 子类共享元数据（若产品需要强一致）。

---

## 4. SandboxRuntime（共享沙箱）

- **会话级**：每个 Agent 运行周期内一个 `SandboxSession`（或复用现有 `sandbox_id`）。
- **Shell / Grep / Glob** 共用同一 **`working_dir` / 挂载视图** 与同一 **`SandboxRuntime` 实现**（本地 `asyncio` 子进程 vs Docker enclave，由 `implementation: sandbox | python_env` 等与现有一致）。
- **Grep**：在 enclave 内调用 `rg` 或使用宿主 `ripgrep` 库（由部署二选一）；**Glob**：在策略解析后的根上做目录遍历或 `pathspec`，避免默认可执行任意 `find -exec`。

---

## 5. ArtifactManager（产物管理）

- **阈值**：例如 stdout+stderr 合计超过 N KB 则 spill 至  
  `{output_dir}/.ms_agent_artifacts/{tool_name}/{task_or_call_id}.txt`（路径可配置）。
- **返回**：JSON 中包含 `preview`（首尾若干字符/行）、`artifact_path`（相对 `output_dir`）、`truncated: true`。
- **与 TaskManager 配合**：后台任务完成时，`TaskManager.complete(task_id, result)` 的 `result` 宜为「短摘要 + artifact 路径」，避免通知与下一轮上下文被撑爆。

---

## 6. GrepTool / GlobTool（独立工具、共享内核）

- **输入**：结构化字段（如 pattern、path、glob、head_limit、offset、output_mode），不把「整条 shell」作为唯一 API。
- **实现**：内部调用 `SandboxRuntime.exec_rg(...)` 或在策略内核限定根上的 glob 遍历；**禁止**由用户可控字符串直接拼接未校验的 shell。
- **共享**：同一 `WorkspacePolicyKernel` + `SandboxRuntime` + `ArtifactManager`（由 `ToolManager` 或执行类工具在初始化时注入）。
- **注册**：在 `ToolManager` 中作为独立 `ToolBase`（可一个 server 多个 tool，或两个 server）；与 `file_system` 解耦，保持 `file_system` 精简。

---

## 7. 与 `feat/agent-tool-overhaul` 的 Task 体系兼容

### 7.1 分支中的现状（摘要）

- **`TaskManager`**（`ms_agent/utils/task_manager.py`）：进程级后台任务注册表；`BackgroundTask` 中 **`task_type` 注释已包含 `'agent' | 'shell'`**。
- **`AgentTool`**：`run_in_background` 时 `register(task_type='agent', proc=mp.Process, ...)`，watcher 在子进程结束后调用 `complete` / `fail`；`LLMAgent` 通过 `set_task_manager` 注入同一 `TaskManager`，每轮 `drain_notifications()` 将完成事件注入对话。

### 7.2 Shell 后台（与 Agent 对称）

**建议接口**

- **同步**：`shell_executor(command, timeout)` → 行为与现网接近，但走 PolicyKernel + ArtifactManager。
- **后台**：增加 `run_in_background: bool`（或等价命名）， **`__call_id`**（与 `AgentTool` 注入一致，便于对账与「推后台」扩展）。

**后台行为**

1. `task_id = task_manager.register(task_type='shell', tool_name='shell_executor', description=command[:200], proc=...)`
2. `proc` 可为 **`asyncio.create_subprocess_*` 返回的 `Process`**（与 Agent 的 `mp.Process` 不同，需在 **`TaskManager.kill` / `kill_all` 中扩展**：对 `asyncio.subprocess.Process` 调用 `kill()` / `terminate()`，并处理已结束进程）。
3. `asyncio.create_task(watcher)`：等待结束 → `ArtifactManager.maybe_spill` → `await task_manager.complete(task_id, result_str)`（失败则 `fail`）。

**立即返回 JSON**（与 Agent 后台对齐，便于统一文档与客户端）：

```json
{
  "status": "async_launched",
  "task_id": "<id>",
  "tool_name": "shell_executor"
}
```

### 7.3 LLMAgent 接线

- 与 overhaul 一致：构造 `TaskManager()`，遍历 `extra_tools`，若实现 **`set_task_manager(self.task_manager)`** 则注入。
- **`LocalCodeExecutionTool` / 未来的 `SecureShellTool`** 实现 `set_task_manager`，与 `AgentTool` 共享同一 `TaskManager` 实例。

### 7.4 长同步 Shell → Escape 到后台

- 与 `AgentTool._run_sync_escapable` 类似：同步 Shell 带 `sync_timeout_s`，超时或显式信号后取消当前子进程并改为 `register(task_type='shell', ...)` 后台重跑或仅保留已产出部分（产品二选一）。
- 若存在 **TaskControlTool** 类机制，可复用「`__call_id` + escape 事件」模式，Shell 侧维护 `call_id → Process` 映射以支持 **kill / escape**。

### 7.5 兼容对照表

| 能力 | overhaul 行为 | 本方案落点 |
|------|----------------|------------|
| 后台 Agent | `register(task_type='agent', proc=Process)` | 不变 |
| 预留 Shell | `task_type` 含 `'shell'` | `shell_executor(run_in_background=true)` 走同一 register / complete / fail |
| 回合内通知 | `drain_notifications()` | Shell 完成同样入队 |
| Kill / 清理 | `kill` / `kill_all` | 扩展支持 asyncio 子进程；watcher `finally` 释放资源 |

---

## 8. 配置示例（OmegaConf / YAML 意向）

```yaml
tools:
  workspace_policy:
    allow_roots: []              # 追加；默认已含 output_dir
    deny_globs: ['**/.git/**']
  code_executor:
    implementation: python_env   # or sandbox
    shell:
      default_mode: workspace_write   # read_only | workspace_write
      max_output_kb: 256
      wall_time_s: 900
    grep:
      default_head_limit: 250
    glob:
      max_files: 100
```

---

## 9. 实施顺序建议

1. 抽出 **`WorkspacePolicyKernel`** + 单元测试（路径解析、默认 `output_dir`、追加 allow）。
2. 实现 **`ArtifactManager`**，接到现有 `shell_executor` 返回（先本地工具、后接沙箱）。
3. 将 **`TaskManager`**（overhaul）合入主线并 **扩展 `kill` 支持 `asyncio.subprocess.Process`**。
4. **`LocalCodeExecutionTool.set_task_manager` + `run_in_background` 的 `shell_executor`**。
5. 新增 **GrepTool / GlobTool** façade，共享上述内核与运行时。
6. 更新文档与系统提示：默认 **发现用 Grep/Glob，构建用 Shell，改文件用 file_system**。

---

## 10. 设计取舍小结

- **Shell**：强约束的通用执行面 + 后台，与 **TaskManager** 统一生命周期与通知。
- **Grep / Glob**：独立 Schema、只读、易截断，与 Shell **共享策略与沙箱**，避免把一切搜索都绑在一条 shell 字符串上。
- **默认 allow_roots 含 `output_dir`**：与现有 Agent 工作区模型一致，减少越权访问宿主路径的风险。

---

## 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-13 | 初版：根据设计与 `feat/agent-tool-overhaul` 中 TaskManager / AgentTool 后台模型整理成文。 |
| 2026-04-13 | 实现落地：见下文「实现映射」。 |

## 11. 实现映射（代码位置）

| 组件 | 路径 |
|------|------|
| WorkspacePolicyKernel | `ms_agent/utils/workspace_policy.py` |
| ArtifactManager | `ms_agent/utils/artifact_manager.py` |
| TaskManager | `ms_agent/utils/task_manager.py` |
| Shell 策略 / 产物 / 后台 | `ms_agent/tools/code/local_code_executor.py`（`set_task_manager`、`shell_executor`） |
| Grep / Glob | `ms_agent/tools/filesystem_tool.py` 中 `grep` / `glob` 工具（与 `read_file` / `edit_file` / `write_file` 同属 `file_system` server；用 `tools.file_system.include` / `exclude` 控制）。可选键：`grep_timeout_s`、`grep_head_limit`、`glob_max_files`；`include` 短名 `read` / `edit` / `write` 分别等价 `read_file` / `edit_file` / `write_file`。 |
| `__call_id` 注入 shell | `ms_agent/tools/tool_manager.py` |
| TaskManager 与通知 | `ms_agent/agent/llm_agent.py`（`prepare_tools` / `cleanup_tools` / `_append_task_notifications`） |
| 单测 | `tests/utils/test_workspace_policy.py` |

**未在本阶段实现**：文档 §7.4 长同步 Shell escape 到后台；Docker `CodeExecutionTool` 侧 shell 与策略对齐（仍沿用原沙箱实现）。
