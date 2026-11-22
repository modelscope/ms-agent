# 权限

MS-Agent将工具安全规则、用户授权意图和事件扩展分开处理。它们作用于受管理的工具调用，不是通用OS沙箱，也不保证直接运行的外部代码受同样保护。

## 调用经过哪些检查

```{mermaid}
flowchart TD
 A[工具调用与参数] --> B[检查工具和MCP可用性]
 B --> C[SafetyGuard路径与命令规则]
 C --> D{拒绝?}
 D -->|是| X[返回拒绝]
 D -->|否| E[PreToolUse Hook]
 E --> F[PermissionEnforcer融合授权]
 F --> G{允许?}
 G -->|否| X
 G -->|是| H[执行工具]
 H --> I[PostToolUse Hook与结果]
```

网络命令默认属于询问规则，不是永远不可放行的黑名单。没有交互处理器时，无法确认的操作会拒绝；不要通过关闭所有保护绕过一个配置问题。

## 一个保留默认保护的配置

```yaml
permission:
  mode: interactive
  allow_network: false
  safety_rules:
    allowed_directories: ["${PROJECT_ROOT}"]
    path_validation:
      read_policy: loose
```

`auto`按规则处理并保留强制询问，`strict`拒绝内层不确定的ask，`interactive`交给确认处理器。`restricted`是interactive的兼容名称。TUI默认restricted，不等于基础配置默认auto。

## 列表不是都追加

`safety_rules.patterns`、`sensitive_paths`、`sensitive_read_paths`、`dangerous_removal_paths`显式设置时会替换默认列表，空列表会清空对应保护。没有自定义需要时省略它们。外层`ask_rules`与内层安全列表的合并语义不同，不能照抄通用空配置模板。

允许目录还受工作目录和临时目录策略影响。`allow_temp_dir`默认允许系统临时工作区；读策略loose/strict与写范围不同。敏感读取保护和敏感写入保护也分别表达不同风险。

## 界面确认与部署边界

在批准前检查命令、目标路径和作用域；“始终允许”可能记住后续授权，不应当随手用于未知任务。Hook脚本、直接调用工具、远端MCP内部行为不等于经过当前管线的完整路径校验。

远程服务仍需认证、网络隔离和必要的容器边界。页面上的权限选项不是给服务器开放公网的理由。

下一步：[执行环境](execution-environments.md)、[Hooks](hooks.md)。实现：`permission/config.py`、`safety.py`、`enforcer.py`、`tools/tool_manager.py`。
