# 智能体

`LLMAgent` 组织模型调用与工具执行。它不是模型客户端的别名：在每轮调用周围还要装配工具、提示、权限、技能、会话和记忆。只想开始调用时，先看 [Python SDK](../get-started/python-sdk.md)。

## 一次任务的执行过程

```{mermaid}
flowchart TD
 A[准备模型和运行时] --> B[装配工具、权限、Hooks和技能]
 B --> C[载入记忆、检索和会话]
 C --> D[构造提示与当前上下文]
 D --> E[请求模型]
 E --> F{需要工具?}
 F -->|是| G[授权、执行并记录结果]
 G --> D
 F -->|否| H[保存回复与处理后续输入]
 H --> I{继续?}
 I -->|是| D
 I -->|否| J[结束并释放资源]
```

取消、异常和轮数限制同样会影响结束路径，不是只有“没有工具调用”才结束。交互回调还可能等待下一条用户输入。

## 配置与构建

```python
from ms_agent.agent import LLMAgent
from ms_agent.config import Config

config = Config.from_task('agent.yaml')
agent = LLMAgent(config=config)
```

配置中的 `type` 由加载器选择 Agent 类型；`code_file` 可加载自定义实现，需要显式信任外部代码。工作流应使用其加载入口，不把工作流配置交给单个 Agent 当普通模型设置。

## 正确处理返回与取消

- 非流式 `await agent.run(query)` 返回消息列表；不要假设最后一项永远是可显示的文本。
- 流式返回异步生成器，消费者必须正确关闭它；消息和UI事件的区别见[消息与事件](messages-events.md)。
- 用 `try/finally` 清理自己创建的工具连接。取消应向上传递，不能把半轮输出当作正常完成。
- 代码常量的默认轮数与随包 `agent.yaml` 中的 `max_chat_round: 9999` 是不同层次；业务应显式设置预算。

## 扩展选择

| 想改变什么 | 优先选择 |
| --- | --- |
| 可调用操作 | [工具](tools.md) |
| Python生命周期行为 | [Callbacks](callbacks.md) |
| 事件上的脚本检查 | [Hooks](hooks.md) |
| 输入上下文或长期知识 | [上下文](context.md)、[记忆](memory.md) |
| 任务分工与依赖 | [子智能体](subagents.md)、[工作流](workflows.md) |

先使用这些接口，再考虑继承Agent。重写整个执行循环需要承担取消、持久化和资源关闭的责任。

实现：`ms_agent/agent/llm_agent.py`、`loader.py`、`runtime.py`。
