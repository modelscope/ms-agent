# Plugins

插件把技能、命令、Agent定义、Hooks、MCP等资源作为一个单元安装和装配。它不是任意第三方代码的通用执行容器，也不等同于单个Skill。

## 从空目录创建本地插件

在已安装 MS-Agent 的环境执行。所有管理命令显式使用独立 `MS_AGENT_HOME` 和测试项目路径，避免加载日常项目中的插件，也不会改变你已有的全局插件。

```bash
DEMO="$(mktemp -d)"
mkdir -p "$DEMO/my-plugin/.claude-plugin" "$DEMO/my-plugin/skills/greeting" "$DEMO/project"
```

保存以下两个文件：

```text
my-plugin/
├── .claude-plugin/plugin.json
└── skills/greeting/SKILL.md
```

`$DEMO/my-plugin/.claude-plugin/plugin.json`：

```json
{"name":"docs-demo","version":"0.1.0","description":"A harmless greeting skill."}
```

`$DEMO/my-plugin/skills/greeting/SKILL.md`：

```markdown
---
name: docs-greeting
description: Greet the user without tools or external services.
---
# Greeting
Reply with: Hello from docs-demo.
Do not run tools, access files, or contact external services.
```

这是当前支持的 Claude 格式 manifest；`name` 形成插件 ID，`version` 记录版本，加载器发现 `skills/` 中的资源。只有 manifest 而没有任何可加载资源的目录不是合法插件。先检查所有文件，特别是第三方插件中的脚本和 MCP 配置。

## 禁用安装、启用与资源发现

```bash
MS_AGENT_HOME="$DEMO/home" ms-agent plugin install "$DEMO/my-plugin" --disabled --project-path "$DEMO/project"
MS_AGENT_HOME="$DEMO/home" ms-agent plugin list --json --project-path "$DEMO/project"
```

预期 ID 为 `docs-demo`，`enabled` 为 false，状态为 `disabled`。安装只复制并登记资源，不执行技能。

在 `$DEMO/verify_plugin.py` 保存以下离线检查脚本。它创建新的插件运行时，把资源接入技能目录，并读取技能正文；不调用模型、工具或外部服务。

```python
import os
from pathlib import Path
import sys
from omegaconf import OmegaConf
from ms_agent.plugins.runtime import PluginRuntime
from ms_agent.skill.catalog import SkillCatalog

config = OmegaConf.create({'skills': {'sources': [], 'auto_discover': False}})
runtime = PluginRuntime(global_root=Path(os.environ['MS_AGENT_HOME']))
runtime.start_sync(sys.argv[1], 'docs-demo-check', config=config)
catalog = SkillCatalog(config=config.skills)
catalog.load_from_config(config.skills)
found = [skill for skill in catalog.get_enabled_skills().values()
         if skill.name == 'docs-greeting']
assert bool(found) == (sys.argv[2] == 'enabled')
if found:
    assert 'Hello from docs-demo.' in found[0].content
    print('docs-greeting discovered with its full content')
else:
    print('docs-greeting not loaded')
```

```bash
MS_AGENT_HOME="$DEMO/home" python "$DEMO/verify_plugin.py" "$DEMO/project" disabled
MS_AGENT_HOME="$DEMO/home" ms-agent plugin toggle docs-demo --enable --project-path "$DEMO/project"
MS_AGENT_HOME="$DEMO/home" ms-agent plugin list --json --project-path "$DEMO/project"
MS_AGENT_HOME="$DEMO/home" python "$DEMO/verify_plugin.py" "$DEMO/project" enabled
```

预期：启用前检查输出 `not loaded`；启用后列表的 `enabled` 为 true，检查能发现 `docs-greeting` 及完整正文并退出 0。新建 Agent 后，该资源成为可用技能；是否由模型选择仍取决于任务和技能策略。

默认作用域为 global（本例是隔离的 `$DEMO/home`）；项目安装使用 `--scope project --project-path ...`，后续管理保持相同作用域。`--link` 链接本地来源，源文件修改会影响后续加载；`--force` 替换已有托管副本，先备份。

## 停用与清理

```bash
MS_AGENT_HOME="$DEMO/home" ms-agent plugin toggle docs-demo --disable --project-path "$DEMO/project"
MS_AGENT_HOME="$DEMO/home" python "$DEMO/verify_plugin.py" "$DEMO/project" disabled
MS_AGENT_HOME="$DEMO/home" ms-agent plugin uninstall docs-demo --purge --project-path "$DEMO/project"
MS_AGENT_HOME="$DEMO/home" ms-agent plugin list --json --project-path "$DEMO/project"
```

预期：停用后的新运行时不发现示例技能；卸载后列表为空。`--purge` 仅删除这个隔离 home 中 `docs-demo` 的托管副本，源插件与 `$DEMO/project` 保留。结束进程后可移除本次 `$DEMO`，不要清理已有真实项目或全局 home。

## 装配过程

```{mermaid}
flowchart TD
 A[安装来源] --> B[托管目录和配置记录]
 B --> C[按作用域选择启用插件]
 C --> D[解析资源]
 D --> E[技能 / 命令 / Agent / Hooks / MCP]
 E --> F[接入SDK运行时]
```

资源装配与实际执行分开。插件声明Hooks并不意味着任何执行器类型均实现；Hook来源上下文由运行时传递。全局、项目、会话覆盖要按配置来源理解。

## 更新和移除

用 `ms-agent plugin --help`查看管理命令。停用不等于撤销已经发生的文件/网络操作；卸载和删除文件也有不同语义。CLI 管理命令不会刷新另一个进程中已经创建的运行时。现有会话可能仍持有旧资源；启停或更新后新建会话/实例，或由宿主显式调用运行时重载接口后再检查资源。

当前插件装配能力与未来管理UI、供应链签名、增量重载的提案分开，见[Plugins RFC](../development/rfcs/plugins.md)。

下一步：[Skills](skills.md)、[Hooks](hooks.md)、[MCP](mcp-client.md)。实现：`plugins/installer.py`、`config_manager.py`、`registry.py`、`runtime.py`。
