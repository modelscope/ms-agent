# Agent Hub

Agent Hub用于跨框架复用智能体资产，例如指令、技能和记忆。它处理的是文件识别、转换、合并与同步，不是把另一个框架的全部运行时搬进MS-Agent。

## 先检查本地资产

```bash
ms-agent agent --help
ms-agent agent status -f ms-agent --local-dir ./demo-agent-home
```

使用专门的测试副本，避免直接操作日常使用的Agent home。`--local-dir`显式指定源根，框架名称应来自当前CLI支持列表。

## 转换前先预览

```bash
ms-agent agent convert --from-framework ms-agent --target-framework hermes \
  --local-dir ./demo-agent-home --out-dir ./converted-agent --dry-run
```

根据预览检查目标路径、文件类型和冲突；确认后才去掉dry-run。不同框架对同一概念的字段、格式和作用域可能不同。格式转换成功不代表目标框架的运行效果完全相同。

## 上传、下载与持续同步

| 操作 | 需要关注 |
| --- | --- |
| upload | 远端仓库、可见性、凭据与文件清单 |
| download | 目标目录、框架转换、合并与备份 |
| watch | 持续文件监听、是否拉取远端、进程关闭 |
| backups / restore | 备份来源、恢复目标及覆盖风险 |

上传命令的默认仓库可见性可能是public。先 `--dry-run` 检查文件清单并主动选择可见性，不上传密钥、个人资料或未经确认的记忆。网络命令使用账户凭据；不是普通模型API Key的替代用途。

## 验证迁移结果

检查指令是否保留含义、技能资源是否完整、记忆是否仍在正确作用域；再在目标框架运行一个小任务。发现冲突先查备份和差异，不能为通过同步而无条件覆盖用户内容。

下一步：[Skills](skills.md)、[记忆](memory.md)、[CLI参考](../development/cli-reference.md)。实现：`agent_hub/`、`cli/agent.py`。
