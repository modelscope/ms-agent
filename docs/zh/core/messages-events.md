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

## 运行中输入与事件订阅

`SessionInputController` 将接收输入与执行任务分开：`queue` 在当前任务完成后开启新任务，`steer` 在模型或工具的生命周期边界加入当前任务。已派发的工具批次不被插话强行取消；模型回复后尚未派发的旧工具可标记 `not_executed`，保留工具调用配对，而不能伪造成功结果。

WebUI 的主要接口为：

| 接口 | 用途 |
| --- | --- |
| `POST /api/chat/inputs` | 接收消息，按输入 ID 去重 |
| `GET /api/chat/sessions/{id}/inputs` | 查询任务状态与待处理消息 |
| `PATCH /api/chat/sessions/{id}/inputs/{input_id}` | 按 revision 编辑待处理消息 |
| `DELETE /api/chat/sessions/{id}/inputs/{input_id}` | 撤回待处理消息 |
| `POST /api/chat/sessions/{id}/inputs/resume` | 继续发送暂停消息 |
| `GET /api/chat/sessions/{id}/events` | SSE 快照与增量事件订阅 |
| `POST /api/chat/interrupt` | 停止指定任务 |

输入的 `pending` / `delivered` / `cancelled` 与任务运行状态分别记录，真正写入用户消息后才算投递。已经投递的消息不能再编辑或撤回。订阅使用 `epoch:sequence` 游标重放，游标过期则发送完整快照；断开订阅不会取消执行。当前需单 API worker，准备中与待处理输入合计最多 20 条。

TUI 的忙碌输入使用自己的终端输入缓冲，不应推断它具有 WebUI 的持久队列或编辑接口。操作见 [WebUI](../user-guide/webui.md)与[TUI](../user-guide/tui.md)。

下一步：[智能体](agents.md)、[会话](sessions.md)。实现：`llm/utils.py`、`ui/events.py`、`ui/input.py`。
