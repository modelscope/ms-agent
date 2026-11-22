# 架构总览

MS-Agent围绕一次任务的执行组织模型、工具、上下文、权限和持久化。CLI、TUI、WebUI及协议服务负责不同交互方式，执行与管理能力集中在Python SDK中。

本文说明职责与取舍。具体配置和扩展方法见核心模块；未来方案见设计提案（RFC），不把尚未接入的设计写成当前功能。

## 分层与依赖

```{mermaid}
flowchart TD
 A[CLI / TUI / WebUI / ACP / A2A] --> B[智能体与工作流]
 A --> C[项目、会话与配置服务]
 B --> D[模型与工具执行]
 B --> E[上下文与记忆]
 D --> F[权限与Hooks]
 D --> G[模型Provider / MCP / 本地工具]
 E --> C
```

入口把请求转成SDK调用，再把事件转成界面或协议响应。不在界面层维护另一份会话数据库或复制Agent循环，扩展能力才能被多个入口复用。

## 从请求到结果

1. 加载配置，确定工作目录、模型和交互模式。
2. 装配模型、工具、权限、Hooks、Plugins、Skills与记忆。
3. 载入会话，构造系统提示和本轮可见上下文。
4. 生成回复或工具调用；工具经过权限管线，结果回到模型输入。
5. 记录消息和产物，按条件调度记忆写入，处理追加输入或结束。
6. 取消/异常路径同样需要记录实际状态并关闭拥有的资源。

[智能体](../core/agents.md)负责模型与工具循环；[工作流](../core/workflows.md)表达明确阶段；[子智能体](../core/subagents.md)承接自主委派。它们不应被描述成完全相同的一种编排方式。

## 历史、上下文、记忆分离

| 层 | 保留什么 | 设计意义 |
| --- | --- | --- |
| SessionLog | 原始消息、工具结果和压缩事件 | 可追溯、可恢复 |
| ContextAssembler | 当前模型可见窗口 | 控制预算而不覆盖原记录 |
| MemoryBackend | 跨任务复用知识 | 后端可替换，调用契约统一 |

上下文策略符合 `ViewStrategy`，按顺序应用；记忆编排器通过 `MemoryBackend`委托具体实现。二者可扩展，但不是全部扩展都能用任意YAML名字自动加载。见[上下文](../core/context.md)、[记忆](../core/memory.md)。

后台记忆写入是有条件、异步的，不能承诺摘要发生前已经保存。旧压缩器仍由部分领域项目使用，渐进迁移需要核对项目自定义逻辑。

## 工具、权限与扩展

`ToolManager`是受管理工具调用的统一入口。内层SafetyGuard检查路径/命令，外层PermissionEnforcer处理模式、规则、授权记忆和人工确认；Hooks在事件位置提供扩展。

权限不等于OS隔离。直接工具对象、可信Hook脚本及远程MCP内部行为有不同边界；外部执行仍需要部署控制。安全配置列表显式赋值会替换默认值，不要用空列表作“追加配置”。

[Callbacks](../core/callbacks.md)是Python生命周期扩展，[Hooks](../core/hooks.md)是事件/脚本协议，[Plugins](../core/plugins.md)是资源装配；[Skills](../core/skills.md)保存按需任务知识。分别维护这些职责比在一个插件机制里混合所有行为更容易验证。

## 新旧路径与服务契约

- 模型四个传统服务默认仍使用legacy适配，其余注册服务走Provider层；开关可改变选择。见[模型](../core/models.md)。
- `Config.from_task()`和服务侧`ConfigResolver`分别承担配置加载与分层合并，不声称后者完全替代前者。
- MCP已有直接客户端执行、配置管理和按需健康检查。独立MCPRuntime状态机的存在不等于全部会话已使用它，未来接口见[MCP RFC](rfcs/mcp-runtime-api.md)。
- WebUI使用共享SDK服务和会话运行时，通过事件流更新页面。已有 `/api/mcps` 与RFC候选接口不同。
- ACP连接交互客户端，A2A连接远端任务服务，Agent Hub转换资产；三者不是互相替代的协议。

## 定位实现与扩展

| 关注点 | 代码 | 深入阅读 |
| --- | --- | --- |
| 循环与编排 | agent、workflow | [智能体](../core/agents.md)、[工作流](../core/workflows.md) |
| 配置与状态 | config、project、session | [配置](../core/configuration.md)、[存储](storage.md) |
| 输入与输出 | ui、llm | [消息与事件](../core/messages-events.md) |
| 能力扩展 | tools、skill、hooks、plugins | [工具](../core/tools.md)、[插件](../core/plugins.md) |
| 长期任务 | memory、cron | [记忆](../core/memory.md)、[调度](../core/scheduling.md) |
| 外部互通 | acp、a2a、agent_hub、capabilities | [ACP](../core/acp.md)、[A2A](../core/a2a.md)、[Agent Hub](../core/agent-hub.md) |

改变事件或生命周期时检查所有消费者，并覆盖完成、失败和中断；接口适配不应绕过SDK持久化。配置字段集中在[参考页](configuration-reference.md)，实现未来方向先登记RFC并明确状态。
