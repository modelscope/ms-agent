# 定时任务

先确认Agent能手动完成目标任务，再定时运行。周期任务会重复调用模型或工具，可能产生费用及副作用；用小范围、可重复执行的任务开始。

## 创建并检查

```bash
ms-agent cron create 'every 30m' '检查项目状态并生成简短摘要，不修改源文件' --name status-check --project /path/to/project/agent.yaml --timeout 120
ms-agent cron list --json
```

`--project`可指向已准备的 Agent 配置文件，或能解析出正确 Agent 配置的目录；首次验证推荐明确的 `agent.yaml`。若同一目录还有 `workflow.yaml`，不要假设目录会优先选择 Agent 配置。模型与工具配置需适合无人值守执行，任务超时用秒表示。记录返回的job ID，检查计划、启用状态和时区。支持固定间隔、一次性时间和cron表达式，详细语义见[调度](../core/scheduling.md)。

如果调度进程使用了自定义工作目录，查看状态和任务列表时也传入同一个 `--workspace` 路径，例如 `ms-agent cron status --workspace /path/to/cron` 和 `ms-agent cron list --workspace /path/to/cron`。显式路径优先于 `MS_AGENT_CRON_WORKSPACE`。这个目录保存调度状态，与 `--project` 选择的 Agent 配置不同。

## 手动运行一次

将下方 `JOB_ID`替换为真实ID：

```bash
ms-agent cron run JOB_ID
ms-agent cron history JOB_ID
ms-agent cron output JOB_ID --last
```

确认实际产物、错误和执行时间。模型回复“完成”不等于目标文件存在；需要人工授权的操作在无人值守环境可能拒绝。

## 启动调度进程

```bash
ms-agent cron start --foreground
```

保持该终端运行，另开终端用 `ms-agent cron status`检查。支持后台daemon的平台也可使用不带foreground的start；不支持fork的平台应使用前台或服务管理器。关闭浏览器不是停止Cron的方法。

## 暂停与停止

```bash
ms-agent cron pause JOB_ID
ms-agent cron resume JOB_ID
ms-agent cron stop
```

暂停任务与停止调度进程不同，已发生的外部副作用不会回滚。删除任务使用 `ms-agent cron remove JOB_ID`，执行前确认历史和产物备份。不要假设重启后自动补跑错过的所有时间点。

## 声明式任务

`ms-agent cron import`读取任务声明。迁移机器时同时检查任务仓库、工作目录、时区、环境变量和凭据；任务ID本身不足以复现环境。全部命令见[CLI参考](../development/cli-reference.md)。
