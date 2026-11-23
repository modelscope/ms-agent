# Hooks

Hooks把外部脚本接到Agent或工具事件上，用于附加上下文、检查请求或影响授权。它们与进程内[Callbacks](callbacks.md)不同；[Plugins](plugins.md)可以作为Hook资源的来源。

## 支持的事件

| 事件 | 关注点 |
| --- | --- |
| SessionStart | 启动脚本；当前回调桥不自动注入返回的上下文 |
| UserPromptSubmit | 用户输入检查 |
| PreToolUse | 工具调用前检查、参数或授权结果 |
| PostToolUse | 调用结果及附加上下文 |
| PermissionRequest | 权限请求扩展 |
| Stop | 回复结束检查 |

`SubagentStop` 的配置可解析，但当前没有触发入口。当前可用执行器只有 `command`；未启用的类型会在加载时告警并跳过，HTTP、Prompt 和 Agent 类型即使列入 `enabled_executors` 也不会创建可用的执行后端，见[执行器RFC](../development/rfcs/hooks-executors.md)。

## 创建与配置

在已安装 MS-Agent 的 Python 环境中，新建一个测试目录，保存以下文件。`python` 必须指向安装 SDK 的解释器。

```text
hook-demo/
├── agent.yaml
├── hook_check.py
└── verify_hook.py
```

`agent.yaml` 的 Hook 部分如下；实际运行 Agent 时将其合入自己的模型配置。`Config.from_task()` 会设置 `local_dir`，命令工作目录优先使用它；未设置时使用项目工作目录。`cwd` 事件字段描述项目范围，不一定等于脚本进程的工作目录。

```yaml
# agent.yaml
output_dir: ./work
tools:
  file_system:
    mcp: false
    include: [read_file]
hooks:
  SessionStart:
    - hooks:
        - type: command
          command: python hook_check.py
          timeout: 10
          fail_closed: true
  PreToolUse:
    - matcher: '*'
      hooks:
        - type: command
          command: python hook_check.py
          timeout: 10
          fail_closed: true
```

```python
# hook_check.py
import json
from pathlib import Path
import sys

payload = json.load(sys.stdin)
if payload['event'] == 'SessionStart':
    print(json.dumps({'additional_context': 'Hook demo started.'}))
elif payload['event'] == 'PreToolUse':
    args = payload.get('tool_args', {})
    path = str(args.get('path', '')).strip()
    if Path(path).name == 'blocked.txt':
        print('blocked.txt is reserved by this demo.', file=sys.stderr)
        sys.exit(2)
    # 仅修改已有参数；不在普通工具中新增未知字段。
    updated = {**args, 'path': path.strip()} if 'path' in args else args
    print(json.dumps({'updated_input': updated,
                      'additional_context': 'Hook demo checked the request.'}))
else:
    print('{}')
```

命令通过参数拆分执行，不隐式经过 shell；管道或重定向需显式调用 shell 并审查风险。相对脚本路径按上述命令工作目录解析；也可填写已审查的绝对路径。仅允许列表内的宿主环境变量和 Hook 上下文变量传入，凭据不会无条件继承。插件还提供 `MS_AGENT_PLUGIN_ROOT` / `MS_AGENT_PLUGIN_DATA`。

## stdin 与 stdout 契约

以下是原生 Hook 的代表性输入，路径和会话 ID 随运行变化：

```json
{"event":"SessionStart","session_id":"demo","project_path":"/tmp/hook-demo/work","cwd":"/tmp/hook-demo/work","extra":{}}
```

```json
{"event":"PreToolUse","session_id":"demo","project_path":"/tmp/hook-demo/work","cwd":"/tmp/hook-demo/work","tool_name":"file_system---read_file","tool_args":{"path":"notes.txt"},"tool_input":{"path":"notes.txt"},"extra":{}}
```

`event` 决定事件类型，`session_id` 是会话标识；`tool_name` 是匹配工具名，`tool_args` 是参数，`tool_input` 为兼容别名。启用外部来源时还可能有平台工具名字段。不要假定输入只包含示例里的字段。

| 输出/结果 | 当前行为 |
| --- | --- |
| 退出 0，空输出或 `{}` | `pass`，继续正常事件流程 |
| `additional_context` | 附加上下文；Pre/PostToolUse 可形成消息附件。SessionStart 回调桥仅执行脚本，不自动将该字段加入模型消息 |
| `updated_input`（对象） | 参数替换；PreToolUse 使用当前工具 schema 内的字段。SessionStart 没有工具参数可修改 |
| `decision: deny` 或退出 2 | 拒绝；退出 2 的 stderr 是原因。PreToolUse 等可阻断事件会停止该操作 |
| 其他非零退出、命令缺失、超时 | `fail_closed: true` 时为 `deny`，否则为 `error`，本身不阻断 |
| 退出 0 但 stdout 不是合法 JSON | `error`；当前 `fail_closed` 不会将解析错误转为拒绝，所以拒绝路径应显式退出 2 |

stdout 只输出一个 JSON 对象，诊断写 stderr。SessionStart 不是可阻断工具事件，不应依靠它拒绝工具；使用 PreToolUse。`allow` 不会解除工具权限系统中的其他安全规则。

## 离线验证与实际接入

先只检查脚本输入输出（无文件写入、无模型调用）：

```bash
printf '%s' '{"event":"SessionStart","session_id":"demo"}' | python hook_check.py
printf '%s' '{"event":"PreToolUse","tool_args":{"path":"blocked.txt"}}' | python hook_check.py
```

预期第一条输出附加上下文并退出 0；第二条 stderr 提供原因并退出 2。

保存以下脚本，通过真实 Hook 工厂和执行器验证配置及拒绝路径。它不会运行 Agent 或模型：

```python
# verify_hook.py
import asyncio
from ms_agent.config import Config
from ms_agent.hooks.factory import build_hook_runtime

async def main():
    config = Config.from_task('./agent.yaml')
    hooks = build_hook_runtime(config, session_id='demo')
    started = await hooks.run_session_start(None, [])
    allowed, _ = await hooks.run_pre_tool_use(
        'file_system---read_file', {'path': ' notes.txt '})
    denied, _ = await hooks.run_pre_tool_use(
        'file_system---read_file', {'path': 'blocked.txt'})
    assert started.additional_context == 'Hook demo started.'
    assert allowed.action == 'pass' and allowed.updated_args['path'] == 'notes.txt'
    assert denied.action == 'deny' and denied.exit_code == 2
    print('SessionStart=pass, PreToolUse=pass/deny')

asyncio.run(main())
```

```bash
python verify_hook.py
```

预期退出 0。可另将命令改为不存在的程序、或使用超出 `timeout` 的测试脚本，检查上述失败策略；测试完成后恢复配置。

实际接入：合并 Hook 配置和模型配置后，用 `ms-agent run --config ./agent.yaml --query '读取 notes.txt'` 开启新任务。先在配置的输出目录 `./work/` 中准备普通 `notes.txt`，检查 Hook 执行事件和工具结果；同目录中的 `blocked.txt` 应被拒绝且显示原因。保持文件位于工具允许的目录内。只有实际工具调用才会触发 PreToolUse，模型未调用工具时不能据此判断 Hook 失效。CLI/SDK 的 Hook 事件观察与脚本离线验证是两类证据。示例目录可在关闭任务后整体移除，不清理已有全局 Hook 配置。

插件Hook携带插件根目录、数据目录和会话来源，避免脚本靠猜测工作目录查找资源。Hook脚本本身是可信执行扩展，不等于普通模型工具调用的完整权限覆盖。

下一步：[权限](permissions.md)、[Plugins](plugins.md)。实现：`hooks/registry.py`、`factory.py`、`executors/command.py`、`response_adapter.py`。
