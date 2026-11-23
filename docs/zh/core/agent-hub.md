# Agent Hub

Agent Hub用于跨框架复用智能体资产，例如指令、技能和记忆。它处理的是文件识别、转换、合并与同步，不是把另一个框架的全部运行时搬进MS-Agent。

## 先检查本地资产

先安装 MS-Agent，在仓库根目录执行以下命令。示例从无敏感信息的合成资产开始；`mktemp` 创建独立目录，不读取或修改日常 Agent home。

```bash
DEMO="$(mktemp -d)"
mkdir -p "$DEMO/source/skills/greeting"
printf '# Instructions\nOnly greet the user.\n' > "$DEMO/source/AGENTS.md"
printf '%s\n' '---' 'name: greeting' 'description: Say hello without tools.' '---' '# Greeting' 'Reply with Hello.' > "$DEMO/source/skills/greeting/SKILL.md"
ms-agent agent status -f ms-agent --local-dir "$DEMO/source"
```

预期：显示测试指令和 `greeting` 技能。也可以将自己的资产副本放入 `source`，先移除凭据和私人内容。

使用专门的测试副本，避免直接操作日常使用的Agent home。`--local-dir`显式指定源根，框架名称应来自当前CLI支持列表。

## 转换前先预览

```bash
env -u TRY_EXP_FRAMEWORKS ms-agent agent convert --from-framework ms-agent --target-framework qwenpaw \
  --local-dir "$DEMO/source" --out-dir "$DEMO/converted" --dry-run
```

预期：输出转换计划，目标为 QwenPaw；`--dry-run` 不写入目标目录、不上传，也不启动监听。默认支持 `ms-agent` 与 `qwenpaw`。Hermes 属于实验框架，需要先设置 `TRY_EXP_FRAMEWORKS=true`；预览不会绕过该检查。

根据预览检查目标路径、文件类型和冲突；确认后才去掉 `--dry-run`。不同框架对同一概念的字段、格式和作用域可能不同。格式转换成功不代表目标框架的运行效果完全相同。

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

示例结束后可以保留 `$DEMO` 查看源文件；确认它是本次临时目录后删除该目录即可，不要清理原始 Agent home。

下一步：[Skills](skills.md)、[记忆](memory.md)、[CLI参考](../development/cli-reference.md)。实现：`agent_hub/`、`cli/agent.py`。
