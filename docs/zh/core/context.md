# 上下文管理

上下文是这一次发送给模型的消息窗口，不是完整会话记录，也不是长期记忆。MS-Agent 用 `ContextAssembler` 从 `SessionLog` 构造可见窗口，再依次应用策略；原始消息仍保留在日志中。

## 压缩机制

```{mermaid}
flowchart TD
  A[完整会话日志] --> B[选择当前可见窗口]
  B --> C[可选工具输出裁剪]
  C --> D[历史摘要策略]
  D --> E{发生压缩?}
  E -->|是| F[追加压缩视图和事件]
  F --> G[更新可见窗口边界]
  E -->|否| H[转换为模型消息]
  G --> H
```

工具裁剪减少较早的大段工具输出，摘要策略借助模型概括历史。策略产生的压缩视图和元数据追加到日志，重启后可继续使用。摘要可能丢失细节，因此“日志完整”不等于“模型始终看到全部信息”。

## 配置内置策略

```yaml
session_log:
  enabled: true
compaction:
  enabled: true
  context_limit: 128000
  compression_ratio: 0.85
  strategies:
    - name: tool_output_pruner
      enabled: true
      prune_protect: 40000
    - name: summary_compactor
      enabled: true
```

默认使用摘要策略；工具输出裁剪需显式启用，它可能移除独有证据。自动压缩默认在有效窗口的 85% 触发，实际阈值还受输入上限和输出预留约束。`compaction.enabled: false` 关闭自动压缩，不关闭日志、硬预算检查或显式手动压缩。

## 输入与输出预算

窗口由模型能力、`llm.context_limit` 和兼容的 `compaction.context_limit` / `session_log.context_limit` 共同限制，取有效上限中的较小值；均未知时回退为 128000。手动配置可以缩小已知模型窗口，不能扩大服务实际支持的范围。

输出预留按最终请求的 `max_tokens`、`max_completion_tokens` 或 `max_output_tokens` 计算；未指定时默认不超过 8192、模型输出上限及窗口的八分之一。输入上限还需扣除该预留。旧 `reserved_buffer` 覆盖比例阈值，但不是最终请求的输出 token 参数。

## 自定义策略对象

策略符合 `ViewStrategy` 的 `name` 和 `apply()` 接口。下面的最小策略保留窗口，用来验证扩展契约，不调用模型：

```python
from copy import deepcopy
from ms_agent.session.context_assembler import ViewStrategy

class KeepWindow:
    name = 'keep_window'

    def apply(self, visible, all_msgs, config):
        return deepcopy(visible), None

assert isinstance(KeepWindow(), ViewStrategy)
```

构造 `ContextAssembler(session_log, strategies=[...])` 时传入策略对象；返回元数据时，组装器会记录压缩并持久化新窗口。不要修改 `all_msgs`，不要只裁掉工具调用而保留悬空结果。

**当前 YAML 只认识 `tool_output_pruner` 和 `summary_compactor`。** 新策略名不会自动导入 Python 实现；需要在编程集成处接入，不能把对象可插拔写成任意 YAML 即插即用。

## 与记忆和手动压缩的区别

自动压缩、SDK `/compact` 和 WebUI 按钮共用 `LLMAgent.compact_context()`。手动压缩在输入等待边界执行，不追加用户消息，也不触发主对话回答；WebUI 尚未提供 slash command 路由，应使用圆环菜单中的按钮。

摘要保留系统消息、最新输入和受保护的完整工具调用组。新窗口与完成事件作为完整记录追加，回放只采用校验通过的窗口；原始历史不被删除。摘要输入可按预算分片，空内容、截断或未缩短上下文的结果不会替换原窗口。

启用[记忆](memory.md)后，压缩提交前先尝试提取长期事实。普通提取失败保留旧记忆和重试来源，合格摘要仍可提交；取消会中止整个操作。

## 失败与续接

摘要失败时保留原上下文；仍超过硬输入预算时保存待处理请求。WebUI 的“重试压缩并继续”及 SDK `ResumeContext` 续接该请求，不重复追加用户消息。发送新指令会取代旧待处理请求。最新输入本身过大时，应缩短内容或换用更大窗口模型，不能靠压缩删除必须保留的输入。

下一步：[会话](sessions.md)、[提示装配](prompts.md)、[存储布局](../development/storage.md)。实现：`session/context_assembler.py`、`session/strategies/`、`LLMAgent._build_compaction_strategies()`。
