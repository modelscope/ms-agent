# 调度

调度让任务在约定时间触发，而不是让一次模型会话无限循环。Cron模块将任务定义、时间计算、执行记录和通知分开；运行中的调度进程负责实际触发。

## 生命周期

```{mermaid}
stateDiagram-v2
 [*] --> Enabled: 创建或导入
 Enabled --> Running: 到期或手动触发
 Running --> Enabled: 完成并计算下次时间
 Running --> Failed: 执行失败
 Failed --> Enabled: 按调度继续或人工处理
 Enabled --> Paused: 暂停
 Paused --> Enabled: 恢复
```

图中的状态用于说明流程，具体持久字段以任务记录为准。一次性、固定间隔、cron表达式和时区有不同语义，先确认下一次执行时间再无人值守运行。

## 检查表达式

```python
from ms_agent.cron.parser import parse_schedule

schedule = parse_schedule('every 30m')
assert schedule.kind == 'interval'
assert schedule.interval_seconds == 1800
```

这只解析时间，不执行任务。CLI管理步骤见[定时任务教程](../user-guide/scheduled-tasks.md)。

## 运行与存储

服务负责读取任务仓库、选择到期任务并调用执行器；heartbeat和通知是独立环节。创建任务不等于调度器已启动，浏览器关闭也不等于后台调度进程停止。

进程重启、超时、并发限制和产物保存应分别验证。不要假设错过的时间会自动补跑，也不要假设第三方操作天然幂等。周期任务应有明确输出位置、预算和停止方式。

权限和模型配置必须适合无人值守环境：需要交互确认但没有处理器的操作可能拒绝。先手动运行一个无害任务并检查历史，再启用周期执行。

实现：`cron/parser.py`、`repository.py`、`scheduler.py`、`executor.py`、`service.py`。下一步：[权限](permissions.md)、[部署](../user-guide/deployment.md)。
