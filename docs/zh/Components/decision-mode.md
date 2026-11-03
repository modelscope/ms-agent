# 决策模式（实验功能）

决策模式为长任务增加两项辅助能力：在上下文接近上限时筛选工具输出，以及在出现重复执行或准备交付时复核证据。主模型继续负责理解任务、调用工具和生成答案；决策模型只回答代码定义的问题，不能直接执行命令或授予工具权限。

这项功能适合工具输出多、验证步骤长的任务。短问答通常不调用决策服务。它不保证任务正确，也不保证每次更快：筛选、摘要、缓存变化和原文恢复都可能增加开销。

## 在 WebUI 中启用

1. 在“设置 → 模型”中配置供应商及凭据。例如百炼 Token Plan 的 Base URL 为 `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`。
2. 在“设置 → 个性化 → 决策模型”中选择该供应商，填写 `decision-model-preview` 并保存。“测试连接”会发起一次很小的付费请求；保存和切换模式本身不调用模型。
3. 新建会话，在输入框上方选择“决策模式”，再发送消息。聊天模型仍单独选择；不要把决策模型设为聊天模型。

显式选择模式会更新后续新会话的默认值。每个会话在首次执行被服务端接受后锁定模式和策略配置，即使随后取消或服务报错，也需要新建会话才能换模式。恢复旧会话不会改变全局默认值，分支继承来源会话的模式和配置。密钥轮换使用供应商当前凭据，不把密钥写进执行配置快照。

## SDK 配置

先通过现有 `ModelSettingsManager` 或 WebUI 配好供应商。决策配置引用 `MS_AGENT_HOME/settings.json` 中的供应商 ID：

```python
from ms_agent.config.decision import DecisionSettings
from ms_agent.project.paths import global_home

DecisionSettings(global_home()).update(
    decision={"provider": "ath", "model": "decision-model-preview"},
    default_execution_mode="decision",
)
```

对于直接构建的 Agent，在原有 YAML 中加入以下配置。主模型配置继续使用原来的 `llm` 字段：

```yaml
execution:
  mode: decision
decision:
  provider: ath
  model: decision-model-preview
  protocol: systemone
  policy_version: v1
  context:
    enabled: true
    trigger_ratio: 0.85
    target_ratio: 0.65
    keep_probability_max: 0.05
  supervision:
    enabled: true
    intervention_threshold: 0.95
session_log:
  enabled: true
compaction:
  enabled: true
  context_limit: 128000
  reserved_buffer: 20000
```

`context_limit` 应按所用聊天模型的容量配置，`reserved_buffer` 为输出留空间。示例中的数值不是模型能力探测结果。直接 SDK/YAML 的模式由显式配置决定；WebUI 的会话锁由 SDK `SessionManager.prepare_execution()` 维护。TUI 使用所选会话的模式，并在启动决策会话时固定其配置。

`DecisionSettings` 校验配置而不试探服务。决策模式需要保留会话日志；禁用日志会明确报错。若关闭上下文压缩，生命周期监督仍可单独运行。

## 输入输出协议

当前适配器支持百炼兼容的 System One 接口，向 `base_url + /systemone` 发送 JSON。它不使用 Chat Completions 的 `messages`、流式文本或 tool calls：

```json
{
  "model": "decision-model-preview",
  "state": {"test_result": {"return_code": 1}},
  "questions": {
    "passed": {
      "type": "noul",
      "instructions": "测试是否通过？"
    }
  }
}
```

响应通过相同问题 ID 对齐，例如 `answers.passed = {"type":"noul","noul":0.01}`。`noul` 是命题成立的模型分数，`choice` 返回选项 ID 及分布，`score` 返回有序标准上的分布与期望分数。分数未经本项目校准，不能当作任务完成率。

`DecisionRequest`、`DecisionResponse` 和 `DecisionClient` 定义公共契约；`SystemOneClient` 负责网络协议。后续供应商可实现同一客户端契约，声明输入限制与支持的问题类型。当前没有通过普通聊天模型模拟决策协议。

## 上下文如何缩小

预算使用完整可见消息、工具定义、推理字段和图片估算；没有可靠 tokenizer 时使用保守估算，并在真正调用主模型前再次检查。低于触发阈值时不调用决策模型。

- 系统提示、用户要求、最近两组完整工具调用、未解决的明确失败、图片和带签名的消息保持完整。
- 其余工具输出按完整内容评估。仅当“完整内容仍需保留”的分数不高于 0.05 时，才替换为短预览和原文引用。
- 若筛选后已达到目标预算，直接提交，不必再生成摘要。
- 若筛选不足、响应无效、超时或服务不可用，丢弃筛选候选，改用筛选前的上下文生成 LLM 摘要。默认最多四个摘要片段，使用同一个主模型并请求关闭摘要推理。
- 候选必须缩小上下文、符合工具调用协议且未过期，才提交一次日志事务。保留内容仍超出硬上限时明确停止，不重复压缩同一快照，也不直接删除受保护证据。

原始会话日志不被覆盖。`context---context_read` 可按 `ctx:<原始 seq>:<tool_call_id>` 分页读取原文，最多返回 8,000 字符；引用只在当前会话或其合法分支中解析。标准模式默认只使用有界摘要；Agent 内的 `/compact` 也使用摘要，不按时间裁剪旧输出。

## 生命周期监督的边界

过程检查先由代码筛出重复动作、相同输出或连续失败的信号，再请求语义判断。结束检查针对已有工具执行的任务，检查候选回复是否在明确失败或未满足要求时宣称完成。没有工具的普通问答不会因此被强制继续。

每个用户任务最多进行六次过程检查、两次结束检查；规则与语义监督合计最多注入两次过程反思，结束时最多纠正一次。过程反思之间至少间隔三组工具调用。反馈引用实际工具证据，使用固定提示模板；不采用工具输出中的指令。等待用户、如实报告阻塞、取消、权限拒绝和硬执行上限均不应被监督器绕过。

检查发生在结束 checkpoint、记忆写入和等待下一次输入之前。内部反馈不会变成新用户任务，也不会重置检查预算。次数、证据引用和耗时写入 `decision_event`，无需重复记录完整判断输入。决策请求超时默认是过程/结束 2 秒、压缩筛选 5 秒；连续失败后短暂暂停请求。

## 验证与限制

协议、筛选、摘要、取消、恢复和会话锁的离线测试在 `tests/decision/` 和 `webui/backend/tests/test_decision_mode.py`。真实服务验证需显式选择供应商和授权调用：

```bash
MS_AGENT_HOME=/path/to/test-home python examples/capability/decision_model/sdk_smoke.py \
  --run --provider ath --model deepseek-v4.1-flash --output /tmp/decision-smoke.json
```

这个脚本使用合成日志，验证真实协议、筛选或摘要、原文恢复和结束监督。它会记录实际分数与路径；模型判断不确定时允许转向摘要，不将这种情况伪装为筛选成功。不能把这些小样本当作速度、成本或成功率的基准评测。发布性能结论前，还需固定主模型和缓存条件，比较标准模式、仅规则、仅摘要以及完整决策模式。
