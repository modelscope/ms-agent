# Hooks

Hooks attach scripts to agent/tool events to add context, inspect requests, or influence authorization. They differ from in-process [callbacks](callbacks.md); [plugins](plugins.md) can supply hook resources.

## Events

| Event | Purpose |
| --- | --- |
| SessionStart | Start script; the current callback bridge does not inject returned context |
| UserPromptSubmit | Input inspection |
| PreToolUse | Pre-call checks, arguments, authorization |
| PostToolUse | Results and additional context |
| PermissionRequest | Permission-request extension |
| Stop | End-of-response checks |

`SubagentStop` configuration is parsed but has no current trigger. Only the `command` executor is implemented. Disabled types are warned about and skipped during loading; listing HTTP, Prompt, or Agent in `enabled_executors` does not create an executable backend; see the [RFC](../development/rfcs/hooks-executors.md).

## Create and configure

Create these files in a separate test directory, using a Python environment with MS-Agent installed. `python` must select that interpreter.

```text
hook-demo/
├── agent.yaml
├── hook_check.py
└── verify_hook.py
```

The following is the Hook part of `agent.yaml`; merge it into your model configuration for an actual Agent run. `Config.from_task()` sets `local_dir`, which is the command working directory when present; otherwise the project directory is used. The event's `cwd` describes project scope, not necessarily the subprocess working directory.

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

Commands are split into arguments, not run through a shell. Pipes/redirection require an explicit reviewed shell. Relative script paths resolve from the command working directory; a reviewed absolute path also works. Only allowlisted host variables and Hook context variables are inherited, not all credentials. Plugins additionally provide `MS_AGENT_PLUGIN_ROOT` / `MS_AGENT_PLUGIN_DATA`.

## stdin and stdout contracts

Representative native inputs follow; paths and session IDs vary by run:

```json
{"event":"SessionStart","session_id":"demo","project_path":"/tmp/hook-demo/work","cwd":"/tmp/hook-demo/work","extra":{}}
```

```json
{"event":"PreToolUse","session_id":"demo","project_path":"/tmp/hook-demo/work","cwd":"/tmp/hook-demo/work","tool_name":"file_system---read_file","tool_args":{"path":"notes.txt"},"tool_input":{"path":"notes.txt"},"extra":{}}
```

`event` identifies the event, `session_id` the session, `tool_name` the matched tool, and `tool_args` its arguments. `tool_input` is a compatibility alias. External sources may add platform tool names; accept additional fields.

| Output/result | Current behavior |
| --- | --- |
| Exit 0 with empty stdout or `{}` | `pass`, continue normal handling |
| `additional_context` | Pre/PostToolUse can attach context to messages. The SessionStart bridge executes the script but does not inject this field into model messages |
| `updated_input` object | Replaces arguments; use existing tool-schema fields in PreToolUse. SessionStart has no tool arguments to change |
| `decision: deny` or exit 2 | Denial; stderr explains exit 2. Blockable events such as PreToolUse stop the operation |
| Other nonzero exit, missing command, timeout | `deny` with `fail_closed: true`, otherwise nonblocking `error` |
| Exit 0 with invalid JSON | `error`; currently `fail_closed` does not turn parsing errors into denial, so deny explicitly with exit 2 |

Write one JSON object to stdout and diagnostics to stderr. SessionStart is not a blockable tool event; use PreToolUse for denial. `allow` does not remove other tool-permission safety checks.

## Offline checks and integration

First test stdin/stdout only, without writes or model calls:

```bash
printf '%s' '{"event":"SessionStart","session_id":"demo"}' | python hook_check.py
printf '%s' '{"event":"PreToolUse","tool_args":{"path":"blocked.txt"}}' | python hook_check.py
```

Expected: the first prints context and exits 0; the second gives a stderr reason and exits 2.

Save the following to check configuration through the actual Hook factory/executor. It does not run an Agent or model:

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

Expected exit: 0. Separately try a missing executable or a test script exceeding `timeout` to check the failure table, then restore the configuration.

For actual integration, merge Hook and model configuration, then start `ms-agent run --config ./agent.yaml --query 'Read notes.txt'`. Prepare a plain `notes.txt` inside the configured output directory `./work/`, then inspect Hook execution events and the tool result. A `blocked.txt` in that directory should be denied with the reason. Keep files within the tool's allowed directory. PreToolUse requires an actual tool call; a model choosing not to call tools is not evidence of a broken Hook. Record Agent lifecycle and offline-script checks separately. After stopping tasks, remove only this example directory, not existing global Hook settings.

Plugin hooks carry plugin-root, data-directory, and session context. Do not guess paths. Hook scripts are trusted execution extensions, not ordinary model-tool calls with identical permission coverage.

Next: [Permissions](permissions.md), [Plugins](plugins.md). Implementation: `hooks/registry.py`, `factory.py`, `executors/command.py`, `response_adapter.py`.
