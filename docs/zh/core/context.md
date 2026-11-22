# 上下文管理

上下文是这一次发送给模型的消息窗口，不是完整会话记录，也不是长期记忆。MS-Agent 用 `ContextAssembler` 从 `SessionLog` 构造可见窗口，再依次应用策略；原始消息仍保留在日志中。

## 压缩机制

```{mermaid}
flowchart TD
  A[完整会话日志] --> B[选择当前可见窗口]
  B --> C[工具输出裁剪策略]
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
  reserved_buffer: 20000
  strategies:
    - name: tool_output_pruner
      enabled: true
      prune_protect: 40000
    - name: summary_compactor
      enabled: true
```

这些是上下文预算，不保证与每个模型的实际窗口完全匹配。`reserved_buffer` 给回复留空间；保护最近工具输出可减少反复读取。`compaction.enabled: false` 停止自动压缩，但仍可以记录会话。

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

压缩前可触发记忆 flush 回调，但异步写入不保证先于摘要完成。持久知识由[记忆](memory.md)后端管理。终端 `/compact` 的手动工具输出裁剪与自动摘要管线也不是完全相同的操作。

下一步：[会话](sessions.md)、[提示装配](prompts.md)、[存储布局](../development/storage.md)。实现：`session/context_assembler.py`、`session/strategies/`、`LLMAgent._build_compaction_strategies()`。
