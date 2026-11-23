# Callbacks

Callbacks 是 Python 进程内的生命周期扩展。它们直接接收运行时和消息列表，适合统计、输入控制或定制响应处理；[Hooks](hooks.md)则提供事件脚本协议，[Plugins](plugins.md)负责装配扩展资源。

## 回调顺序

| 方法 | 调用位置 |
| --- | --- |
| `on_task_begin` | 任务开始 |
| `on_generate_response` | 请求模型之前 |
| `on_tool_call` | 模型生成之后、调用工具之前 |
| `after_tool_call` | 工具调用之后 |
| `on_task_end` | 任务结束 |

方法是异步的。尤其注意 `on_generate_response` 不是“模型生成完成后”的通知，其语义要以实际调用位置为准。

## 最小实现

```python
from ms_agent.callbacks.base import Callback

class TurnCounter(Callback):
    async def on_generate_response(self, runtime, messages):
        self.count = getattr(self, 'count', 0) + 1
```

仅定义类不会自动注册。创建 `agent` 后、调用 `run()` 前，用 `counter = TurnCounter(config)` 和 `agent.register_callback(counter)` 注册实例；任务后可读取 `counter.count`。内置回调可通过YAML启用：

```yaml
callbacks:
  - input_callback
```

`input_callback` 在回复后等待进一步输入，适合交互，但可能让批处理程序等待。无人值守的最小调用使用 `callbacks: []`，并显式控制轮数。

## 使用边界

回调可以原地修改消息，必须保护调用/结果配对、角色及上下文格式。耗时工作应避免阻塞事件循环；拥有资源的扩展要在结束或异常路径清理。不要在回调里打印完整凭据或未经脱敏的模型请求。

下一步：[智能体](agents.md)、[Hooks](hooks.md)。实现：`callbacks/base.py`、`callbacks/utils.py`、`agent/llm_agent.py`。
