# 权限管控系统设计文档

> 参考 Claude Code 权限系统设计（`permissions.ts` + `bashPermissions.ts` + `pathValidation.ts` + `sedValidation.ts`）
>
> 本文档是权限管控模块的**完整可执行方案**，涵盖双层架构、外层用户意图管控、内层安全底线、Shell 路径级校验、前后端交互协议、现有代码迁移等全部内容。

---

## 目录

- [1. 现状分析](#1-现状分析)
- [2. 双层权限架构](#2-双层权限架构)
- [3. 外层：PermissionEnforcer（用户意图层）](#3-外层permissionenforcer用户意图层)
- [4. 内层：SafetyGuard（安全底线层）](#4-内层safetyguard安全底线层)
- [5. Shell 命令路径级校验](#5-shell-命令路径级校验)
- [6. 命令注册表：PATH_EXTRACTORS](#6-命令注册表path_extractors)
- [7. 路径校验流程](#7-路径校验流程)
- [8. 危险路径硬拦截](#8-危险路径硬拦截)
- [9. Safe Wrapper 剥离](#9-safe-wrapper-剥离)
- [10. 输出重定向、进程/命令替换与复合命令校验](#10-输出重定向与进程替换校验)
- [11. 共享基础设施](#11-共享基础设施)
- [12. 集成点与代码变更](#12-集成点与代码变更)
- [13. 现有代码迁移：WorkspacePolicyKernel](#13-现有代码迁移workspacepolicykernel)
- [14. YAML 配置格式（统一）](#14-yaml-配置格式统一)
- [15. 文件结构](#15-文件结构)
- [16. 与 Claude Code 的对比](#16-与-claude-code-的对比)
- [17. 验证方式](#17-验证方式)
- [18. 实现审查：已知问题与待办](#18-实现审查已知问题与待办)
- [附录 A：parse_pattern_command 通用实现](#附录-aparse_pattern_command-通用实现)
- [附录 B：完整命令操作类型对照表](#附录-b完整命令操作类型对照表)

---

## 1. 现状分析

### 1.1 当前权限现状

- **统一拦截已就位**：`ToolManager.single_call_tool()` 中注入双层权限检查（SafetyGuard + PermissionEnforcer）
- **WorkspacePolicyKernel 已迁移删除**：安全职责归并到 `SafetyGuard`，功能职责（workspace cwd、deny_globs）提取为轻量 `WorkspaceContext`（`ms_agent/utils/workspace_context.py`）
- **覆盖完整**：SafetyGuard 校验 `shell_executor`、`read_file`、`write_file`、`edit_file`、`grep`、`glob` 六类工具的路径安全

### 1.2 原 WorkspacePolicyKernel 能力迁移对照

| 原调用者 | 原方法 | 迁移去向 | 状态 |
|--------|-----------|------|------|
| `filesystem_tool.py` | `resolve_under_roots()` | SafetyGuard + `validate_path()` | ✅ 已迁移 |
| `filesystem_tool.py` | `deny_globs` / `workspace_root` | `WorkspaceContext.deny_globs` / `.root` | ✅ 已迁移 |
| `filesystem_tool.py` | `path_is_allowed()` | SafetyGuard 在 tool_manager 层统一检查 | ✅ 已删除 |
| `local_code_executor.py` | `assert_shell_command_allowed()` | SafetyGuard → `ShellPathValidator.check()` | ✅ 已迁移 |
| `local_code_executor.py` | `workspace_root` (subprocess cwd) | `WorkspaceContext.root` | ✅ 已迁移 |
| 两处 | `_shell_looks_network()` | `PermissionConfig._DEFAULT_BLACKLIST` | ✅ 已迁移 |
| — | `iter_files_under()` | 已删除（无外部调用者） | ✅ 已删除 |

### 1.3 设计目标

1. **统一入口**：所有工具调用在 `ToolManager.single_call_tool()` 中经过统一权限检查
2. **双层分离**：用户可选择放行的"意图层" + 不可绕过的"安全底线层"
3. **交互式确认**：支持 CLI 和 Web 两种场景下的用户确认流程
4. **精细化管控**：shell 命令做到参数级路径提取和操作类型区分
5. **消除重复**：`WorkspacePolicyKernel` 的能力迁移到新体系后删除，不保留两套代码

---

## 2. 双层权限架构

```
┌─────────────────────────────────────────────────────────┐
│  PermissionEnforcer（外层 · 用户意图层）                   │
│  位置：ToolManager.single_call_tool() 入口               │
│  职责：用户是否允许这个操作？                               │
│  特点：可配置、可编辑、可被用户 allow_always 覆盖           │
│  规则来源：YAML whitelist/blacklist + PermissionMemory    │
├─────────────────────────────────────────────────────────┤
│  SafetyGuard（内层 · 安全底线层）                          │
│  位置：ToolManager.single_call_tool()，权限检查最前面      │
│  职责：无论用户怎么选，这些操作绝对不允许                     │
│  特点：不可被用户绕过，即使 mode=auto 也生效                │
│  规则来源：YAML safety_rules + 硬编码兜底 + 路径级校验      │
│  前身：WorkspacePolicyKernel（重构后纳入统一体系）          │
└─────────────────────────────────────────────────────────┘
```

**关键区别：**
- 外层 `PermissionEnforcer`：用户选择 `allow_always` 后，后续匹配的调用不再询问
- 内层 `SafetyGuard`：`rm -rf /`、访问 `/etc/passwd` 等操作，即使用户加了 `code_executor---*` 白名单也会被拦截

**共享基础设施：**
- 两层共用 `PermissionMatcher` 的通配符匹配逻辑，规则格式统一为 `server---tool:content_pattern`
- 两层的规则均从 YAML 统一加载，但标记不同的 `layer` 属性
- `WorkspacePolicyKernel` 的现有逻辑（`deny_globs`、`assert_shell_command_allowed`、`resolve_under_roots`）重构为 `SafetyGuard` 的一部分，规则格式对齐

**判定流程：**
```
工具调用进入 ToolManager.single_call_tool()
  │
  ├─ 1. SafetyGuard.check()  ← 内层先行，不可绕过
  │     ├─ 通用安全规则匹配（YAML safety_rules）
  │     ├─ 工具特化检查：
  │     │   ├─ code_executor---shell_executor → ShellPathValidator.check()
  │     │   ├─ file_system---write_file/edit_file → validate_path(..., 'write')
  │     │   ├─ file_system---read_file → validate_path(..., 'read')
  │     │   └─ file_system---grep/glob → validate_path(..., 'read')
  │     ├─ deny → 直接拒绝
  │     └─ ask → resolve_ask() 按模式解析（见下文）
  │
  ├─ 1.5. resolve_ask()  ← ask 模式解析层
  │     ├─ auto 模式 → 按 category 分类决策（allow/deny）
  │     ├─ strict 模式 → 全部 deny
  │     └─ interactive 模式 → 保持 ask，交给 enforcer/handler
  │
  ├─ 2. PermissionEnforcer.check()  ← 外层用户意图
  │     ├─ blacklist match → deny（任何模式均不可绕过）
  │     ├─ mode in (auto, strict) → allow（SafetyGuard 已做安全保障；仍受 blacklist 约束）
  │     ├─ whitelist match → allow
  │     ├─ session memory match → allow
  │     ├─ persistent memory match → allow
  │     └─ 其余 → handler.ask()（询问用户）
  │
  └─ 3. tool_ins.call_tool()  ← 通过两层检查后执行
```

**三种模式说明：**

| 模式 | SafetyGuard `ask` 处理 | Enforcer 行为 | 适用场景 |
|------|----------------------|--------------|----------|
| `auto` | 按 category 分类：input 替换→allow, output 替换/解析失败/cd+write/变量展开→deny, 读超范围→看 read_policy | **blacklist deny** → 其余 allow（无弹窗） | 容器/沙箱/无人值守 |
| `strict` | 全部 → deny | **blacklist deny** → 其余 allow | 高安全要求、无沙箱、无人值守 |
| `interactive` | 保持 ask → 交给 handler | 完整流程（blacklist→whitelist→memory→handler.ask） | 有人值守（CLI/Web/TUI） |

---

## 3. 外层：PermissionEnforcer（用户意图层）

### 3.1 PermissionConfig (`config.py`)

从 agent YAML 或 settings 中解析 `permission` 段：

```python
@dataclass(frozen=True)
class PermissionConfig:
    mode: Literal['auto', 'strict', 'interactive']  # 兼容旧名 restricted → interactive
    whitelist: tuple[str, ...]      # 允许规则
    blacklist: tuple[str, ...]      # 拒绝规则
    safety: SafetyConfig            # 安全底线配置（传给 SafetyGuard）
```

- 白名单/黑名单格式：`server_name---tool_name`，支持 `*` 通配符
- shell 命令级：支持 `code_executor---shell_executor:command_pattern` 格式
- 示例：`file_system---read_*`、`web_search---*`、`code_executor---shell_executor:pip *`

### 3.2 PermissionEnforcer (`enforcer.py`)

```python
@dataclass(frozen=True)
class PermissionDecision:
    action: Literal['allow', 'deny', 'ask']
    reason: str
    updated_args: dict | None = None  # action == 'allow' 且用户修改了参数时

class PermissionEnforcer:
    def __init__(self, config: PermissionConfig, handler: PermissionHandler, memory: PermissionMemory)
    async def check(self, tool_name: str, tool_args: dict) -> PermissionDecision
```

判定流程（参考 Claude Code 的 `hasPermissionsToUseToolInner` 多步管线）：
1. blacklist match → `deny`（**不可绕过**，含 `auto` / `strict`；参考 Claude Code 的 `alwaysDenyRules`）
2. `mode in ('auto', 'strict')` → 直接 `allow`（SafetyGuard + ask_resolver 已保障安全；**不**跳过 blacklist）
3. whitelist match → `allow`（参考 `alwaysAllowRules`）
4. session memory match → `allow`（会话内 `allow_session` 记录）
5. persistent memory match → `allow`（`PermissionMemory` 持久化规则）
6. 其余 → 调用 `handler.ask()`，传入自动生成的 suggestions
7. 用户选择 `modify` 时，返回 `updated_args` 供 `ToolManager` 使用修改后的参数执行

### 3.3 PermissionHandler (`handler.py`)

用户在 `interactive` 模式下遇到非白名单工具时，提供 5 种细粒度选择：

```python
class PermissionAction(str, Enum):
    ALLOW_ONCE = 'allow_once'           # 仅允许本次调用
    ALLOW_SESSION = 'allow_session'     # 本次会话中允许所有同类调用
    ALLOW_ALWAYS = 'allow_always'       # 永久加入白名单（持久化）
    DENY = 'deny'                       # 拒绝本次调用
    MODIFY = 'modify'                   # 用户修改工具参数后执行

@dataclass(frozen=True)
class PermissionResponse:
    action: PermissionAction
    updated_args: dict | None = None    # action == MODIFY 时，用户修改后的参数
    pattern: str | None = None          # action == ALLOW_ALWAYS 时，用户确认/编辑的通配符模式
    feedback: str | None = None         # 用户附加的反馈信息

class PermissionHandler(Protocol):
    async def ask(self, tool_name: str, tool_args: dict,
                  context: str, suggestions: list[str] | None = None) -> PermissionResponse
```

#### 3.3.1 AutoPermissionHandler

直接返回 `action=ALLOW_ONCE`（auto 模式下不会被调用，但作为兜底）。

#### 3.3.2 CLIPermissionHandler

交互式 CLI 菜单，对标 Claude Code 的 Select 组件：

```
╭─ Permission Required ──────────────────────────╮
│ Tool: code_executor---shell_executor            │
│ Args: {"command": "pip install requests"}       │
│                                                 │
│ > [y] 允许本次                                   │
│   [s] 本次会话中允许所有 shell_executor 调用       │
│   [a] 以后都允许 code_executor---shell_executor   │
│   [e] 编辑命令后执行                              │
│   [n] 拒绝                                       │
╰─────────────────────────────────────────────────╯
```

**`allow_always` 可编辑模式**（参考 Claude Code 的 `yes-prefix-edited` 选项）：

用户选择 `a` 后，系统根据当前工具名和参数自动生成一个建议模式，用户可以编辑：

```
╭─ 添加白名单规则 ─────────────────────────────────╮
│ 以后不再询问匹配以下模式的调用：                      │
│                                                   │
│ > code_executor---shell_executor:ls *█             │
│                                                   │
│ 回车确认 / 编辑后回车 / Esc 取消                     │
╰───────────────────────────────────────────────────╯
```

建议模式生成示例：
- `shell_executor` + `{"command": "ls -la"}` → 建议 `code_executor---shell_executor:ls *`
- `shell_executor` + `{"command": "pip install requests"}` → 建议 `code_executor---shell_executor:pip *`
- `read_file` + `{"path": "/src/main.py"}` → 建议 `file_system---read_file`
- `web_search` + 任意参数 → 建议 `web_search---*`

用户可以自由编辑模式来控制粒度：
- 更宽松：`code_executor---shell_executor` → 所有 shell 命令都放行
- 更精确：`code_executor---shell_executor:pip install *` → 仅 pip install 放行

#### 3.3.3 WebPermissionHandler（前后端交互协议）

后端 agent 在工具调用过程中需要暂停执行、等待前端用户确认，采用 **Future 挂起 + 事件推送 + REST 回调** 模式：

```python
class WebPermissionHandler(PermissionHandler):
    def __init__(self, event_emitter: EventEmitter, timeout: float = 120.0):
        self._pending: dict[str, asyncio.Future[PermissionResponse]] = {}
        self._event_emitter = event_emitter
        self._timeout = timeout

    async def ask(self, tool_name: str, tool_args: dict,
                  context: str, suggestions: list[str] | None = None) -> PermissionResponse:
        request_id = uuid4().hex
        future: asyncio.Future[PermissionResponse] = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        # 1. 向流式通道推送权限请求事件
        self._event_emitter.emit(PermissionRequestEvent(
            request_id=request_id,
            tool_name=tool_name,
            tool_args=tool_args,
            suggestions=suggestions or [],
        ))

        # 2. 挂起等待前端回传决策
        try:
            return await asyncio.wait_for(future, timeout=self._timeout)
        except asyncio.TimeoutError:
            return PermissionResponse(action=PermissionAction.DENY,
                                      feedback='Permission request timed out')
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, request_id: str, response: PermissionResponse) -> None:
        future = self._pending.get(request_id)
        if future and not future.done():
            future.set_result(response)
```

**前后端交互流程：**

```
Backend (agent)                          Frontend
     │                                       │
     │──── SSE/Stream: permission_request ───>│  ← 推送权限请求事件
     │     {                                  │
     │       type: "permission_request",      │
     │       request_id: "abc123",            │
     │       tool_name: "code_executor---     │
     │                   shell_executor",     │
     │       tool_args: {command: "ls -la"},  │
     │       suggestions: [                   │
     │         "code_executor---              │
     │          shell_executor:ls *"          │
     │       ],                               │
     │       options: ["allow_once",           │
     │         "allow_session",               │
     │         "allow_always", "modify",      │
     │         "deny"]                        │
     │     }                                  │
     │                                        │
     │  (后端 await future，执行暂停)           │  (前端渲染权限弹窗)
     │                                        │
     │<─── POST /permission/respond ──────────│  ← 用户选择后回传
     │     {                                  │
     │       request_id: "abc123",            │
     │       action: "allow_always",          │
     │       pattern: "code_executor---       │
     │                 shell_executor:ls *"   │
     │     }                                  │
     │                                        │
     │  (future.set_result → await 返回)       │
     │  (工具调用继续执行)                      │
```

**需要预留的接口：**

1. **流式事件类型** `permission_request`：在现有 agent 流式输出协议中新增此事件类型，前端需识别并渲染权限 UI
2. **REST 接口** `POST /permission/respond`：接收前端回传的用户决策，参数为 `{request_id, action, pattern?, updated_args?, feedback?}`
3. **`EventEmitter` 抽象**：`WebPermissionHandler` 通过此接口推送事件，不直接依赖具体的流式协议（SSE/WebSocket/StreamableHTTP），由上层注入具体实现
4. **超时机制**：默认 120 秒未回复自动 deny，可配置

### 3.4 建议模式自动生成 (`suggestions.py`)

```python
def generate_suggestions(tool_name: str, tool_args: dict) -> list[str]:
    """根据工具名和参数自动生成通配符建议模式"""
```

- 参考 Claude Code 的 `PermissionUpdate.suggestions` 机制
- 例如 `code_executor---shell_executor` + `{"command": "npm run build"}` → 建议模式 `code_executor---shell_executor:npm *`
- 建议展示在 `allow_always` 选项中，用户可编辑后确认

### 3.5 PermissionMemory (`memory.py`)

持久化用户的 "always allow" 决策：

```python
@dataclass(frozen=True)
class MemoryEntry:
    pattern: str              # 通配符模式
    scope: Literal['project', 'global']
    source: Literal['user', 'plugin', 'hook']  # 规则来源
    created_at: str
```

- 项目级 `.ms_agent/permission_memory.json` + 全局级 `~/.ms_agent/permission_memory.json`
- 合并时项目级优先
- 提供 `add()` / `matches()` / `revoke()` / `list_all()` 接口
- 会话级记忆（`allow_session`）仅存内存，不持久化

---

## 4. 内层：SafetyGuard（安全底线层）

### 4.1 职责

无论用户配置了什么模式、加了什么白名单，以下操作**绝对不允许**自动放行：
- `rm -rf /`、`mkfs`、`dd if=` 等破坏性命令
- 写入 `/etc/`、`/sys/`、`~/.ssh/` 等系统敏感路径
- shell 命令操作的文件路径超出工作目录范围（write/create 操作）

### 4.2 SafetyGuard 类设计

```python
@dataclass(frozen=True)
class SafetyConfig:
    """内层安全配置（从 YAML permission.safety_rules 解析）"""
    patterns: tuple[str, ...]                        # 通用工具级拦截规则
    sensitive_paths: tuple[str, ...]                  # 写入敏感路径拦截
    dangerous_removal_paths: tuple[str, ...]          # rm/rmdir 危险路径
    read_policy: Literal['loose', 'strict'] = 'loose' # 读超范围时的兜底策略
    max_command_chars: int = 8192
    allowed_directories: tuple[str, ...] = ()         # 完全访问（读+写+create）
    read_only_directories: tuple[str, ...] = ()       # 只读访问（读允许，写/create 拒绝）

@dataclass(frozen=True)
class SafetyDecision:
    action: Literal['allow', 'deny', 'ask']
    reason: str
    category: str = ''  # ask 时标记原因类别，供 resolve_ask 分类决策

class SafetyGuard:
    def __init__(self, config: SafetyConfig, allowed_dirs: list[str],
                 read_only_dirs: list[str] = (), workspace_root: str | None = None):
        self._config = config                       # YAML 中加载的通用安全规则
        self._allowed_dirs = list(allowed_dirs)
        self._read_only_dirs = list(read_only_dirs)  # 只读目录（读允许，写/create 拒绝）
        self._workspace_root = workspace_root        # 相对路径解析基目录（与工具端 output_dir 统一）
        self._shell_validator = ShellPathValidator(   # shell 命令专用校验器
            allowed_dirs=self._allowed_dirs,
            safety_config=PathSafetyConfig(
                max_command_chars=config.max_command_chars,
                allowed_directories=tuple(self._allowed_dirs),
                read_only_directories=tuple(self._read_only_dirs),
            ),
        )
        self._matcher = PermissionMatcher()          # 共用的通配符匹配

    def check(self, tool_name: str, tool_args: dict) -> SafetyDecision:
        # 1. 通用安全规则匹配（YAML safety_rules 中的 server---tool:pattern）
        for rule in self._config.patterns:
            if self._matcher.match_with_content(rule, tool_name, tool_args):
                return SafetyDecision(action='deny', reason=f'Blocked by safety rule: {rule}')

        # 2. 工具特化检查
        if tool_name.endswith('---shell_executor'):
            return self._shell_validator.check(tool_args.get('command', ''))
        elif tool_name.endswith('---write_file') or tool_name.endswith('---edit_file'):
            return self._check_file_path(tool_args.get('path', ''), 'write')
        elif tool_name.endswith('---read_file'):
            return self._check_file_path(tool_args.get('path', ''), 'read')
        elif tool_name.endswith('---grep') or tool_name.endswith('---glob'):
            return self._check_file_path(tool_args.get('path', '.'), 'read')

        # 3. 未匹配 → 放行
        return SafetyDecision(action='allow', reason='No safety rule matched')

    def _check_file_path(self, path: str, op_type: str) -> SafetyDecision:
        cwd = self._workspace_root or os.getcwd()
        result = validate_path(path, cwd, self._allowed_dirs, op_type,
                               read_only_dirs=self._read_only_dirs)
        if not result.allowed:
            return SafetyDecision(action=result.action, reason=result.reason, category=result.category)
        return SafetyDecision(action='allow', reason='Path validation passed')
```

### 4.3 ask 分类解析：resolve_ask (`ask_resolver.py`)

SafetyGuard 返回 `ask` 时携带 `category` 字段，`resolve_ask()` 根据当前模式决定最终动作：

```python
def resolve_ask(decision: SafetyDecision, mode: str, read_policy: str = 'loose') -> SafetyDecision:
    """auto: 按 category 分类; strict: 全 deny; interactive: 保持 ask"""
```

**auto 模式策略表：**

| category | 解析为 | 理由 |
|----------|--------|------|
| `process_input_sub` | allow | `<(...)` 是读操作，风险低 |
| `process_output_sub` | deny | `>(...)` 可能绕过路径校验写入 |
| `parse_failure` | deny | 无法验证即不信任 |
| `cd_write_compound` | deny | cd 改变 cwd，静态路径验证不可靠 |
| `command_validator` | deny | 验证器明确发现可疑模式 |
| `shell_expansion` | deny | `$VAR` 路径无法静态解析 |
| `read_outside_dirs` | 由 `read_policy` 决定 | `loose`→allow, `strict`→deny |

**`read_outside_dirs` 触发条件**：读取路径不在 `allowed_dirs` 且不在 `read_only_dirs` 范围内时触发。如果路径在 `read_only_dirs` 中，`validate_path` 直接返回 allow，不会产生 `ask`。`read_policy` 是对"两个目录列表都未覆盖的读取"的兜底策略。

设计意图：auto 模式下**永不弹出交互**，所有不确定性在 SafetyGuard 返回后立即解析为确定性决策。

### 4.4 SafetyGuard 与 WorkspacePolicyKernel 的关系（已完成迁移）

`SafetyGuard` 已**完全替代** `WorkspacePolicyKernel`，后者已从代码库中删除。WPK 的职责被拆分为两部分：

**安全职责 → SafetyGuard（在 tool_manager 层统一拦截）：**

| 原 WPK 能力 | 迁移去向 | 说明 |
|-------------|---------|------|
| `resolve_under_roots()` | `SafetyGuard._check_file_path()` → `validate_path()` | 支持更多校验步骤 |
| `path_is_allowed()` | `SafetyGuard._check_file_path()` → `validate_path()` | 合并 |
| `assert_shell_command_allowed()` | `SafetyGuard.check()` → `ShellPathValidator.check()` | 精细化为 36 命令注册表 |
| `_shell_looks_network()` | `PermissionConfig._DEFAULT_BLACKLIST` | 升级为可配置的 enforcer 层策略 |
| `_shell_looks_mutating_or_network()` | `ShellPathValidator` 操作类型分类 | 精细化 |

**功能职责 → WorkspaceContext（轻量 frozen dataclass）：**

| 原 WPK 能力 | 迁移去向 | 说明 |
|-------------|---------|------|
| `workspace_root` (subprocess cwd) | `WorkspaceContext.root` | 仅提供工作目录，不含安全检查 |
| `deny_globs` (文件遍历过滤) | `WorkspaceContext.deny_globs` | 仅提供过滤模式，不含安全检查 |
| `iter_files_under()` | 已删除 | 确认无外部调用者 |

---

## 5. Shell 命令路径级校验

### 5.1 问题

`shell_executor` 工具允许 agent 执行任意 shell 命令。仅靠命令前缀匹配（如 `rm *`）无法覆盖以下风险：

- **路径越权**：`cat /etc/shadow`、`rm -rf /` — 命令本身合法，但操作的路径超出工作目录
- **路径伪装**：`rm -- -/../.claude/settings.json` — 利用 `-` 开头路径绕过 flag 过滤
- **包装器绕过**：`timeout 10 rm -rf /` — wrapper 命令遮蔽真实操作命令
- **输出重定向**：`echo "malicious" > /etc/passwd` — 命令是 `echo`，但写入了敏感路径
- **复合命令**：`cd .claude/ && mv test.txt settings.json` — 通过 `cd` 改变工作目录后操作
- **命令替换**：`echo $(rm -rf /)` — 外层命令无害，内层子命令在 shell 运行时执行
- **复合分隔符遗漏**：`true\nrm -rf /`、`ls & rm -rf /` — 换行与单个 `&` 也会启动第二条命令
- **find 侧信道**：`find . -exec rm -rf / {} \;` — 表面为 read，实际通过 `-exec` / `-delete` 写删
- **shell 展开**：`rm $HOME/.ssh/*` — 变量展开导致验证时路径和执行时路径不一致

### 5.2 ShellPathValidator 架构

```
shell 命令字符串进入 ShellPathValidator.check()
  │
  ├─ 1. 进程替换检查（区分 input/output）
  │     >(cmd) → ask(category='process_output_sub')
  │     <(cmd) → ask(category='process_input_sub')
  │
  ├─ 2. 命令替换检查（$(…) / 反引号，单引号内不展开）
  │     提取内层命令字符串 → 递归调用 check()
  │     内层 deny/ask 向上传播
  │
  ├─ 3. 复合命令拆分
  │     && / || / ; / | / 单个 & / 换行 → 拆分为独立子命令
  │     记录是否包含 cd（影响后续路径解析）
  │
  ├─ 4. 输出重定向校验（每个子命令，在 wrapper 剥离前）
  │     > / >> / &> / &>> → 提取目标路径，校验是否在允许范围
  │     /dev/null 始终放行
  │     变量展开 ($VAR) 在重定向目标中 → deny
  │
  ├─ 5. Safe Wrapper 剥离
  │     timeout / nice / nohup / time / stdbuf / env → 去掉包装
  │
  ├─ 6. 命令路径校验（核心）
  │     ├─ 识别 base command（第一个 token）
  │     ├─ find 特例：先校验 -exec/-ok/-delete 内层命令，再校验搜索路径
  │     ├─ PATH_EXTRACTORS[command](args) → 提取路径列表
  │     ├─ 危险路径硬拦截（rm -rf / 等）
  │     └─ validate_path(path, allowed_dirs, op_type, read_only_dirs) → 逐一校验
  │
  └─ 7. 返回决策
        allow（非路径命令/校验通过）/ ask（需确认）/ deny（硬拦截）
```

```python
@dataclass(frozen=True)
class PathSafetyConfig:
    """ShellPathValidator 的配置，由 SafetyGuard 从 SafetyConfig 构建后注入。"""
    max_command_chars: int = 8192
    allowed_directories: tuple[str, ...] = ()
    read_only_directories: tuple[str, ...] = ()   # 只读目录（读允许，写/create 拒绝）

class ShellPathValidator:
    """shell_executor 工具的路径级安全校验"""

    def __init__(self, allowed_dirs: list[str], safety_config: PathSafetyConfig):
        self._allowed_dirs = allowed_dirs
        self._config = safety_config
        self._read_only_dirs = list(safety_config.read_only_directories)
        self._extractors = build_extractor_registry()  # 36 个命令的提取器

    def check(self, command: str) -> SafetyDecision:
        # 1. 进程替换检查
        # 2. 命令替换递归校验
        # 3. 拆分复合命令（含换行、单个 &）
        # 4. 逐子命令：重定向校验 → 剥离 wrapper → find 特例 → 提取路径 → 校验路径
        # 5. cd + write/create 复合检测
        ...
```

`PathSafetyConfig` 是 `SafetyConfig`（YAML 级）与 `ShellPathValidator`（运行时）之间的桥接类型。`SafetyGuard.__init__` 从 `SafetyConfig` 提取字段构建此对象，避免 `ShellPathValidator` 直接依赖上层配置结构。

---

## 6. 命令注册表：PATH_EXTRACTORS

### 6.1 设计原则

- **每个命令一个提取器**：不存在"通用提取"，每个命令按自身参数语法提取路径
- **安全优先**：未注册的命令不做路径校验（passthrough），由外层权限管控覆盖
- **`--` 分隔符感知**：POSIX 标准中 `--` 表示"选项结束"，之后所有参数均为位置参数，即使以 `-` 开头

注册表条目类型：

```python
CommandExtractor = Callable[[list[str]], list[str]]
CommandValidator = Callable[[list[str]], str | None]

@dataclass(frozen=True)
class ExtractorEntry:
    extractor: CommandExtractor         # 从命令参数中提取路径列表
    op_type: Literal['read', 'write', 'create']  # 操作类型，决定路径校验策略
    description: str                    # 人类可读描述（用于错误消息）
    command_validator: CommandValidator | None = None  # 可选的命令级校验器（如 mv/cp）
```

`build_extractor_registry()` 构建完整的 36 条命令映射 `dict[str, ExtractorEntry]`，`ShellPathValidator` 在初始化时调用一次并缓存。

### 6.2 路径提取策略分类

根据命令的参数解析方式，将 36 个命令分为 **5 类提取策略**：

#### 策略 A：过滤 flags 取剩余参数（`filter_out_flags`）

最常见的模式。跳过所有以 `-` 开头的参数（flags），将剩余视为路径。正确处理 `--` 分隔符。

```python
def filter_out_flags(args: list[str]) -> list[str]:
    result = []
    after_double_dash = False
    for arg in args:
        if after_double_dash:
            result.append(arg)
        elif arg == '--':
            after_double_dash = True
        elif not arg.startswith('-'):
            result.append(arg)
    return result
```

安全关键：`rm -- -/../.claude/settings.json` 中 `-/../...` 以 `-` 开头，朴素过滤会丢弃它，但 `--` 之后应当保留。

#### 策略 B：模式命令解析（`parse_pattern_command`）

用于 grep/rg 类命令，参数格式为 `command [flags] pattern [files...]`。
第一个非 flag 参数是 pattern（跳过），后续是文件路径。如果通过 `-e`/`-f` 显式指定了 pattern，则所有非 flag 参数都是路径。

#### 策略 C：特殊参数跳过

用于 sed/jq 等命令，需要跳过"表达式"参数（非路径），仅提取文件参数。

#### 策略 D：搜索起点收集

用于 find 命令，收集位于 flags 之前的参数作为搜索起点。

#### 策略 E：子命令分发

用于 git 等有子命令体系的命令，根据子命令决定是否需要路径校验。

### 6.3 完整命令注册表

#### `cd` — 切换目录 | `read` | 特殊处理

- 无参数 → `[home_dir]`
- 有参数 → 所有参数拼接为一个路径
- 安全考量：`cd` 本身是 read，但在复合命令中影响后续命令的工作目录（详见 §10.5）

#### `ls` — 列出文件 | `read` | A + 默认值

- `filter_out_flags(args)`，无路径时默认 `['.']`

#### `find` — 搜索文件 | `read`（含侧信道校验）| D（搜索起点收集）

- 跳过全局选项 `-H`/`-L`/`-P`
- 收集首个非全局 flag 之前的位置参数作为搜索起点
- 某些 flag 值也是路径：`-newer`、`-anewer`、`-cnewer`、`-mnewer`、`-samefile`、`-path`、`-wholename`、`-ilname`、`-lname`、`-ipath`、`-iwholename` + `-newer[acmBt][acmtB]` 正则
- `--` 之后所有参数强制为路径，无路径时默认 `['.']`
- **侧信道（`ShellPathValidator._check_find`）**：
  - `-exec` / `-execdir` / `-ok` / `-okdir`：提取内层 shell 命令并**递归** `check()`
  - `-delete`：搜索起点按 `write` 校验
  - `-fprintf` / `-fprint` / `-fprint0` / `-fls`：`command_validator` → ask（写文件动作）

```python
def extract_find(args):
    paths = []
    path_flags = {'-newer', '-anewer', '-cnewer', '-mnewer', '-samefile',
                  '-path', '-wholename', '-ilname', '-lname', '-ipath', '-iwholename'}
    newer_pattern = re.compile(r'^-newer[acmBt][acmtB]$')
    found_non_global_flag = False
    after_double_dash = False

    i = 0
    while i < len(args):
        arg = args[i]
        if after_double_dash:
            paths.append(arg); i += 1; continue
        if arg == '--':
            after_double_dash = True; i += 1; continue
        if arg.startswith('-'):
            if arg in ('-H', '-L', '-P'):
                i += 1; continue
            found_non_global_flag = True
            if arg in path_flags or newer_pattern.match(arg):
                if i + 1 < len(args):
                    paths.append(args[i + 1]); i += 1
            i += 1; continue
        if not found_non_global_flag:
            paths.append(arg)
        i += 1
    return paths if paths else ['.']
```

#### 策略 A 命令组（27 个）| `filter_out_flags(args)`

| 命令 | 操作类型 | 附加校验 | 描述 |
|------|---------|---------|------|
| `mkdir` | create | - | create directories in |
| `touch` | create | - | create or modify files in |
| `rm` | write | 危险删除路径检查 | remove files from |
| `rmdir` | write | 危险删除路径检查 | remove directories from |
| `mv` | write | 命令校验器：拒绝所有带 flag 的调用（`--target-directory=PATH` 绕过） | move files to/from |
| `cp` | write | 命令校验器：同 mv | copy files to/from |
| `cat` | read | - | concatenate files from |
| `head` | read | - | read the beginning of files from |
| `tail` | read | - | read the end of files from |
| `sort` | read | - | sort contents of files from |
| `uniq` | read | - | filter duplicate lines from files in |
| `wc` | read | - | count lines/words/bytes in files from |
| `cut` | read | - | extract columns from files in |
| `paste` | read | - | merge files from |
| `column` | read | - | format files from |
| `file` | read | - | examine file types in |
| `stat` | read | - | read file stats from |
| `diff` | read | - | compare files from |
| `awk` | read | - | process text from files in |
| `strings` | read | - | extract strings from files in |
| `hexdump` | read | - | display hex dump of files from |
| `od` | read | - | display octal dump of files from |
| `base64` | read | - | encode/decode files from |
| `nl` | read | - | number lines in files from |
| `sha256sum` | read | - | compute SHA-256 checksums for files in |
| `sha1sum` | read | - | compute SHA-1 checksums for files in |
| `md5sum` | read | - | compute MD5 checksums for files in |

#### `tr` — 字符转换 | `read` | 特殊处理

- 跳过 1-2 个字符集参数（SET1、SET2），`-d`/`--delete` 时仅 SET1
- 剩余为文件路径

```python
def extract_tr(args):
    has_delete = any(a == '-d' or a == '--delete' or
                     (a.startswith('-') and 'd' in a) for a in args)
    non_flags = filter_out_flags(args)
    return non_flags[1 if has_delete else 2:]
```

#### `grep` — 文本搜索 | `read` | B（模式命令解析）

带值 flags：`-e`, `--regexp`, `-f`, `--file`, `--exclude`, `--include`, `--exclude-dir`, `--include-dir`, `-m`, `--max-count`, `-A`/`-B`/`-C` + 长形式

特殊：`-r`/`-R`/`--recursive` 且无路径 → `['.']`

#### `rg` (ripgrep) — 文本搜索 | `read` | B（模式命令解析）

带值 flags：`-e`, `--regexp`, `-f`, `--file`, `-t`, `--type`, `-T`, `--type-not`, `-g`, `--glob`, `-m`, `--max-count`, `--max-depth`, `-r`, `--replace`, `-A`/`-B`/`-C` + 长形式

默认路径：`['.']`

#### `sed` — 流编辑器 | `write`（可降级为 `read`） | C（特殊参数跳过）

提取逻辑：
1. `-f`/`--file` 值 → 脚本文件路径，加入路径列表
2. `-e`/`--expression` 值 → 表达式，跳过
3. 第一个非 flag 参数 → 表达式（如未通过 `-e`/`-f` 指定），跳过
4. 之后 → 文件路径

```python
def extract_sed(args):
    paths, skip_next, script_found, after_dd = [], False, False, False
    for i, arg in enumerate(args):
        if skip_next: skip_next = False; continue
        if not after_dd and arg == '--': after_dd = True; continue
        if not after_dd and arg.startswith('-'):
            if arg in ('-f', '--file'):
                if i + 1 < len(args): paths.append(args[i + 1]); skip_next = True
                script_found = True
            elif arg in ('-e', '--expression'):
                skip_next = True; script_found = True
            elif 'e' in arg or 'f' in arg: script_found = True
            continue
        if not script_found: script_found = True; continue
        paths.append(arg)
    return paths
```

**操作类型降级**：`-n` + 仅打印表达式（`^(\d+(,\d+)?)?p$`）+ 无 `-i` → `read`

**表达式安全检查（防御纵深）**：即使路径合法，以下表达式模式仍需拦截。

检查结果类型：

```python
@dataclass(frozen=True)
class SedSafetyResult:
    safe: bool
    reason: str
```

`check_sed_expression_safety(expression) → SedSafetyResult` 对每个 sed 表达式逐一检查，任一不安全则整条命令被 deny。

拦截规则：

| 危险模式 | 说明 |
|----------|------|
| `w`/`W` command | 写入文件 |
| `e`/`E` command | 执行 shell 命令 |
| `s<delim>...<delim>...<delim>[flags]` 中含 `w`/`e` flag | 替换结果写文件/执行（支持任意分隔符，如 `s\|x\|y\|w file`） |
| 非 ASCII 字符 | Unicode 同形字攻击 |
| `{}` 花括号 | 块命令，无法静态分析 |
| 换行符 | 多行命令注入 |
| `!` 取反 | 增加分析复杂度 |

**任意分隔符检测**：sed 的 `s` 命令允许使用任意字符作为分隔符（如 `s|foo|bar|w file`、`s#foo#bar#e`）。`_has_dangerous_sub_flags()` 通过解析实际分隔符字符、跳过转义分隔符、定位 flags 区段来检测危险 flag，而非假定 `/` 为分隔符。

#### `jq` — JSON 处理器 | `read` | C（特殊参数跳过）

- 带值 flags：`-e`, `-f`, `--arg`, `--argjson`, `--slurpfile`, `--rawfile`, `-L`, `--indent` 等
- 第一个非 flag 参数是 filter → 跳过，后续为文件路径
- 无文件参数 → 从 stdin 读取，无需校验

#### `git` — 版本控制 | `read` | E（子命令分发）

- **`git diff --no-index`**：提取 `diff` 之后的非 flag 参数，取前 2 个
- **其他子命令**：在 git 仓库上下文内，受 git 自身安全模型约束 → 返回空列表

```python
def extract_git(args):
    if args and args[0] == 'diff' and '--no-index' in args:
        return filter_out_flags(args[1:])[:2]
    return []
```

### 6.4 分类汇总

| 策略 | 命令数 | 命令列表 |
|------|-------|---------|
| A: filter_out_flags | 27 | mkdir, touch, rm, rmdir, mv, cp, cat, head, tail, sort, uniq, wc, cut, paste, column, file, stat, diff, awk, strings, hexdump, od, base64, nl, sha256sum, sha1sum, md5sum |
| B: parse_pattern_command | 2 | grep, rg |
| C: 特殊参数跳过 | 2 | sed, jq |
| D: 搜索起点收集 | 1 | find |
| E: 子命令分发 | 1 | git |
| 特殊处理 | 3 | cd, ls, tr |

### 6.5 命令级校验器

某些命令有 flag 可绕过路径提取（路径藏在 flag 值中），需额外校验：

| 命令 | 规则 | 原因 |
|------|------|------|
| `mv` | 拒绝所有带 flag 的调用 → ask | `--target-directory=PATH` |
| `cp` | 拒绝所有带 flag 的调用 → ask | `--target-directory=PATH` |

### 6.6 操作类型分类

| 类型 | 策略 | 命令（数量） |
|------|------|------------|
| `read` | 范围可放宽 | cd, ls, find, cat, head, tail, sort, uniq, wc, cut, paste, column, tr, file, stat, diff, awk, strings, hexdump, od, base64, nl, grep, rg, git, jq, sha256sum, sha1sum, md5sum (29) |
| `write` | 严格限制在工作目录内 | rm, rmdir, mv, cp, sed (5) |
| `create` | 严格限制在工作目录内 | mkdir, touch (2) |

动态降级：`sed` 在只读条件下（`-n` + 仅打印 + 无 `-i`）从 `write` 降级为 `read`。

---

## 7. 路径校验流程

### 7.1 `validate_path(path, cwd, allowed_dirs, op_type, *, read_only_dirs=())`

对单个路径做完整校验，返回 `PathValidationResult(allowed, resolved_path, action, reason)`。

**步骤：**

1. **去引号 + 波浪号展开**
   - 去除包裹的单/双引号
   - `~` → `home_dir`，`~/xxx` → `home_dir/xxx`
   - `~username`、`~+`、`~-` → 拒绝（TOCTOU 风险：验证时无法知道 shell 实际展开结果）

2. **拒绝 Shell 展开语法**
   - 包含 `$` → 拒绝（`$VAR`、`${VAR}`、`$(cmd)`）
   - 包含 `%` → 拒绝（Windows `%VAR%`）
   - 以 `=` 开头 → 拒绝（Zsh `=cmd` 展开）

3. **Glob 模式处理**
   - write/create 操作中含 glob（`*?[]{}` 字符） → 拒绝（无法确定实际写入路径）
   - read 操作中含 glob → 提取 glob 基础目录进行校验

4. **路径解析**
   - 相对路径 → `resolve(cwd, path)` 转为绝对路径
   - 解析符号链接（但危险路径检查在解析前进行，防止 `/tmp` → `/private/tmp` 逃逸）

5. **目录范围检查**
   - 路径是否在 `allowed_dirs` 中某个目录的子树内
   - write/create 操作 → 必须在 `allowed_dirs` 范围内，否则 deny
   - read 操作 → 先查 `allowed_dirs`，再查 `read_only_dirs`，都不在则 ask（交由 `read_policy` + `resolve_ask` 决定最终结果）

### 7.2 目录白名单

**`allowed_dirs`**（读 + 写 + create）合并来源：
- 项目根目录（agent 启动时确定）
- YAML 配置的 `allowed_directories`
- 会话中动态添加的目录（用户确认后）

**`read_only_dirs`**（仅读取）来源：
- YAML 配置的 `read_only_directories`

路径校验优先级：`allowed_dirs`（完全访问） → `read_only_dirs`（只读） → 其余（ask/deny，由 `read_policy` 决定）。写入操作只查 `allowed_dirs`，`read_only_dirs` 中的路径不允许写入。

### 7.3 Glob 基础目录提取

```python
def get_glob_base_directory(pattern: str) -> str:
    glob_chars = set('*?[]{}')
    first_glob = len(pattern)
    for i, c in enumerate(pattern):
        if c in glob_chars:
            first_glob = i; break
    base = pattern[:first_glob]
    last_sep = base.rfind('/')
    if last_sep < 0: return '.'
    return base[:last_sep] or '/'
```

---

## 8. 危险路径硬拦截

### 8.1 危险删除路径 (`is_dangerous_removal_path`)

适用于 `rm` 和 `rmdir`，即使在工作目录范围内也**不可自动放行**：

| 模式 | 示例 | 说明 |
|------|------|------|
| 通配符 `*` | `rm *` | 删除当前目录所有文件 |
| 尾部 `/*` | `rm /tmp/*` | 清空目录 |
| 根目录 `/` | `rm -rf /` | 系统根目录 |
| 家目录 `~` | `rm -rf ~` | 用户全部数据 |
| 根直接子目录 | `rm -rf /usr` | 系统关键目录（不含 `/usr/local`） |
| Windows 驱动器根 | `rm -rf C:\` | Windows 根 |
| Windows 驱动器直接子目录 | `rm -rf C:\Windows` | Windows 系统目录 |

路径规范化：连续 `\` 和 `/` 压缩为单个 `/`。

```python
def is_dangerous_removal_path(path: str) -> bool:
    normalized = re.sub(r'[/\\]+', '/', path)
    if normalized == '*': return True
    if normalized.endswith('/*') or normalized.endswith('\\*'): return True
    if normalized == '/': return True
    if normalized == os.path.expanduser('~').replace('\\', '/'): return True
    if re.match(r'^/[^/]+$', normalized): return True
    if re.match(r'^[A-Za-z]:/?$', normalized): return True
    if re.match(r'^[A-Za-z]:/[^/]+$', normalized): return True
    return False
```

### 8.2 系统敏感路径

对任何 write 操作均需特别警惕（配置在 YAML `safety_rules.sensitive_paths` 中）：

| 路径 | 说明 |
|------|------|
| `/etc/*` | 系统配置 |
| `/sys/*`, `/boot/*`, `/dev/*`, `/proc/*` | 内核/设备/进程 |
| `~/.ssh/*`, `~/.gnupg/*` | 密钥 |
| `~/.bashrc`, `~/.zshrc`, `~/.profile` | Shell 配置 |
| `.git/config`, `.git/hooks/*` | Git 配置和钩子 |

---

## 9. Safe Wrapper 剥离

### 9.1 问题

包装命令遮蔽真实操作命令：`timeout 10 rm -rf /` → base command 是 `timeout`（非路径命令）→ passthrough。

### 9.2 支持剥离的 Wrapper

| Wrapper | 剥离示例 |
|---------|---------|
| `timeout` | `timeout 10 rm file` → `rm file` |
| `time` | `time ls -la` → `ls -la` |
| `nice` | `nice -n 10 rm file` → `rm file` |
| `nohup` | `nohup rm file` → `rm file` |
| `stdbuf` | `stdbuf -o0 cat file` → `cat file` |
| `env` | `env KEY=val rm file` → `rm file` |

**不剥离**：`sudo`、`su`、`doas`、`bash -c`、`sh -c` — 改变执行上下文，不能安全剥离。

### 9.3 两阶段剥离算法

```
阶段 1：剥离安全环境变量
  循环直到无变化：
    - 检查是否以 VAR=value 开头
    - VAR 在安全变量白名单中 → 剥离
    - VAR 不在白名单 → 停止

阶段 2：剥离 wrapper 命令
  循环直到无变化：
    - 匹配 5 个 wrapper 的正则 → 剥离前缀
    - 此阶段不剥离环境变量（wrapper 用 execvp 执行子命令，VAR=val 是命令名不是赋值）
```

### 9.4 安全环境变量白名单

| 分类 | 变量 |
|------|------|
| Go | `GOEXPERIMENT`, `GOOS`, `GOARCH`, `CGO_ENABLED`, `GO111MODULE` |
| Rust | `RUST_BACKTRACE`, `RUST_LOG` |
| Node | `NODE_ENV`（不含 `NODE_OPTIONS`） |
| Python | `PYTHONUNBUFFERED`, `PYTHONDONTWRITEBYTECODE` |
| Pytest | `PYTEST_DISABLE_PLUGIN_AUTOLOAD`, `PYTEST_DEBUG` |
| 语言/编码 | `LANG`, `LANGUAGE`, `LC_ALL`, `LC_CTYPE`, `LC_TIME`, `CHARSET` |
| 终端/显示 | `TERM`, `COLORTERM`, `NO_COLOR`, `FORCE_COLOR`, `TZ` |
| 颜色配置 | `LS_COLORS`, `LSCOLORS`, `GREP_COLOR`, `GREP_COLORS`, `GCC_COLORS` |
| 显示格式 | `TIME_STYLE`, `BLOCK_SIZE`, `BLOCKSIZE` |

**不安全（不可剥离）**：`HOME`, `TMPDIR`, `SHELL`（影响路径）；`BASH_ENV`, `PYTHONPATH`（代码注入）；`GOFLAGS`, `RUSTFLAGS`, `NODE_OPTIONS`（影响运行时）

### 9.5 timeout 剥离细节（最复杂）

| Flag | 类型 |
|------|------|
| `--foreground`, `--preserve-status`, `--verbose`/`-v` | 无值 |
| `--kill-after=N`/`-k N`/`-kN`, `--signal=SIG`/`-s SIG`/`-sSIG` | 有值 |

Flag 值安全校验：必须匹配 `[A-Za-z0-9_.+-]+`，拒绝 `$()` `` ` `` `|;&` 等。

### 9.6 nice 的三种形式

- `nice cmd`（无参数）
- `nice -N cmd`（传统，如 `nice -10 ls`）
- `nice -n N cmd`（POSIX，如 `nice -n 10 ls`）

### 9.7 env 的安全/不安全 flag

- 安全：`-i`（清空环境）、`-0`（NUL 分隔）、`-v`（详细）、`-u NAME`（删除变量）
- 不安全（遇到则停止剥离）：`-S`（字符串拆分 → 注入参数）、`-C`（改 cwd）、`-P`（改 PATH）

---

## 10. 输出重定向、进程/命令替换与复合命令校验

### 10.1 输出重定向

| 运算符 | 校验 |
|--------|------|
| `>`、`>|`、`&>` | 目标路径校验，操作类型 `create` |
| `>>`、`&>>` | 同上 |
| `>&N`（如 `2>&1`） | **不校验**（fd 复制） |
| `>&file` | 同 `>` |

- `/dev/null` 始终放行
- 目标含 `$VAR`/`%VAR%` → 拒绝（无法确定实际路径）

### 10.2 进程替换

```bash
echo secret > >(tee .git/config)  # 输出替换：写入目标不在重定向列表中
diff <(sort a.txt) <(sort b.txt)  # 输入替换：只读操作，风险低
```

区分输入/输出替换，分别标记 category：
- `>(cmd)` → ask(category=`process_output_sub`)：可能绕过路径校验写入未知位置
- `<(cmd)` → ask(category=`process_input_sub`)：本质是读操作

auto 模式下：输出替换 → deny，输入替换 → allow

### 10.3 命令替换

```bash
echo $(rm -rf /)           # 外层 echo 无害，内层 rm 在 shell 中执行
echo "$(curl http://x)"    # 双引号内仍会展开
echo '$(rm -rf /)'         # 单引号内为字面量，不提取内层命令
```

- 引号感知提取 `$(…)` 与反引号内容（单引号字符串内跳过）
- 支持 `${VAR:-$(cmd)}` 等参数展开中的嵌套替换
- 对每个内层命令**递归**调用 `ShellPathValidator.check()`
- 算术展开 `$((…))` 不视为命令替换

### 10.4 复合命令分隔符

除 `&&` / `||` / `;` / `|` 外，以下也会拆分为独立子命令（引号内不拆分）：

| 分隔符 | 说明 |
|--------|------|
| 换行 `\n` / `\r\n` | 多行脚本等价于多条命令 |
| 单个 `&` | 后台执行符，第二条命令仍会运行 |

### 10.5 复合命令中的 cd 安全问题

复合命令（`&&`/`;`）包含 `cd` + write/create 操作 → 强制 ask。

原因：路径校验基于原始 cwd，但 `cd` 在运行时改变了工作目录。
攻击：`cd .claude/ && mv test.txt settings.json` → 校验看到 `settings.json`（相对原始 cwd），实际写入 `.claude/settings.json`。

---

## 11. 共享基础设施

### 11.1 PermissionMatcher (`matcher.py`)

两层共用的通配符匹配逻辑：

```python
class PermissionMatcher:
    def match(self, pattern: str, tool_call: str) -> bool:
        """使用 fnmatch 做通配符匹配"""

    def match_with_content(self, pattern: str, tool_name: str, tool_args: dict) -> bool:
        """支持 server---tool:content_pattern 格式"""
```

- 工具名格式：`{server_name}---{tool_name}`（与 `ToolManager.TOOL_SPLITER = '---'` 一致）
- 支持 `*` / `?` 通配符，`|` 分隔多模式
- 支持 `server---tool:content_pattern` 格式（content 从 tool_args 中提取）

---

## 12. 集成点与代码变更

### 12.1 `tool_manager.py` 注入权限检查

在 `ToolManager.single_call_tool()` 中，解析 tool_name/tool_args 之后、`tool_ins.call_tool()` 之前：

```python
# --- 权限检查注入点 (tool_manager.py ~L294) ---
args_dict = dict(tool_args) if isinstance(tool_args, dict) else {}

# 内层：安全底线检查（不可绕过）
if self._safety_guard is not None:
    from ms_agent.permission.ask_resolver import resolve_ask
    safety_decision = self._safety_guard.check(tool_name, args_dict)
    if safety_decision.action == 'deny':
        return f'Blocked by safety policy: {safety_decision.reason}'
    if safety_decision.action == 'ask':
        resolved = resolve_ask(safety_decision, self._permission_mode, self._read_policy)
        if resolved.action == 'deny':
            return f'Blocked by safety policy: {resolved.reason}'
        if resolved.action == 'ask':
            if self._permission_enforcer is None:
                return f'Blocked by safety policy (requires confirmation): {resolved.reason}'
            # interactive 模式：fall through 到 enforcer/handler

# 外层：用户意图检查（可被用户覆盖）
if self._permission_enforcer is not None:
    perm_decision = await self._permission_enforcer.check(tool_name, args_dict)
    if perm_decision.action == 'deny':
        return f'Tool call denied: {perm_decision.reason}'
    if perm_decision.updated_args is not None:
        tool_args = perm_decision.updated_args
        tool_info['arguments'] = tool_args

# ... 继续现有的 tool_ins.call_tool() 逻辑 ...
```

`ToolManager.__init__()` 增加可选参数：
- `permission_enforcer: PermissionEnforcer | None = None`
- `safety_guard: SafetyGuard | None = None`

两者由上层（LLMAgent 或 Server）根据配置注入。

### 12.2 初始化链路

```python
# llm_agent.py: _build_permission_objects()
raw = dict(self.config.permission) if self.config.permission else {}
project_root = os.getcwd()
perm_config = PermissionConfig.from_dict(raw, project_root=project_root)

# workspace_root = output_dir，保证 SafetyGuard 和工具端使用相同基目录解析相对路径
output_dir = str(Path(getattr(self.config, 'output_dir', './output')).expanduser().resolve())

# 创建 SafetyGuard（内层）
allowed_dirs = [project_root] + list(perm_config.safety.allowed_directories)
read_only_dirs = list(perm_config.safety.read_only_directories)
safety_guard = SafetyGuard(
    config=perm_config.safety,
    allowed_dirs=allowed_dirs,
    read_only_dirs=read_only_dirs,
    workspace_root=output_dir,       # 统一路径解析基目录
)

# 创建 PermissionEnforcer（外层）
handler = AutoPermissionHandler()  # 或 CLIPermissionHandler() / WebPermissionHandler(emitter)
memory = PermissionMemory(project_path=project_root)
enforcer = PermissionEnforcer(config=perm_config, handler=handler, memory=memory)

# 注入到 ToolManager（含 mode 和 read_policy，供 ask_resolver 使用）
tool_manager = ToolManager(
    ...,
    permission_enforcer=enforcer,
    safety_guard=safety_guard,
    permission_mode=perm_config.mode,
    read_policy=perm_config.safety.read_policy,
)
```

---

## 13. 已完成迁移：WorkspacePolicyKernel → SafetyGuard + WorkspaceContext

> **状态：✅ 已完成**
>
> `ms_agent/utils/workspace_policy.py` 已从代码库中删除。安全职责统一到 SafetyGuard，功能职责提取为 `WorkspaceContext`。

### 13.1 迁移结果

| 原 WPK 代码 | 迁移去向 | 实现位置 |
|-------------|---------|---------|
| `resolve_under_roots()` | `SafetyGuard._check_file_path()` → `validate_path()` | `ms_agent/permission/safety.py` |
| `path_is_allowed()` | SafetyGuard 在 tool_manager 层统一检查，工具层不再需要 | 已删除 |
| `deny_globs` | `WorkspaceContext.deny_globs`（功能用途：文件遍历过滤） | `ms_agent/utils/workspace_context.py` |
| `workspace_root` | `WorkspaceContext.root`（功能用途：subprocess cwd、相对路径显示） | `ms_agent/utils/workspace_context.py` |
| `assert_shell_command_allowed()` | `SafetyGuard.check()` → `ShellPathValidator.check()` | `ms_agent/permission/shell_validator.py` |
| `_shell_looks_network()` | `PermissionConfig._DEFAULT_BLACKLIST`（enforcer 层策略） | `ms_agent/permission/config.py` |
| `_shell_looks_mutating_or_network()` | `ShellPathValidator` 操作类型 + 路径校验 | `ms_agent/permission/shell_validator.py` |
| `iter_files_under()` | 已删除（确认无外部调用者） | — |

### 13.2 调用点变更（实际代码）

**`filesystem_tool.py`：**
```python
# 之前
from ms_agent.utils.workspace_policy import WorkspacePolicyError, WorkspacePolicyKernel
self._fs_policy = WorkspacePolicyKernel(output_dir, extra_allow_roots=roots, deny_globs=deny)
root = self._fs_policy.resolve_under_roots(path)       # grep/glob 路径解析
cwd=str(self._fs_policy.workspace_root)                 # subprocess cwd
deny = self._fs_policy.deny_globs                       # 文件遍历过滤
self._fs_policy.path_is_allowed(rp)                     # glob 结果路径检查

# 之后
from ms_agent.utils.workspace_context import WorkspaceContext
self._ws = WorkspaceContext.from_config(config)
root = (self._ws.root / raw).resolve()                  # 路径解析（安全检查在 SafetyGuard 完成）
cwd=str(self._ws.root)                                  # subprocess cwd
deny = self._ws.deny_globs                              # 文件遍历过滤
# path_is_allowed 已删除 — SafetyGuard 在 tool_manager 层已检查 path 参数
```

**`local_code_executor.py`：**
```python
# 之前
from ms_agent.utils.workspace_policy import WorkspacePolicyError, WorkspacePolicyKernel
self._policy = WorkspacePolicyKernel(output_dir, ...)
self._policy.assert_shell_command_allowed(command)      # 命令安全检查
cwd=str(self._policy.workspace_root)                    # subprocess cwd

# 之后
from ms_agent.utils.workspace_context import WorkspaceContext
self._ws = WorkspaceContext.from_config(config)
# assert_shell_command_allowed 已删除 — SafetyGuard 在 tool_manager 层已检查
cwd=str(self._ws.root)                                  # subprocess cwd
```

### 13.3 关键设计决策

**1. WorkspaceContext 不含任何安全逻辑**

```python
@dataclass(frozen=True)
class WorkspaceContext:
    root: Path                                    # workspace cwd（原 output_dir）
    deny_globs: tuple[str, ...] = ('**/.git/**',) # 文件遍历过滤模式

    @classmethod
    def from_config(cls, config) -> WorkspaceContext: ...
```

WorkspaceContext 是纯功能性的——提供 subprocess 的 cwd 和 grep/glob 的文件过滤模式。所有安全校验（路径白名单、敏感路径、命令检查）统一在 SafetyGuard 层完成。

**2. SafetyGuard 接受 workspace_root 统一路径解析**

迁移前存在路径解析不一致：SafetyGuard 用 `os.getcwd()`，WPK 用 `output_dir`。迁移后 `SafetyGuard.__init__` 接受 `workspace_root` 参数，`llm_agent.py` 传入 `output_dir`，两端使用相同的基目录。

**3. SafetyGuard 覆盖 grep/glob 工具**

迁移前 grep/glob 的路径安全完全依赖 WPK 的 `resolve_under_roots()`。迁移后 SafetyGuard 的 `check()` 新增 `---grep` 和 `---glob` 分支，复用 `_check_file_path(path, 'read')`。

**4. 网络命令检测迁移到 enforcer 层**

WPK 的 `_shell_looks_network()` 硬编码阻止 curl/wget/ssh 等命令。这不属于安全底线（用户可以选择允许），因此迁移到 `PermissionConfig._DEFAULT_BLACKLIST`：
- auto 模式下被 enforcer deny
- interactive 模式下 ask 用户确认
- 用户可通过 whitelist 覆盖

### 13.4 兼容性保证

| 原 WPK 行为 | 新系统对应 | 保证方式 |
|-------------|----------|---------|
| `deny_globs` 默认 `('**/.git/**',)` | `WorkspaceContext` 默认值 | 代码中硬编码 |
| `shell_network_enabled = False` | `_DEFAULT_BLACKLIST` 包含 curl/wget/ssh/scp/rsync/nc/netcat | 默认 blacklist |
| `max_command_chars` 限制 | `ShellPathValidator.check()` 入口检查 | 配置传递链保留 |
| `shell_default_mode = 'read_only'` | 暂未迁移 | 标记为后续优化 |

---

## 14. YAML 配置格式（统一）

```yaml
permission:
  # --- 外层：用户意图 ---
  mode: auto  # auto | strict | interactive（兼容旧名 restricted → interactive）

  whitelist:
    - "file_system---read_file"
    - "file_system---grep"
    - "file_system---glob"
    - "web_search---*"

  blacklist:                    # 以下为内置默认值，用户配置会追加合并
    - "code_executor---shell_executor:curl *"    # 默认
    - "code_executor---shell_executor:wget *"    # 默认
    - "code_executor---shell_executor:ssh *"     # 默认
    - "code_executor---shell_executor:scp *"     # 默认
    - "code_executor---shell_executor:rsync *"   # 默认
    - "code_executor---shell_executor:nc *"      # 默认
    - "code_executor---shell_executor:netcat *"  # 默认
    # - "custom---tool"                          # 用户自定义追加

  # --- 内层：安全底线 ---
  safety_rules:
    # 通用工具级拦截（不可被用户覆盖）
    patterns:
      - "code_executor---shell_executor:rm -rf *"
      - "code_executor---shell_executor:mkfs *"
      - "code_executor---shell_executor:dd if=*"
      - "file_system---write_file:/etc/*"
      - "file_system---write_file:/sys/*"

    # 危险删除路径（rm/rmdir 专用，不可被用户覆盖）
    dangerous_removal_paths:
      - "*"
      - "/*"
      - "/"
      - "~"

    # 系统敏感路径（write/create 操作拦截）
    sensitive_paths:
      - "/etc/*"
      - "/sys/*"
      - "/boot/*"
      - "/dev/*"
      - "/proc/*"
      - "~/.ssh/*"
      - "~/.gnupg/*"
      - "~/.bashrc"
      - "~/.zshrc"
      - "~/.profile"
      - ".git/config"
      - ".git/hooks/*"
      - "**/.git/**"        # 兼容原 WorkspacePolicyKernel 默认 deny_globs

  # --- 路径校验配置 ---
  allowed_directories:          # 完全访问（读 + 写 + create）
    - "${PROJECT_ROOT}"
    - "/tmp/ms-agent-workspace"

  read_only_directories:        # 只读访问（读允许，写/create 拒绝）
    - "/data/models"
    - "/usr/local/lib"

  path_validation:
    read_policy: loose    # loose: 读超出 allowed_dirs ∪ read_only_dirs 时 auto 模式放行
                          # strict: 读超出范围时 auto 模式拒绝
    max_command_chars: 8192  # 兼容原 WorkspacePolicyKernel
```

---

## 15. 文件结构

```
ms_agent/permission/
├── __init__.py              # 导出 PermissionEnforcer, SafetyGuard, resolve_ask 等
├── config.py                # PermissionConfig + SafetyConfig + _DEFAULT_BLACKLIST — 解析 YAML
├── ask_resolver.py          # resolve_ask() — ask 模式解析（auto/strict/interactive）
├── matcher.py               # PermissionMatcher — 通配符匹配逻辑（两层共用）
├── enforcer.py              # PermissionEnforcer — 外层判定入口
├── handler.py               # PermissionHandler 协议 + Auto/CLI/Web 三种实现
├── memory.py                # PermissionMemory — "以后都允许" 持久化
├── suggestions.py           # generate_suggestions() — 自动建议模式生成
├── safety.py                # SafetyGuard — 内层安全底线（含 workspace_root + grep/glob 覆盖）
├── path_validator.py        # validate_path() — 单路径校验函数
├── shell_validator.py       # ShellPathValidator — shell 命令路径级校验 + SafetyDecision
├── path_extractors.py       # PATH_EXTRACTORS — 36 个命令的路径提取器注册表
├── wrapper_strip.py         # strip_safe_wrappers() — Safe Wrapper 剥离
└── sed_validator.py         # sed 表达式安全校验（防御纵深）

ms_agent/utils/
├── workspace_context.py     # WorkspaceContext — 轻量功能上下文（替代 WPK 的 root/deny_globs）
├── ...                      # 其他 utils
└── [已删除] workspace_policy.py  # WorkspacePolicyKernel 已迁移删除
```

---

## 16. 与 Claude Code 的对比

| 特性 | Claude Code | ms-agent 方案 |
|------|-------------|--------------|
| 权限行为 | allow / deny / ask | allow / deny / ask |
| 模式 | default / acceptEdits / bypassPermissions / dontAsk / plan / auto | auto / strict / interactive |
| auto 模式 ask 处理 | AI 分类器（Haiku）判断 + denial tracking | 规则策略表按 category 自动解析（无额外 LLM 调用） |
| dontAsk/strict 等效 | ask → deny | ask → deny |
| interactive 等效 | default mode: ask → 弹出用户确认 | ask → handler.ask() |
| 询问选项 | Yes / Yes (session) / No / Tab to amend | allow_once / allow_session / allow_always / modify / deny |
| 规则持久化 | settings.json (user/project/local) | permission_memory.json (project/global) |
| 参数修改 | updatedInput + userModified | updated_args (via modify action) |
| 建议生成 | PermissionUpdate[] suggestions | generate_suggestions() → pattern list |
| 规则格式 | ToolName(ruleContent) | server---tool:content_pattern |
| 会话级规则 | session source in ToolPermissionContext | 内存中的 session_memory dict |
| 路径提取 | PATH_EXTRACTORS (34 命令) | PATH_EXTRACTORS (36 命令，含 cd/ls/tr 特殊处理) |
| 操作类型 | read / write / create | read / write / create |
| 危险路径 | isDangerousRemovalPath() | is_dangerous_removal_path() |
| Wrapper 剥离 | stripSafeWrappers() (2 阶段) | strip_safe_wrappers() (2 阶段) |
| 命令解析 | tree-sitter AST + shell-quote | shlex + 正则（一期），可扩展 AST |
| sed 安全 | 多层允许列表 + 拒绝列表 | 多层允许列表 + 拒绝列表 + 任意分隔符感知 |
| 目录权限 | additionalDirectories（读写不分离） | allowed_directories（读+写） + read_only_directories（只读） + read_policy 兜底 |
| 进程替换 | 不区分 input/output，统一 ask | 区分：`<(` → allow, `>(` → deny（auto 模式） |
| 前端交互 | React UI 组件 | Future + SSE + REST 回调 |
| 现有代码 | 无遗留 | WorkspacePolicyKernel 已迁移删除，安全→SafetyGuard，功能→WorkspaceContext |

---

## 17. 验证方式

### 17.1 单元测试

| 模块 | 测试要点 |
|------|---------|
| PermissionMatcher | 通配符匹配、`|` 分隔、content pattern、边界情况 |
| PermissionEnforcer | auto/strict/interactive 模式、黑白名单优先级、session/persistent memory |
| ask_resolver | auto 模式 7 个 category 解析、strict 全 deny、interactive 保持 ask、read_policy |
| PermissionMemory | 项目级/全局级持久化、合并优先级、add/revoke/list |
| SafetyGuard | safety_rules 匹配、工具特化分发、deny 不可覆盖 |
| ShellPathValidator | 完整流水线（进程替换→拆分→剥离→提取→校验→重定向） |
| PATH_EXTRACTORS | 36 个命令各自的提取逻辑、`--` 处理、edge case |
| validate_path | 波浪号展开、shell 展开拒绝、glob 处理、目录范围检查、read_only_dirs 读写分离 |
| is_dangerous_removal_path | 7 种危险模式、路径规范化 |
| strip_safe_wrappers | 6 个 wrapper、2 阶段算法、安全环境变量白名单 |
| sed_validator | 只读降级、危险表达式拦截 |
| CLIPermissionHandler | 5 种操作的交互流程、allow_always 可编辑模式 |
| WebPermissionHandler | Future 挂起/resolve、超时 deny |
| generate_suggestions | 各工具类型的建议模式生成 |

### 17.2 集成测试

| 场景 | 验证内容 |
|------|---------|
| SafetyGuard → ToolManager | mock SafetyGuard，验证 deny 时 single_call_tool 返回拒绝消息 |
| PermissionEnforcer → ToolManager | mock PermissionEnforcer，验证 deny/modify 行为 |
| WorkspacePolicyKernel 兼容 | 原测试用例在新系统中全部通过 |
| 端到端权限流程 | interactive 模式下工具调用→ask→用户选择→执行/拒绝 |
| auto 模式无交互 | auto 模式下 SafetyGuard ask → resolve_ask → allow/deny（无 hang） |
| strict 模式保守 | strict 模式下所有不确定命令被 deny |

### 17.3 安全回归测试

针对已知攻击向量逐一验证：

| 攻击 | 预期结果 |
|------|---------|
| `rm -rf /` | deny（危险路径） |
| `timeout 10 rm -rf /` | deny（剥离 wrapper 后识别） |
| `rm -- -/../.claude/settings.json` | deny（`--` 后正确提取路径） |
| `echo "x" > /etc/passwd` | deny（重定向写入超出 allowed_dirs） |
| `cd .claude/ && mv test settings.json` | auto→deny / interactive→ask（cd + write） |
| `rm $HOME/.ssh/*` | auto→deny / interactive→ask（shell 展开） |
| `env HOME=/tmp rm -rf ~` | 不剥离 HOME（不安全变量） |
| `echo secret > >(tee .git/config)` | auto→deny / interactive→ask（输出进程替换） |
| `diff <(sort a.txt) <(sort b.txt)` | auto→allow（输入进程替换，只读） |
| `echo $(rm -rf /)` | deny（命令替换内层校验） |
| `true\nrm -rf /` | deny（换行分隔第二条命令） |
| `true & rm -rf /` | deny（单个 `&` 分隔第二条命令） |
| `find . -exec rm -rf /etc/important {} \;` | deny（find -exec 内层校验） |
| `code_executor---shell_executor:curl *`（auto 模式） | deny（enforcer blacklist，先于 auto allow） |
| `mv --target-directory=/etc test.txt` | auto→deny / interactive→ask（命令校验器） |
| `sed -e 's/x/y/w /etc/passwd' file` | deny（sed 表达式安全检查） |
| `sed -e 's\|x\|y\|w /etc/passwd' file` | deny（sed 任意分隔符表达式安全检查） |

---

## 18. 实现审查：已知问题与待办

> **审查日期**：2026-06-09
>
> 对照实现路径：`ms_agent/permission/`、`ms_agent/tools/tool_manager.py`、`ms_agent/agent/llm_agent.py`
>
> **测试现状**：`tests/permission/` 共 248 项单元测试通过；§17.2 集成测试与部分 Handler 单测尚未落地。

### 18.1 实现完成度概览

| 维度 | 状态 | 说明 |
|------|------|------|
| 双层架构（SafetyGuard + PermissionEnforcer） | ✅ 已完成 | `ToolManager.single_call_tool()` 统一入口 |
| Shell 路径级校验（36 命令注册表） | ✅ 已完成 | 进程/命令替换、复合分隔符、find -exec、重定向、wrapper 剥离、sed 纵深防御 |
| WorkspacePolicyKernel 迁移 | ✅ 已完成 | 安全→SafetyGuard，功能→WorkspaceContext |
| YAML 配置解析与默认规则 | ✅ 已完成 | `PermissionConfig.from_dict()` |
| auto / strict 模式 | ✅ 可用 | `resolve_ask` 规则表消歧，无交互 hang |
| interactive 模式端到端 | ⚠️ 未完成 | Handler 未按场景接入，见 §18.2 |
| Web 前后端权限协议 | ⚠️ 未完成 | `WebPermissionHandler` 已实现但未接通 webui |
| 集成测试 | ⚠️ 未完成 | §17.2 所列场景尚无对应用例 |

### 18.2 已知问题（按优先级）

#### P0 — 安全正确性

| # | 问题 | 设计预期 | 当前实现 | 状态 |
|---|------|---------|---------|------|
| 1 | ~~Shell 路径校验 cwd 与执行 cwd 不一致~~ | §13.2：统一使用 workspace root | `resolve_workspace_root()` 统一解析；`ShellPathValidator` 通过 `PathSafetyConfig.workspace_root` 校验；Agent / 文件工具 / SafetyGuard 共用同一根目录 | ✅ 已修复（2026-06-09） |
| 2 | **interactive 模式 Handler 未接入** | §12.2：按运行环境注入 Handler | `llm_agent._build_permission_objects()` 始终使用 `AutoPermissionHandler()` | 待修复 |

#### P1 — 交互与安全策略缺口

| # | 问题 | 设计预期 | 当前实现 | 涉及文件 |
|---|------|---------|---------|---------|
| 3 | **SafetyGuard `ask` 可被白名单/memory 绕过** | §2 判定流程：interactive 模式下 SafetyGuard `ask` 应交给 handler 确认 | `ToolManager` 在 SafetyGuard 返回 `ask` 后直接 fall through 到 `PermissionEnforcer.check()`；若命中 whitelist 或 memory 则直接 `allow`，跳过了安全疑点确认 | `tool_manager.py:305-310`、`enforcer.py` |
| 4 | **Web 前后端集成缺失** | §3.3.3：`permission_request` 事件 + `POST /permission/respond` | `WebPermissionHandler` 类已实现，但 `webui/` 无事件处理与 REST 回调，`resolve()` 无调用链 | `handler.py`、`webui/` |
| 5 | **`sensitive_paths` 未覆盖 shell 写路径** | §8.2：对任何 write 操作均需警惕系统敏感路径 | `SafetyGuard._check_file_path()` 对 `write_file`/`edit_file` 做 fnmatch 检查；shell 重定向和命令路径仅走 `validate_path` 目录范围检查，不查 `sensitive_paths` | `safety.py`、`shell_validator.py` |
| 6 | **`dangerous_removal_paths` YAML 配置未生效** | §14：`safety_rules.dangerous_removal_paths` 可配置 | `SafetyConfig.dangerous_removal_paths` 已解析，但 `is_dangerous_removal_path()` 逻辑硬编码，未读取配置 | `config.py`、`path_validator.py` |

#### P2 — 细节与文档

| # | 问题 | 说明 | 涉及文件 |
|---|------|------|---------|
| 7 | ~~`generate_suggestions` 未剥离 wrapper~~ | 复用 `strip_safe_wrappers()` | `suggestions.py` | ✅ 已修复（2026-06-09） |
| 8 | ~~`allowed_dirs` 与 `workspace_root` 来源不一致~~ | 统一 workspace root | `resolve_workspace_root()` + `allowed_dirs=[workspace_root, …]` | ✅ 已修复（2026-06-09） |
| 9 | ~~`PermissionConfig(mode='restricted')` 测试绕过别名~~ | 测试统一走 `from_dict()` | `tests/permission/test_enforcer.py` | ✅ 已修复（2026-06-09） |
| 10 | ~~§12.1 伪代码过时~~ | 更新为 `resolve_ask` 流程 | 本文档 §12.1 | ✅ 已修复（2026-06-09） |
| 11 | **`path_extractors.py` 注释写 34 命令** | 实际注册 36 条（与设计 §6.4 一致） | `path_extractors.py:319` |
| 12 | ~~**auto/strict 跳过 blacklist**~~ | §3.2：blacklist 先于 mode 短路 | `enforcer.py` 先匹配 blacklist | ✅ 已修复（2026-06） |
| 13 | ~~**Shell 命令替换 / 换行 / `&` 绕过**~~ | §10.3–§10.4：递归校验与扩展分隔符 | `shell_validator.py` | ✅ 已修复（2026-06） |
| 14 | ~~**find -exec 绕过 read 分类**~~ | §6.3：find 侧信道递归校验 | `shell_validator.py` + `path_extractors.py` | ✅ 已修复（2026-06） |


### 18.3 测试覆盖缺口

对照 §17.1 / §17.2，以下测试尚未实现：

| 缺失项 | 优先级 |
|--------|--------|
| `CLIPermissionHandler` 交互流程单测 | P1 |
| `WebPermissionHandler` Future 挂起/resolve/超时单测 | P1 |
| ~~`generate_suggestions` 各工具类型单测~~ | ✅ 已补充 |
| `ToolManager` + SafetyGuard / Enforcer 集成测试 | P1 |
| interactive 模式端到端流程测试 | P1 |

### 18.4 修复路线图

```
Phase 1（安全正确性）
  ├─ ✅ ShellPathValidator 接受 workspace_root，与 SafetyGuard / subprocess cwd 对齐
  ├─ ✅ resolve_workspace_root：未配置 output_dir 时默认 cwd；Agent / 工具 / 权限层统一
  ├─ sensitive_paths 扩展到 shell 重定向与 write 路径校验
  └─ dangerous_removal_paths 配置化（替换硬编码 is_dangerous_removal_path）

Phase 2（交互可用）
  ├─ _build_permission_objects 按 mode + 运行环境选择 Handler
  ├─ SafetyGuard ask 时 enforcer 跳过 whitelist/memory，强制走 handler
  └─ Web：permission_request 事件 + POST /permission/respond 接通 webui

Phase 3（完善）
  ├─ ToolManager 集成测试 + Handler 单测
  ├─ ✅ generate_suggestions 增加 wrapper 剥离
  └─ ✅ 更新 §12.1 伪代码
```

---

## 附录 A：parse_pattern_command 通用实现

```python
def parse_pattern_command(
    args: list[str],
    flags_with_args: set[str],
    defaults: list[str] | None = None,
) -> list[str]:
    """解析 grep/rg/jq 类命令的参数，提取文件路径"""
    paths = []
    pattern_found = False
    after_double_dash = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg is None:
            i += 1; continue
        if not after_double_dash and arg == '--':
            after_double_dash = True
            i += 1; continue
        if not after_double_dash and arg.startswith('-'):
            flag = arg.split('=')[0]
            if flag in ('-e', '--regexp', '-f', '--file'):
                pattern_found = True
            if flag in flags_with_args and '=' not in arg:
                i += 1
            i += 1; continue
        if not pattern_found:
            pattern_found = True
            i += 1; continue
        paths.append(arg)
        i += 1
    return paths if paths else (defaults or [])
```

---

## 附录 B：完整命令操作类型对照表

| 命令 | 操作类型 | 提取策略 | 附加校验 | 描述 |
|------|---------|---------|---------|------|
| cd | read | 特殊 | cd+write 检查 | change directories to |
| ls | read | A+默认 | - | list files in |
| find | read | D | - | search files in |
| mkdir | create | A | - | create directories in |
| touch | create | A | - | create or modify files in |
| rm | write | A | 危险删除路径 | remove files from |
| rmdir | write | A | 危险删除路径 | remove directories from |
| mv | write | A | 命令校验器 | move files to/from |
| cp | write | A | 命令校验器 | copy files to/from |
| cat | read | A | - | concatenate files from |
| head | read | A | - | read the beginning of files from |
| tail | read | A | - | read the end of files from |
| sort | read | A | - | sort contents of files from |
| uniq | read | A | - | filter duplicate lines from files in |
| wc | read | A | - | count lines/words/bytes in files from |
| cut | read | A | - | extract columns from files in |
| paste | read | A | - | merge files from |
| column | read | A | - | format files from |
| tr | read | 特殊 | - | transform text from files in |
| file | read | A | - | examine file types in |
| stat | read | A | - | read file stats from |
| diff | read | A | - | compare files from |
| awk | read | A | - | process text from files in |
| strings | read | A | - | extract strings from files in |
| hexdump | read | A | - | display hex dump of files from |
| od | read | A | - | display octal dump of files from |
| base64 | read | A | - | encode/decode files from |
| nl | read | A | - | number lines in files from |
| grep | read | B | `-r` 默认 `.` | search for patterns in files from |
| rg | read | B | 默认 `.` | search for patterns in files from |
| sed | write/read | C | 降级+表达式检查 | edit files in |
| git | read | E | 仅 `diff --no-index` | access files with git from |
| jq | read | C | - | process JSON from files in |
| sha256sum | read | A | - | compute SHA-256 checksums for files in |
| sha1sum | read | A | - | compute SHA-1 checksums for files in |
| md5sum | read | A | - | compute MD5 checksums for files in |
