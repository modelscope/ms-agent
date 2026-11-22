# TUI interaction

The TUI provides ongoing terminal interaction over shared SDK execution and sessions, without a browser frontend. Complete {ref}`terminal installation <terminal>` first.

## Start

```bash
ms-agent tui --work-dir ./demo-project
```

Add `--config ./agent.yaml` for an existing configuration and `--env ./.env` for dotenv input. Create or verify the workspace first. The default permission mode is restricted, an alias for interactive.

Initial tool setup may take time. Submit a small task when the prompt appears. The bottom bar shows model, tokens, permissions, and session information. Type `/` for completion and use the up arrow for current input history.

## Useful commands

| Command | Purpose |
| --- | --- |
| `/help` | Commands available in this interface |
| `/model` | Model selection/configuration; follow prompts |
| `/tools` | Configured tools |
| `/sessions` | Project session list |
| `/resume <number-or-ID>` | Reopen a session |
| `/new` | Start another session |
| `/context` / `/usage` | Context and usage |
| `/compact` | Prune older tool output manually |
| `/stop` | Request execution stop |
| `/quit` | Exit interaction |

Commands depend on the interface and installed extensions. Prefer `/help` over another agent product's shortcut list. Hermes options such as `--tui` or `--continue` are not MS-Agent commands.

## Input, approval, and interruption

Input uses prompt_toolkit by default; multiline/paste shortcuts differ between terminals. Prepare long text in an editor, paste it, and inspect it before sending. Attachment support depends on the parser/model; a path written in a message is not proof that pixels were uploaded.

Inspect commands and targets before approval. Ctrl-C may interrupt input or execution; check actual state and use stop/exit if work remains active. Review generated files after interruption. Cancellation is not rollback.

## Resume and record events

Restart from the same workspace and use `/sessions` and `/resume`. Session switching happens at lifecycle boundaries; do not modify active logs behind the runtime.

```bash
ms-agent tui --work-dir ./demo-project --emit-events ./events.jsonl
```

Events can contain task/tool data; redact before sharing. Without a TTY, input can fall back to a simpler mode. A successful piped invocation is not a complete interactive test.

Next: [CLI scripting](cli.md), [Sessions](../core/sessions.md), [Permissions](../core/permissions.md).
