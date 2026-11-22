# 消息与事件

消息描述对话内容，事件描述执行过程中发生了什么。区分两者可以避免在前端重复追加整段回答，或将“工具参数正在生成”误显示为“工具已执行”。

## 两种数据各司其职

| 数据 | 典型用途 | 关键点 |
| --- | --- | --- |
| `Message` | 模型输入、Agent返回、会话日志转换 | 角色、内容、工具调用/结果与多模态信息 |
| `AgentEvent` | TUI/WebUI/协议适配中的增量展示 | `type`区分事件，`to_dict()`得到可序列化形式 |

工具结果需要对应此前的调用。重新组织上下文时，不应拆散调用与结果的配对；完整历史也不应被UI展示状态替代。

## 观察一次回复

```{mermaid}
sequenceDiagram
 participant User as 用户
 participant Agent as 智能体
 participant UI as 界面
 User->>Agent: 提交请求
 Agent-->>UI: turn_started
 Agent-->>UI: content_delta / reasoning_delta
 Agent-->>UI: tool_call_composing
 Note over Agent,UI: 参数生成不表示操作已执行
 Agent-->>UI: tool_call_started / tool_call_completed
 Agent-->>UI: content_end
 Agent-->>UI: turn_completed
```

并非每轮都会出现所有事件。异常与取消有自己的路径，不能单靠最后一段文本判定成功。

```python
from ms_agent.ui.events import ContentDelta, TurnCompleted

assert ContentDelta(text='hello').to_dict() == {
    'type': 'content_delta', 'text': 'hello'
}
assert TurnCompleted(turn_id='demo').to_dict()['type'] == 'turn_completed'
```

## 流式消费者

`await agent.run(query, stream=True)` 得到的异步生成器产出消息视图，不应当把每次产出的完整消息都当作一个文本增量。需要自行维护已显示内容，或使用SDK事件接口构建界面。TUI的 `--emit-events` 可将事件追加为JSONL，便于理解真实顺序。

WebUI 会将SDK事件适配到HTTP流式响应，不要绕过适配层向浏览器直接发送内部Python对象。扩展事件时同时检查SDK、TUI、ACP转换器及WebUI消费者。

下一步：[智能体](agents.md)、[会话](sessions.md)。实现：`llm/utils.py`、`ui/events.py`、`ui/input.py`。
