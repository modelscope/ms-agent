# 会话中的排队与插话

WebUI 允许用户在智能体工作时继续发送消息，用于安排后续任务或调整当前任务。输入的接收、保存和执行顺序由 SDK 管理，页面负责展示和操作。

## 使用方式

在「设置 → 个性化 → 对话行为」中选择默认方式：

| 方式 | 行为 |
| --- | --- |
| 排队（默认） | 当前任务完成后，按接收顺序逐条执行，每条消息开启一个新任务 |
| 插话 | 在当前模型响应或已启动的工具批次结束后，把消息加入当前任务，再由模型继续处理 |

空闲时，两种方式都会开启新任务。设置保存在 SDK 的 `settings.json`，字段为 `interaction.follow_up_behavior`；修改设置只影响之后接收的消息。

输入框右侧共用一个主按钮：任务运行且草稿为空时显示「停止」，输入文字、添加附件或选择技能后切换为「发送」。清空或成功发送后，任务仍在运行则恢复「停止」。附件上传时暂时禁用发送，手动压缩上下文时保留停止入口。

待处理消息放在输入框上方，可编辑、撤回和展开查看。实际加入模型上下文后，消息移入正文，显示为普通用户气泡，后续回复另起一个助手消息段。界面不增加插话标签，也不提供临时切换发送方式的菜单。列表和按钮复用现有主题、间距与移动端布局。

## 消息顺序

排队与插话各自保序，插话优先加入正在执行的任务。例如，A 运行时依次收到排队消息 Q1、Q2 和插话 S1、S2：

```text
A 执行 → 加入 S1、S2 → A 完成 → 执行 Q1 → 执行 Q2
```

同一处理时机之前收到的多条插话一起交给模型，每条仍是独立的用户消息，保留各自的附件和技能。之后收到的插话在下一次检查时处理。调度器不会把多条输入合成一句，也不会擅自删除先前要求。

插话携带目标任务的 `expected_turn_id`。目标已结束或改变时，服务端返回 `409`，页面保留草稿，避免把针对旧任务的修改送给新任务。

## 执行方式

`SessionInputController` 负责输入状态，`LLMAgent` 在以下位置检查插话：

1. **模型调用前**：把已接收的插话加入本次请求。
2. **模型响应结束、工具尚未派发时**：跳过这批旧工具调用，补齐对应结果，再加入插话，让模型重新决策。
3. **工具批次结束后**：先保留真实工具结果，再加入插话。
4. **任务结束前**：在异步结束钩子之后再次检查，确保已经接收的插话得到处理，再结束任务并写入记忆。

跳过的工具结果使用原 `tool_call_id`，标记为非成功，并明确说明工具没有执行、没有输出：

```json
{
  "source": "agent_runtime",
  "status": "not_executed",
  "reason": "superseded_by_user_input",
  "result": null,
  "message": "This tool call was not executed. No tool output is available. Consider the following user messages before deciding whether a new tool call is needed."
}
```

每个已声明的调用都必须有对应结果，顺序为 `assistant(tool_calls) → tool results → user → assistant`。已执行的工具保留真实结果；跳过的工具在界面中显示「已跳过」，不会生成文件产物记录。Anthropic 协议同时设置 `tool_result.is_error`。

首版不取消正在生成的模型响应，也不强行中断已派发的工具批次。等待授权的工具仍需用户批准或拒绝，插话不能代替授权。

## 停止与恢复

「停止」沿用取消当前任务的行为，同时保留并暂停尚未处理的输入。已产生的内容和文件不会回滚。

「继续发送」把暂停的消息按原顺序作为新任务处理，不恢复已取消的调用栈。用户也可以先发送一个新任务，此前暂停的消息仍需手动继续。错误导致任务结束时同样暂停队列，只有正常完成才自动处理下一条。

如果输入准备期间发生过停止，该消息也会暂停，避免准备较慢的输入在停止后意外启动。手动压缩和上下文恢复与会话任务共用运行锁，下一条输入等待这些操作完成后再开始。

## 保存与刷新

输入分为 `pending`、`delivered`、`cancelled` 三种状态，暂停原因单独保存。`input_id` 用于请求去重，`revision` 防止旧编辑覆盖新内容；消息开始处理后，编辑和撤回返回冲突。文本、附件引用、技能及接收时选择的模型一并保存。

SDK 在现有 SessionLog 中追加带版本的 `input_event`，记录输入变化和任务开始、结束、中断。**用户消息写入日志，才算完成投递。** 任务 ID、消息 ID 和助手显示段 ID 随普通消息保存，历史回放、导出与会话分支使用实际投递顺序，控制记录不进入模型对话。

WebUI 每个会话只有一个执行 worker。发送请求与 SSE 订阅分开，刷新页面、切换会话或断开连接不会取消任务。订阅使用 `epoch:sequence` 游标重放事件；游标过期时，服务端返回历史、当前输出和待处理消息的完整快照。前端通过同一个 reducer 更新实时输出与恢复后的内容。

服务进程重启后，未完成任务标记为中断，待处理消息恢复为暂停。已投递输入不会自动重跑。若工具可能已经产生副作用，但结果未写入日志，恢复记录只能说明执行结果未知，不能声称工具未执行。强制结束进程可能丢失尚未落盘的最后少量输出。

## 接口与范围

| 接口 | 用途 |
| --- | --- |
| `POST /api/chat/inputs` | 接收输入；首次创建会话和重复提交均使用同一个输入 ID 去重 |
| `GET /api/chat/sessions/{id}/inputs` | 查询待处理消息和任务状态 |
| `PATCH /api/chat/sessions/{id}/inputs/{input_id}` | 按 `revision` 编辑待处理消息 |
| `DELETE /api/chat/sessions/{id}/inputs/{input_id}` | 按 `revision` 撤回待处理消息 |
| `POST /api/chat/sessions/{id}/inputs/resume` | 继续发送暂停的消息 |
| `GET /api/chat/sessions/{id}/events` | 订阅会话快照与后续事件 |
| `POST /api/chat/interrupt` | 按目标任务 ID 停止执行 |

旧 `/api/chat` 入口也通过同一个输入控制器执行。未启用控制器的 CLI/TUI 沿用现有流程。首版使用单 API worker，准备中与待处理输入合计最多 20 条，事件重放缓冲最多 2048 条；不包含对子 Agent 的定向插话或多进程调度。

设计参考了 [Codex 的活动任务插话协议](https://learn.chatgpt.com/docs/app-server#steer-an-active-turn)、[OpenCode 的会话收件箱](https://github.com/anomalyco/opencode/blob/9e2f9311ae1b183af0c971c165aff324e8b4b2b8/packages/core/src/session/inbox.ts)和 [Pi 的执行循环](https://github.com/earendil-works/pi/blob/2c1d24d6f4927004af7d8fda93e76586dd6097de/packages/agent/src/agent-loop.ts)。这里采用共同的排队与插话区分，并按 MS-Agent 现有执行流程选择生效时机。
