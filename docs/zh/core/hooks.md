# Hooks

Hooks把外部脚本接到Agent或工具事件上，用于附加上下文、检查请求或影响授权。它们与进程内[Callbacks](callbacks.md)不同；[Plugins](plugins.md)可以作为Hook资源的来源。

## 支持的事件

| 事件 | 关注点 |
| --- | --- |
| SessionStart | 会话启动上下文 |
| UserPromptSubmit | 用户输入检查 |
| PreToolUse | 工具调用前检查、参数或授权结果 |
| PostToolUse | 调用结果及附加上下文 |
| PermissionRequest | 权限请求扩展 |
| Stop | 回复结束检查 |

`SubagentStop`可出现在配置注册表，但当前不作为已触发功能承诺。当前执行器是 `command`；HTTP/Prompt/Agent执行器的字段能解析不等于后端已经注册，见[执行器RFC](../development/rfcs/hooks-executors.md)。

## 配置脚本

```yaml
hooks:
  SessionStart:
    - hooks:
        - type: command
          command: python hook_check.py
          timeout: 10
          fail_closed: true
```

脚本从stdin接收JSON。先用只读取事件、不做外部写入的脚本测试：

```python
# hook_check.py
import json
import sys

event = json.load(sys.stdin)
print(json.dumps({'additional_context': 'This session uses reviewed project instructions.'}))
```

命令通过参数拆分执行，不隐式经过shell；管道、重定向等需要明确使用shell且审查风险。运行目录和环境变量按Hook来源上下文处理，不会无条件传递宿主全部环境。

## 结果与失败策略

退出码2用于阻断，标准错误提供原因；正常JSON输出经响应适配器处理。超时/找不到命令时，`fail_closed`决定是否按拒绝处理。部署策略应显式选择失败行为，不能把脚本异常默认为允许。

插件Hook携带插件根目录、数据目录和会话来源，避免脚本靠猜测工作目录查找资源。Hook脚本本身是可信执行扩展，不等于普通模型工具调用的完整权限覆盖。

下一步：[权限](permissions.md)、[Plugins](plugins.md)。实现：`hooks/registry.py`、`factory.py`、`executors/command.py`、`response_adapter.py`。
