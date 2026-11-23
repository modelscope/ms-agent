# Plugins

插件把技能、命令、Agent定义、Hooks、MCP等资源作为一个单元安装和装配。它不是任意第三方代码的通用执行容器，也不等同于单个Skill。

## 安装一个可信本地插件

先检查插件目录及其脚本，再安装为禁用状态：

```bash
ms-agent plugin install ./my-plugin --disabled
ms-agent plugin list --json
```

确认ID和内容后再启用：

```bash
ms-agent plugin toggle PLUGIN_ID --enable
```

将 `PLUGIN_ID` 替换为列表中的实际ID。默认作用域global；项目安装使用 `--scope project --project-path /path/to/project`。`--link`对本地来源建立链接，开发方便但源文件修改会影响运行；`--force`会替换已有副本，使用前备份。

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

用 `ms-agent plugin --help`查看管理命令。停用不等于撤销已经发生的文件/网络操作；卸载和删除文件也有不同语义。运行中的会话可能仍持有资源，按入口要求刷新或重新开始，不承诺增量热重载已完整落地。

当前插件装配能力与未来管理UI、供应链签名、增量重载的提案分开，见[Plugins RFC](../development/rfcs/plugins.md)。

下一步：[Skills](skills.md)、[Hooks](hooks.md)、[MCP](mcp-client.md)。实现：`plugins/installer.py`、`config_manager.py`、`registry.py`、`runtime.py`。
