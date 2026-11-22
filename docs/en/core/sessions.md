# Sessions

A session connects inputs, replies, tool results, and recovery state. It answers “what happened, and where can I continue?” [Context](context.md) selects the next model input; [memory](memory.md) retains reusable knowledge across tasks.

## Logs and visible windows

`SessionLog` appends messages and compaction events. Compacted views become new records rather than overwriting originals. Recovery uses the visible boundary instead of resending all previously compacted history.

```yaml
session_log:
  enabled: true
  context_limit: 128000
  reserved_buffer: 20000
compaction:
  enabled: true
```

`session_log.dir` can specify the directory. Otherwise SDK logs are grouped by working directory under `$MS_AGENT_HOME/projects/<key>/`. The WebUI can supply managed project/session locations. Do not assume a universal `output/sessions` directory.

## Who owns the session?

| Interface | Responsibility |
| --- | --- |
| Direct SDK | Agent initializes logs, assembles context, and records output |
| WebUI | Adapter owns session selection/runtime while reusing SDK execution and storage |
| TUI | Selects/reopens sessions for the workspace and renders events |
| ACP/A2A | Maps external sessions or tasks to internal execution |

Sharing a working directory does not mean every interface automatically selects the same session. Use supported selection/recovery operations instead of copying logs and changing IDs.

## Interruption and persistence

Replies are saved before waiting for the next input. Interrupted turns retain what actually happened. After cancelling tools, inspect files and external operations: a session log is not a rollback system.

Do not edit JSONL or move active stores while a service is running. Back up metadata, conversation records, and project files together. Changing the working directory also changes the default project key.

## Use and troubleshoot

- Open project history in the WebUI; use `/sessions` in the TUI.
- If history is missing, check the working directory, `MS_AGENT_HOME`, and the interface's storage scope.
- If context is too large, adjust budgets/compaction instead of deleting the original log.

See [Projects and sessions](../user-guide/projects-sessions.md) and [Storage](../development/storage.md). Implementation: `session/session_log.py`, `project/session_manager.py`, interface runtimes.
