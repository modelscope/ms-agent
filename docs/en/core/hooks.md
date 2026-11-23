# Hooks

Hooks attach scripts to agent/tool events to add context, inspect requests, or influence authorization. They differ from in-process [callbacks](callbacks.md); [plugins](plugins.md) can supply hook resources.

## Events

| Event | Purpose |
| --- | --- |
| SessionStart | Session-start context |
| UserPromptSubmit | Input inspection |
| PreToolUse | Pre-call checks, arguments, authorization |
| PostToolUse | Results and additional context |
| PermissionRequest | Permission-request extension |
| Stop | End-of-response checks |

`SubagentStop` is accepted by the registry but is not promised as a currently triggered event. The implemented executor is `command`. Parsing HTTP/Prompt/Agent fields does not register those executors; see the [RFC](../development/rfcs/hooks-executors.md).

## Configure a script

```yaml
hooks:
  SessionStart:
    - hooks:
        - type: command
          command: python hook_check.py
          timeout: 10
          fail_closed: true
```

Scripts receive JSON on stdin. Start with a script that inspects the event without external writes:

```python
# hook_check.py
import json
import sys

event = json.load(sys.stdin)
print(json.dumps({'additional_context': 'This session uses reviewed project instructions.'}))
```

Commands are split into arguments, not implicitly executed through a shell. Pipes/redirection require an explicit shell and appropriate review. Working directory and environment follow source context; the full host environment is not passed unconditionally.

## Results and failure policy

Exit code 2 blocks an operation, with stderr providing the reason. Successful JSON output is interpreted by a response adapter. For timeouts/missing commands, `fail_closed` determines denial behavior. Choose failure policy deliberately rather than assuming a broken script permits execution.

Plugin hooks carry plugin-root, data-directory, and session context. Do not guess paths. Hook scripts are trusted execution extensions, not ordinary model-tool calls with identical permission coverage.

Next: [Permissions](permissions.md), [Plugins](plugins.md). Implementation: `hooks/registry.py`, `factory.py`, `executors/command.py`, `response_adapter.py`.
